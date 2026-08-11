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

SCHEMA_COBERTURA = vol.Schema(
    {
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
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

SCHEMA_RESUMO = vol.Schema({vol.Required("codigo_ibge"): vol.Coerce(int)})


def _client(hass: HomeAssistant) -> RMFClient:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data.client
    raise HomeAssistantError("Nenhuma entry da RMF carregada")


def _coords(hass: HomeAssistant, call: ServiceCall) -> tuple[float, float]:
    if "entity_id" in call.data:
        state = hass.states.get(call.data["entity_id"])
        if state is None or state.attributes.get("latitude") is None:
            raise HomeAssistantError(f"{call.data.get('entity_id')} sem coordenadas")
        return state.attributes["latitude"], state.attributes["longitude"]
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
