"""ERBs próximas como entidades geo_location (aparecem no mapa)."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MAX_GEO, DEFAULT_MAX_GEO, DOMAIN, SUBENTRY_LOCAL
from .coordinator import ErbsCoordinator
from .entity import RMFEntity

SOURCE = DOMAIN


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
    """Remove a entity com segurança.

    async_add_entities agenda a adição via task própria — se uma ERB sai do
    top-N antes dessa task rodar, `ent.hass` ainda é None e
    `async_remove()` levantaria AttributeError. Cede o loop até a adição
    terminar (ponytail: busy-wait; trocar por espera na task de adição se
    isso virar gargalo real).
    """
    while ent.hass is None:
        await asyncio.sleep(0)
    await ent.async_remove()


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
