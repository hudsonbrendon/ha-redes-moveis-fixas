"""Actions da integração RMF."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import RMFClient, RMFError
from .const import DOMAIN

# Bounding box aproximado do Brasil, mesmo limite do services.yaml.
_LAT = vol.All(vol.Coerce(float), vol.Range(min=-35, max=6))
_LON = vol.All(vol.Coerce(float), vol.Range(min=-75, max=-28))

SCHEMA_COBERTURA = vol.Schema(
    {
        vol.Optional("latitude"): _LAT,
        vol.Optional("longitude"): _LON,
        vol.Optional("entity_id"): cv.entity_id,
    }
)

SCHEMA_ESTACOES = SCHEMA_COBERTURA.extend(
    {
        vol.Optional("operadora"): cv.string,
        vol.Optional("tecnologia"): cv.string,
        vol.Optional("banda"): cv.string,
        vol.Optional("limite", default=200): vol.All(int, vol.Range(min=1, max=1000)),
    }
)

SCHEMA_RESUMO = vol.Schema(
    {
        vol.Required("codigo_ibge"): vol.All(
            vol.Coerce(int), vol.Range(min=1100015, max=5300108)
        )
    }
)


def _client(hass: HomeAssistant) -> RMFClient:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data.client
    raise HomeAssistantError("Nenhuma entry da RMF carregada")


def _coords(hass: HomeAssistant, call: ServiceCall) -> tuple[float, float]:
    # entity_id tem precedência sobre latitude/longitude explícitas quando
    # ambos são informados (ver services.yaml).
    if "entity_id" in call.data:
        state = hass.states.get(call.data["entity_id"])
        lat = state.attributes.get("latitude") if state else None
        lon = state.attributes.get("longitude") if state else None
        if lat is None or lon is None:
            raise HomeAssistantError(f"{call.data.get('entity_id')} sem coordenadas")
        return lat, lon
    if "latitude" not in call.data or "longitude" not in call.data:
        raise HomeAssistantError("Informe latitude/longitude ou entity_id")
    return call.data["latitude"], call.data["longitude"]


def _csv(valor: str | None) -> list[str] | None:
    if not valor:
        return None
    return [v.strip() for v in valor.split(",") if v.strip()]


async def _consultar_cobertura(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    lat, lon = _coords(hass, call)
    try:
        return await _client(hass).async_cobertura(lat, lon)
    except RMFError as err:
        raise HomeAssistantError(str(err)) from err


async def _buscar_estacoes(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    lat, lon = _coords(hass, call)
    try:
        return await _client(hass).async_estacoes(
            lat,
            lon,
            operadora=_csv(call.data.get("operadora")),
            tecnologia=_csv(call.data.get("tecnologia")),
            banda=_csv(call.data.get("banda")),
            limite=call.data["limite"],
        )
    except RMFError as err:
        raise HomeAssistantError(str(err)) from err


async def _resumo_do_municipio(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    try:
        return await _client(hass).async_resumo_municipio(call.data["codigo_ibge"])
    except RMFError as err:
        raise HomeAssistantError(str(err)) from err


def async_setup_services(hass: HomeAssistant) -> None:
    """Registra as actions (idempotente)."""
    if hass.services.has_service(DOMAIN, "consultar_cobertura"):
        return
    hass.services.async_register(
        DOMAIN,
        "consultar_cobertura",
        _consultar_cobertura,
        schema=SCHEMA_COBERTURA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "buscar_estacoes",
        _buscar_estacoes,
        schema=SCHEMA_ESTACOES,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "resumo_do_municipio",
        _resumo_do_municipio,
        schema=SCHEMA_RESUMO,
        supports_response=SupportsResponse.ONLY,
    )
