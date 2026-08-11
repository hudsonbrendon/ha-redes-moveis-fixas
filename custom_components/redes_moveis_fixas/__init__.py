"""Integração Redes Móveis Fixas."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.components.webhook import (
    async_generate_url as webhook_async_generate_url,
    async_register as webhook_async_register,
    async_unregister as webhook_async_unregister,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client, issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .api import RMFAuthError, RMFClient, RMFError
from .const import (
    CONF_ENTITY_ID,
    CONF_IBGE,
    CONF_INCLUIR_BETA,
    CONF_INTERVALO_COBERTURA,
    CONF_INTERVALO_ERBS,
    CONF_INTERVALO_MUNICIPIO,
    CONF_MODO,
    CONF_MONITOR_ID,
    CONF_MONITOR_SECRET,
    CONF_MONITORAR,
    CONF_OPERADORAS,
    CONF_PAISES,
    CONF_TOKEN,
    CONF_WEBHOOK_ID,
    DEFAULT_INTERVALO_COBERTURA_MIN,
    DEFAULT_INTERVALO_ERBS_H,
    DEFAULT_INTERVALO_MUNICIPIO_H,
    DISTANCIA_MINIMA_M,
    DOMAIN,
    INTERVALO_HEALTH,
    INTERVALO_MINIMO_PESSOA,
    INTERVALO_MONITORES,
    PLATFORMS,
    SUBENTRY_LOCAL,
    SUBENTRY_MONITOR_IOS,
    SUBENTRY_MUNICIPIO,
)
from .coordinator import (
    CoberturaCoordinator,
    ErbsCoordinator,
    HealthCoordinator,
    MonitoresCoordinator,
    MunicipioCoordinator,
)
from .services import async_setup_services
from .webhook import handle_webhook

_LOGGER = logging.getLogger(__name__)


@dataclass
class RMFRuntime:
    """Estado de runtime da entry."""

    client: RMFClient
    health: HealthCoordinator
    monitores: MonitoresCoordinator
    cobertura: dict[str, CoberturaCoordinator] = field(default_factory=dict)
    erbs: dict[str, ErbsCoordinator] = field(default_factory=dict)
    municipio: dict[str, MunicipioCoordinator] = field(default_factory=dict)


def _coords_do_estado(
    hass: HomeAssistant, entity_id: str
) -> tuple[float | None, float | None]:
    state = hass.states.get(entity_id)
    if state is None:
        return None, None
    lat = state.attributes.get("latitude")
    lon = state.attributes.get("longitude")
    if lat is None or lon is None:
        return None, None
    return float(lat), float(lon)


def _url_webhook(hass: HomeAssistant, webhook_id: str) -> str:
    """URL pública do webhook (exige external_url/cloud configurado)."""
    try:
        return webhook_async_generate_url(hass, webhook_id)
    except NoURLAvailableError as err:
        raise ConfigEntryNotReady(f"Sem URL externa pro webhook: {err}") from err


async def _provisionar_monitor(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
    client: RMFClient,
    webhook_id: str,
) -> None:
    """Cria o monitor na API se a subentry ainda não tem um."""
    if subentry.data.get(CONF_MONITOR_ID):
        return
    url = _url_webhook(hass, webhook_id)
    # Mesma tradução de erros dos coordinators: sem isto o HA parkeia a entry
    # em SETUP_ERROR (não-retentável) em vez de SETUP_RETRY/reauth.
    try:
        if subentry.subentry_type == SUBENTRY_MUNICIPIO:
            dados = await client.async_criar_monitor_cidade(
                url, [str(subentry.data[CONF_IBGE])], descricao=subentry.title
            )
        else:
            dados = await client.async_criar_monitor_ios(
                url,
                subentry.data[CONF_PAISES],
                operadoras=subentry.data.get(CONF_OPERADORAS) or None,
                incluir_beta=subentry.data.get(CONF_INCLUIR_BETA, False),
            )
    except RMFAuthError as err:
        raise ConfigEntryAuthFailed(err) from err
    except RMFError as err:
        raise ConfigEntryNotReady(f"Falha ao criar monitor: {err}") from err
    # O secret só volta nessa resposta — precisa ser persistido agora.
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data={
            **subentry.data,
            CONF_MONITOR_ID: dados["id"],
            CONF_MONITOR_SECRET: dados["secret"],
        },
    )


def _checar_monitores(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Cria/fecha issues conforme o estado dos monitores.

    Roda no setup e a cada refresh do MonitoresCoordinator (listener abaixo),
    então uma issue criada quando o monitor cai é fechada sozinha assim que
    ele volta a aparecer `ativo` na listagem.
    """
    rt: RMFRuntime = entry.runtime_data
    dados = rt.monitores.data or {}
    for subentry in entry.subentries.values():
        monitor_id = subentry.data.get(CONF_MONITOR_ID)
        if not monitor_id:
            continue
        mon = dados.get(monitor_id)
        issue_id = f"monitor_inativo_{subentry.subentry_id}"
        if mon is None or not mon.get("ativo"):
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="monitor_inativo",
                translation_placeholders={"nome": subentry.title},
                data={"entry_id": entry.entry_id, "subentry_id": subentry.subentry_id},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


