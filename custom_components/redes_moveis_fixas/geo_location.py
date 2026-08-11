"""ERBs próximas como entidades geo_location (aparecem no mapa)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MAX_GEO, DEFAULT_MAX_GEO, DOMAIN, SUBENTRY_LOCAL
from .coordinator import ErbsCoordinator
from .entity import RMFEntity

_LOGGER = logging.getLogger(__name__)

SOURCE = DOMAIN

# Teto de voltas do loop de espera em _remover: o add roda numa task própria
# agendada por async_add_entities, então uma volta ou duas já bastam pro caso
# comum. Um teto pequeno evita girar pra sempre no caso abortado (ver
# _remover) sem impor atraso perceptível no caso normal.
_MAX_ESPERA_ADD = 10


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    rt = entry.runtime_data
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_LOCAL:
            continue
        max_geo = int(subentry.data.get(CONF_MAX_GEO, DEFAULT_MAX_GEO))
        if max_geo == 0:
            continue
        gerente = _GerenteErbs(
            rt.erbs[subentry.subentry_id], subentry, async_add_entities, max_geo
        )
        # Sem isto o listener no coordinator sobrevive ao unload da entry:
        # o coordinator some (nova instância no próximo setup), mas nada
        # jamais chama o unsub retornado por async_add_listener.
        entry.async_on_unload(gerente.unsub)


def _erbs_validas(data: dict | None) -> list[dict]:
    """ERBs com id e coordenadas utilizáveis — sem isso não dá pra por no mapa."""
    validas = []
    for erb in (data or {}).get("erbs", []):
        if not isinstance(erb, dict) or not erb.get("id"):
            continue
        coords = erb.get("coordenadas")
        if not isinstance(coords, dict):
            continue
        lat, lon = coords.get("lat"), coords.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        validas.append(erb)
    return validas


def _distancia(erb: dict) -> float:
    """Distância pra ordenação; sem valor numérico vai pro fim (não quebra)."""
    dist = erb.get("distancia_km")
    return dist if isinstance(dist, (int, float)) else float("inf")


class _GerenteErbs:
    """Mantém as entities em sincronia com o top-N do coordinator."""

    def __init__(
        self,
        coordinator: ErbsCoordinator,
        subentry: ConfigSubentry,
        async_add_entities: AddEntitiesCallback,
        max_geo: int,
    ) -> None:
        self._coordinator = coordinator
        self._subentry = subentry
        self._add = async_add_entities
        self._max = max_geo
        self._entities: dict[str, ErbGeolocationEvent] = {}
        self.unsub = coordinator.async_add_listener(self._sincronizar)
        self._sincronizar()

    @callback
    def _sincronizar(self) -> None:
        # Um add pode ser abortado pelo entity_platform (entity_id/unique_id
        # duplicado, registry entry desabilitada...) — nesse caso `hass` fica
        # None PRA SEMPRE (add_to_platform_abort não é reversível). Se a ERB
        # nunca sai do top-N, ela ficaria "tracked" como viva indefinidamente
        # e nunca mais tentaríamos recriar a entity. Uma ERB recém-criada
        # neste mesmo ciclo também tem hass None (a task de add ainda não
        # rodou), mas essa só entra em self._entities DEPOIS deste purge —
        # então aqui só sobra quem já teve ciclos anteriores (com awaits de
        # verdade entre eles) pra terminar de adicionar ou abortar.
        for erb_id, ent in list(self._entities.items()):
            if ent.hass is None:
                del self._entities[erb_id]

        erbs = sorted(_erbs_validas(self._coordinator.data), key=_distancia)[
            : self._max
        ]
        atuais = {erb["id"]: erb for erb in erbs}

        novos = [
            ErbGeolocationEvent(self._coordinator, self._subentry, erb)
            for erb_id, erb in atuais.items()
            if erb_id not in self._entities
        ]
        for ent in novos:
            self._entities[ent.erb_id] = ent
        if novos:
            self._add(novos, config_subentry_id=self._subentry.subentry_id)

        for erb_id in list(self._entities):
            if erb_id not in atuais:
                ent = self._entities.pop(erb_id)
                self._coordinator.hass.async_create_task(_remover(ent))


async def _remover(ent: ErbGeolocationEvent) -> None:
    """Remove a entity com segurança, sem nunca girar pra sempre.

    async_add_entities agenda a adição via task própria — se uma ERB sai do
    top-N antes dessa task rodar, `ent.hass` ainda é None e `async_remove()`
    levantaria AttributeError (`self.hass.loop...`). Mas se o add foi
    ABORTADO (entity_id duplicado, registry entry desabilitada — ver
    EntityPlatform._async_add_entity), `hass` fica None pra sempre: sem um
    teto aqui, esperar "até ficar pronto" giraria pelo resto do processo.
    Cede um número limitado de voltas do loop; se `hass` nunca aparecer, o
    add foi abortado e a entity nunca chegou a escrever estado — não há
    nada pra remover, só desiste em silêncio (loga em debug).
    """
    for _ in range(_MAX_ESPERA_ADD):
        if ent.hass is not None:
            # force_remove=True: sem isto, como RMFEntity dá unique_id a toda
            # entity, o entity_registry tem uma entry pra cada ERB e
            # Entity._async_remove_impl pega o ramo "mantém a registry row,
            # escreve estado unavailable" em vez de remover de verdade — o
            # padrão do geo_location.demo do próprio HA core é justamente
            # forçar aqui. Estas são entities transitórias/discovery: sem
            # force_remove, um local em modo pessoa deixaria uma torre morta
            # (marcador unavailable no mapa) atrás de si a cada troca de top-N.
            #
            # force_remove só tira o ESTADO — a linha do entity_registry
            # sobrevive (é assim que o registry funciona: unique_id existiu
            # uma vez, fica registrado pra sempre até alguém apagar). Sem a
            # remoção explícita abaixo, a troca de top-N acumularia uma
            # entry morta no registry por ERB já vista, pra sempre.
            hass, entity_id = ent.hass, ent.entity_id
            await ent.async_remove(force_remove=True)
            registry = er.async_get(hass)
            if registry.async_get(entity_id) is not None:
                registry.async_remove(entity_id)
            return
        await asyncio.sleep(0)
    _LOGGER.debug(
        "ERB %s: add nunca terminou (provavelmente abortado), nada a remover",
        ent.erb_id,
    )


class ErbGeolocationEvent(RMFEntity, GeolocationEvent):
    _attr_source = SOURCE
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:radio-tower"

    def __init__(
        self, coordinator: ErbsCoordinator, subentry: ConfigSubentry, erb: dict
    ) -> None:
        self.erb_id: str = erb["id"]
        operadora = erb.get("operadora") or "?"
        super().__init__(
            coordinator,
            subentry,
            f"erb_{self.erb_id}",
            f"ERB {operadora} {self.erb_id}",
        )
        self._erb = erb

    def _atual(self) -> dict:
        for erb in (self.coordinator.data or {}).get("erbs", []):
            if isinstance(erb, dict) and erb.get("id") == self.erb_id:
                return erb
        return self._erb

    @property
    def distance(self) -> float | None:
        dist = self._atual().get("distancia_km")
        return dist if isinstance(dist, (int, float)) else None

    @property
    def latitude(self) -> float | None:
        coords = self._atual().get("coordenadas")
        lat = coords.get("lat") if isinstance(coords, dict) else None
        return lat if isinstance(lat, (int, float)) else None

    @property
    def longitude(self) -> float | None:
        coords = self._atual().get("coordenadas")
        lon = coords.get("lon") if isinstance(coords, dict) else None
        return lon if isinstance(lon, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        erb = self._atual()
        return {
            "operadora": erb.get("operadora"),
            "tecnologias": erb.get("tecnologias"),
            "bandas": erb.get("bandas"),
            "endereco": erb.get("endereco"),
        }
