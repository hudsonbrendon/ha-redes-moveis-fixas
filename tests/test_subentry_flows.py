"""Testes dos subentry flows."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFError, RMFNotFoundError
from custom_components.redes_moveis_fixas.const import DOMAIN

from .conftest import load_fixture


@pytest.fixture
async def entry(hass):
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok"},
        unique_id="uid1",
        state=config_entries.ConfigEntryState.LOADED,
    )
    e.add_to_hass(hass)
    return e


async def test_subentry_local_zona(hass, entry):
    hass.states.async_set(
        "zone.home",
        "0",
        {"latitude": -5.8, "longitude": -35.2, "friendly_name": "Casa"},
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "local"), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"modo": "zona"}
    )
    assert result["step_id"] == "alvo"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "entity_id": "zone.home",
            "intervalo_cobertura": 30,
            "intervalo_erbs": 6,
            "max_geo": 25,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = list(entry.subentries.values())[0]
    assert sub.subentry_type == "local"
    assert sub.data["modo"] == "zona"
    assert sub.data["entity_id"] == "zone.home"
    assert sub.data["intervalo_cobertura"] == 30
    assert isinstance(sub.data["intervalo_cobertura"], int)
    assert sub.data["intervalo_erbs"] == 6
    assert isinstance(sub.data["intervalo_erbs"], int)
    assert sub.data["max_geo"] == 25
    assert isinstance(sub.data["max_geo"], int)


async def test_subentry_municipio_valida_ibge(hass, entry):
    with patch(
        "custom_components.redes_moveis_fixas.config_flow.RMFClient"
    ) as client_cls:
        client_cls.return_value.async_resumo_municipio = AsyncMock(
            return_value=load_fixture("resumo_municipio.json")["dados"]
        )
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "municipio"),
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"codigo_ibge": "3550308", "monitorar": True, "intervalo_municipio": 12},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = list(entry.subentries.values())[0]
    assert sub.title == "São Paulo (SP)"
    assert sub.data["codigo_ibge"] == 3550308
    assert isinstance(sub.data["codigo_ibge"], int)
    assert sub.data["intervalo_municipio"] == 12
    assert isinstance(sub.data["intervalo_municipio"], int)


async def test_subentry_municipio_ibge_invalido(hass, entry):
    with patch(
        "custom_components.redes_moveis_fixas.config_flow.RMFClient"
    ) as client_cls:
        client_cls.return_value.async_resumo_municipio = AsyncMock(
            side_effect=RMFNotFoundError("404")
        )
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "municipio"),
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"codigo_ibge": "9999999", "monitorar": False, "intervalo_municipio": 12},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "ibge_invalido"}


async def test_subentry_municipio_ibge_nao_numerico(hass, entry):
    with patch(
        "custom_components.redes_moveis_fixas.config_flow.RMFClient"
    ) as client_cls:
        client_cls.return_value.async_resumo_municipio = AsyncMock()
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "municipio"),
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"codigo_ibge": "abc", "monitorar": False, "intervalo_municipio": 12},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "ibge_invalido"}


async def test_subentry_municipio_erro_generico(hass, entry):
    with patch(
        "custom_components.redes_moveis_fixas.config_flow.RMFClient"
    ) as client_cls:
        client_cls.return_value.async_resumo_municipio = AsyncMock(
            side_effect=RMFError("500")
        )
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "municipio"),
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"codigo_ibge": "3550308", "monitorar": False, "intervalo_municipio": 12},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_subentry_monitor_ios(hass, entry):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "monitor_ios"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"paises": "br, pt", "operadoras": "vivo, tim", "incluir_beta": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = list(entry.subentries.values())[0]
    assert sub.data["paises"] == ["BR", "PT"]
    assert sub.data["operadoras"] == ["vivo", "tim"]
    assert sub.data["incluir_beta"] is False


async def test_subentry_monitor_ios_incluir_beta_true(hass, entry):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "monitor_ios"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"paises": "br", "operadoras": "vivo", "incluir_beta": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = list(entry.subentries.values())[0]
    assert sub.data["incluir_beta"] is True