async def _remover_orfaos(
    hass: HomeAssistant, entry: ConfigEntry, client: RMFClient, url_webhook: str
) -> None:
    """Apaga monitores da API que apontam pro nosso webhook mas não têm subentry.

    Proteção: só mexe num monitor se as DUAS condições baterem — `url` é
    exatamente a URL do nosso webhook (outra instalação HA, ou outra entry
    com webhook_id diferente, nunca bate) E o id não está reivindicado por
    nenhuma subentry desta entry (`nossos`). Cobre a remoção de subentry, que
    não tem hook próprio no HA.
    """
    nossos = {
        s.data.get(CONF_MONITOR_ID)
        for s in entry.subentries.values()
        if s.data.get(CONF_MONITOR_ID)
    }
    for tipo in ("cidade", "ios"):
        try:
            lista = await client.async_listar_monitores(tipo)
        except RMFError:
            continue
        for mon in lista:
            if mon.get("url") == url_webhook and mon["id"] not in nossos:
                try:
                    await client.async_remover_monitor(tipo, mon["id"])
                    _LOGGER.info("Monitor órfão %s removido", mon["id"])
                except RMFError as err:
                    _LOGGER.warning("Falha ao remover órfão %s: %s", mon["id"], err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura a entry hub."""
    client = RMFClient(
        aiohttp_client.async_get_clientsession(hass), entry.data[CONF_TOKEN]
    )

    # Webhook: id estável guardado na entry
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if not webhook_id:
        webhook_id = secrets.token_hex(16)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_WEBHOOK_ID: webhook_id}
        )
    # A API RMF entrega da internet pública: local_only=False é obrigatório.
    webhook_async_register(
        hass,
        DOMAIN,
        "Redes Móveis Fixas",
        webhook_id,
        handle_webhook,
        local_only=False,
        allowed_methods=["POST"],
    )
    entry.async_on_unload(lambda: webhook_async_unregister(hass, webhook_id))

    health = HealthCoordinator(hass, entry, client, INTERVALO_HEALTH)
    monitores = MonitoresCoordinator(hass, entry, client, INTERVALO_MONITORES)
    await health.async_config_entry_first_refresh()
    await monitores.async_config_entry_first_refresh()

    rt = RMFRuntime(client=client, health=health, monitores=monitores)
    entry.runtime_data = rt

    for subentry in entry.subentries.values():
        sid = subentry.subentry_id
        if subentry.subentry_type == SUBENTRY_LOCAL:
            lat, lon = _coords_do_estado(hass, subentry.data[CONF_ENTITY_ID])
            rt.cobertura[sid] = CoberturaCoordinator(
                hass,
                entry,
                client,
                sid,
                lat,
                lon,
                timedelta(
                    minutes=subentry.data.get(
                        CONF_INTERVALO_COBERTURA, DEFAULT_INTERVALO_COBERTURA_MIN
                    )
                ),
            )
            rt.erbs[sid] = ErbsCoordinator(
                hass,
                entry,
                client,
                sid,
                lat,
                lon,
                timedelta(
                    hours=subentry.data.get(
                        CONF_INTERVALO_ERBS, DEFAULT_INTERVALO_ERBS_H
                    )
                ),
            )
            await rt.cobertura[sid].async_config_entry_first_refresh()
            await rt.erbs[sid].async_config_entry_first_refresh()
            if subentry.data[CONF_MODO] == "pessoa":
                _seguir_pessoa(hass, entry, subentry, rt)
        elif subentry.subentry_type == SUBENTRY_MUNICIPIO:
            rt.municipio[sid] = MunicipioCoordinator(
                hass,
                entry,
                client,
                sid,
                subentry.data[CONF_IBGE],
                timedelta(
                    hours=subentry.data.get(
                        CONF_INTERVALO_MUNICIPIO, DEFAULT_INTERVALO_MUNICIPIO_H
                    )
                ),
            )
            await rt.municipio[sid].async_config_entry_first_refresh()
            if subentry.data.get(CONF_MONITORAR):
                await _provisionar_monitor(hass, entry, subentry, client, webhook_id)
        elif subentry.subentry_type == SUBENTRY_MONITOR_IOS:
            await _provisionar_monitor(hass, entry, subentry, client, webhook_id)

    url_webhook = _url_webhook(hass, webhook_id)
    await _remover_orfaos(hass, entry, client, url_webhook)
    _checar_monitores(hass, entry)
    entry.async_on_unload(
        rt.monitores.async_add_listener(lambda: _checar_monitores(hass, entry))
    )

    async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Registrado só no fim: as gravações de monitor_id acima não podem
    # disparar um reload no meio do próprio setup.
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


@callback
def _seguir_pessoa(
    hass: HomeAssistant, entry: ConfigEntry, subentry: ConfigSubentry, rt: RMFRuntime
) -> None:
    """Atualiza coords quando a pessoa se move (>500 m e >=10 min)."""
    sid = subentry.subentry_id
    ultima: dict[str, datetime | None] = {"em": None}

    async def _mudou(event: Event) -> None:
        novo = event.data.get("new_state")
        if novo is None:
            return
        lat = novo.attributes.get("latitude")
        lon = novo.attributes.get("longitude")
        if lat is None or lon is None:
            return
        coord = rt.cobertura[sid]
        agora = dt_util.utcnow()
        if ultima["em"] and agora - ultima["em"] < INTERVALO_MINIMO_PESSOA:
            return
        if coord.lat is not None:
            dist = distance(coord.lat, coord.lon, float(lat), float(lon))
            if dist is not None and dist <= DISTANCIA_MINIMA_M:
                return
        ultima["em"] = agora
        for c in (rt.cobertura[sid], rt.erbs[sid]):
            c.lat, c.lon = float(lat), float(lon)
            await c.async_request_refresh()

    entry.async_on_unload(
        async_track_state_change_event(hass, [subentry.data[CONF_ENTITY_ID]], _mudou)
    )


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarrega as platforms (webhook/listeners saem via async_on_unload)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Entry removida: apaga os monitores na API (melhor esforço)."""
    client = RMFClient(
        aiohttp_client.async_get_clientsession(hass), entry.data[CONF_TOKEN]
    )
    for subentry in entry.subentries.values():
        monitor_id = subentry.data.get(CONF_MONITOR_ID)
        if not monitor_id:
            continue
        tipo = "cidade" if subentry.subentry_type == SUBENTRY_MUNICIPIO else "ios"
        try:
            await client.async_remover_monitor(tipo, monitor_id)
        except RMFError as err:
            _LOGGER.warning("Falha ao remover monitor %s: %s", monitor_id, err)
