"""Coordinators da integração RMF."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import RMFAuthError, RMFClient, RMFError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class RMFCoordinator(DataUpdateCoordinator[dict]):
    """Base: traduz erros da API pra exceções do HA."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: RMFClient,
        name: str,
        interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{name}",
            update_interval=interval,
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        try:
            return await self._fetch()
        except RMFAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except RMFError as err:
            raise UpdateFailed(err) from err

    async def _fetch(self) -> dict:
        raise NotImplementedError


class CoberturaCoordinator(RMFCoordinator):
    """Cobertura por operadora num ponto (lat/lon mutável pra modo pessoa)."""

    def __init__(self, hass, entry, client, subentry_id, lat, lon, interval) -> None:
        super().__init__(hass, entry, client, f"cobertura_{subentry_id}", interval)
        self.lat: float | None = lat
        self.lon: float | None = lon

    async def _fetch(self) -> dict:
        if self.lat is None or self.lon is None:
            return {}
        return await self.client.async_cobertura(self.lat, self.lon)


class ErbsCoordinator(RMFCoordinator):
    """ERBs num raio de 5 km do ponto."""

    def __init__(self, hass, entry, client, subentry_id, lat, lon, interval) -> None:
        super().__init__(hass, entry, client, f"erbs_{subentry_id}", interval)
        self.lat: float | None = lat
        self.lon: float | None = lon

    async def _fetch(self) -> dict:
        if self.lat is None or self.lon is None:
            return {}
        return await self.client.async_estacoes(self.lat, self.lon)


class MunicipioCoordinator(RMFCoordinator):
    """Resumo de estações do município."""

    def __init__(self, hass, entry, client, subentry_id, ibge, interval) -> None:
        super().__init__(hass, entry, client, f"municipio_{subentry_id}", interval)
        self.ibge: int = ibge

    async def _fetch(self) -> dict:
        return await self.client.async_resumo_municipio(self.ibge)


class HealthCoordinator(RMFCoordinator):
    """Status do serviço."""

    def __init__(self, hass, entry, client, interval) -> None:
        super().__init__(hass, entry, client, "health", interval)

    async def _fetch(self) -> dict:
        return await self.client.async_health()


class MonitoresCoordinator(RMFCoordinator):
    """Lista os monitores registrados (cidade + ios), indexados por id."""

    def __init__(self, hass, entry, client, interval) -> None:
        super().__init__(hass, entry, client, "monitores", interval)

    async def _fetch(self) -> dict:
        monitores: dict[str, dict] = {}
        for tipo in ("cidade", "ios"):
            for mon in await self.client.async_listar_monitores(tipo):
                mon_id = mon.get("id")
                if mon_id is None:
                    continue
                monitores[mon_id] = {**mon, "tipo": tipo}
        return monitores
