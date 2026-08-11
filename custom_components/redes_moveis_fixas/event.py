"""Event entities da integração RMF."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SIGNAL_NOVIDADE, SUBENTRY_MONITOR_IOS, SUBENTRY_MUNICIPIO
from .entity import RMFEntity


def _como_dict(valor: Any) -> dict:
    """Normaliza um valor remoto (payload de webhook) que deveria ser um dict."""
    return valor if isinstance(valor, dict) else {}


def _como_lista(valor: Any) -> list:
    """Normaliza um valor remoto que deveria ser uma lista."""
    return valor if isinstance(valor, list) else []


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    rt = entry.runtime_data
    for subentry in entry.subentries.values():
        sid = subentry.subentry_id
        if subentry.subentry_type == SUBENTRY_MUNICIPIO:
            async_add_entities(
                [NovasTorresEvent(rt.municipio[sid], subentry)],
                config_subentry_id=sid,
            )
        elif subentry.subentry_type == SUBENTRY_MONITOR_IOS:
            async_add_entities(
                [NovidadesIosEvent(rt.monitores, subentry)], config_subentry_id=sid
            )


class RMFEventBase(RMFEntity, EventEntity):
    """Escuta o dispatcher do subentry e dispara eventos."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_NOVIDADE.format(self._subentry.subentry_id),
                self._recebido,
            )
        )

    @callback
    def _recebido(self, payload: Any) -> None:
        raise NotImplementedError


class NovasTorresEvent(RMFEventBase):
    """Uma nova ERB ou upgrade de tecnologia no município monitorado."""

    _attr_event_types = ["nova_erb", "upgrade_tecnologia"]

    def __init__(self, coordinator, subentry: ConfigSubentry) -> None:
        super().__init__(
            coordinator,
            subentry,
            "novas_torres",
            f"Novas torres em {subentry.title}",
        )

    @callback
    def _recebido(self, payload: Any) -> None:
        payload = _como_dict(payload)
        erbs = [e for e in _como_lista(payload.get("erbs")) if isinstance(e, dict)]
        if not erbs:
            return
        for erb in erbs:
            tipo = "nova_erb" if erb.get("nova") else "upgrade_tecnologia"
            self._trigger_event(
                tipo,
                {
                    "operadora": erb.get("operadora"),
                    "id": erb.get("id"),
                    "tecnologias": erb.get("tecnologias"),
                    "tecnologias_novas": erb.get("tecnologias_novas"),
                    "coordenadas": erb.get("coordenadas"),
                    "municipio": payload.get("municipio"),
                },
            )
            # um write por item: _trigger_event só atualiza atributos em
            # memória, quem publica o state_changed é o write. Um write só
            # no final do loop faria os itens 1..N-1 de uma entrega com
            # várias novidades nunca aparecerem no state machine.
            self.async_write_ha_state()


class NovidadesIosEvent(RMFEventBase):
    """Bundle de operadora Apple novo, alterado ou removido."""

    _attr_event_types = ["nova", "alterada", "removida"]

    def __init__(self, coordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator, subentry, "novidades_ios", "Novidades do iOS")

    @callback
    def _recebido(self, payload: Any) -> None:
        payload = _como_dict(payload)
        novidades = [
            n for n in _como_lista(payload.get("novidades")) if isinstance(n, dict)
        ]
        if not novidades:
            return
        for nov in novidades:
            operadora = _como_dict(nov.get("operadora"))
            tipo = nov.get("tipo")
            # tipo ausente/None/valor desconhecido do remoto: _trigger_event
            # exige que esteja em _attr_event_types, senão levanta ValueError.
            if tipo not in self._attr_event_types:
                tipo = "alterada"
            self._trigger_event(
                tipo,
                {
                    "operadora": operadora.get("nome"),
                    "pais": operadora.get("pais_iso"),
                    "bundle": nov.get("bundle"),
                    "recursos_adicionados": nov.get("recursos_adicionados"),
                    "recursos_removidos": nov.get("recursos_removidos"),
                    "rotulos_adicionados": nov.get("rotulos_adicionados"),
                    "rotulos_removidos": nov.get("rotulos_removidos"),
                    "beta": nov.get("beta"),
                    "ocorrido_em": nov.get("ocorrido_em"),
                },
            )
            self.async_write_ha_state()
