"""Testes do config flow (entry + reauth)."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFAuthError, RMFError
from custom_components.redes_moveis_fixas.const import DOMAIN


async def test_flow_cria_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "tok_abc"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Redes Móveis Fixas"
    assert result["data"] == {"token": "tok_abc"}


async def test_flow_token_invalido(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(side_effect=RMFAuthError("403")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "ruim"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_flow_sem_conexao(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(side_effect=RMFError("boom")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "tok"}
        )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_token_duplicado_aborta(hass):
    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(return_value=None),
    ):
        r1 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        r1 = await hass.config_entries.flow.async_configure(
            r1["flow_id"], {"token": "tok_igual"}
        )
        assert r1["type"] is FlowResultType.CREATE_ENTRY

        r2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        r2 = await hass.config_entries.flow.async_configure(
            r2["flow_id"], {"token": "tok_igual"}
        )
    assert r2["type"] is FlowResultType.ABORT
    assert r2["reason"] == "already_configured"


async def test_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"token": "velho"}, unique_id="uid1")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "novo"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["token"] == "novo"
