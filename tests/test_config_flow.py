"""Testes do config flow (entry + reauth)."""

from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import aioresponses
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFAuthError, RMFError
from custom_components.redes_moveis_fixas.config_flow import _uid, _validar_token
from custom_components.redes_moveis_fixas.const import BASE_URL, DOMAIN


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


async def test_reauth_atualiza_unique_id(hass):
    """Reauth troca o token E o unique_id, senão um `user` flow com o token
    novo não bate com nenhuma entry e cria uma segunda entry duplicada."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"token": "tok_velho"}, unique_id=_uid("tok_velho")
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "tok_novo"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["token"] == "tok_novo"
    assert entry.unique_id == _uid("tok_novo")

    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(return_value=None),
    ):
        r2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        r2 = await hass.config_entries.flow.async_configure(
            r2["flow_id"], {"token": "tok_novo"}
        )
    assert r2["type"] is FlowResultType.ABORT
    assert r2["reason"] == "already_configured"


async def test_validar_token_real_propaga_403(hass):
    """`_validar_token` sem mock: garante que ele bate em GET /api/monitorar-ios
    e propaga RMFAuthError num 403 real (nenhum teste acima exercita o corpo)."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/api/monitorar-ios", status=403, body="forbidden")
        with pytest.raises(RMFAuthError):
            await _validar_token(hass, "tok_ruim")


async def test_reauth_token_novo_limpa_monitores(hass):
    """Token novo não enxerga monitores do antigo: o reauth limpa monitor_id/secret
    pra o reload provisionar de novo; subentries sem monitor ficam intactas."""
    from homeassistant.config_entries import ConfigSubentryData

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok_velho"},
        unique_id=_uid("tok_velho"),
        subentries_data=[
            ConfigSubentryData(
                data={"codigo_ibge": 2403251, "monitorar": True,
                      "monitor_id": "m1", "monitor_secret": "s1"},
                subentry_type="municipio", title="Parnamirim", unique_id="2403251",
            ),
            ConfigSubentryData(
                data={"modo": "zona", "entity_id": "zone.home"},
                subentry_type="local", title="Casa", unique_id="zone.home",
            ),
        ],
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with (
        patch(
            "custom_components.redes_moveis_fixas.config_flow._validar_token",
            AsyncMock(return_value=None),
        ),
        patch("homeassistant.config_entries.ConfigEntries.async_schedule_reload"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "tok_novo"}
        )
    assert result["reason"] == "reauth_successful"
    subs = {s.title: s.data for s in entry.subentries.values()}
    assert "monitor_id" not in subs["Parnamirim"] and "monitor_secret" not in subs["Parnamirim"]
    assert subs["Parnamirim"]["codigo_ibge"] == 2403251
    assert subs["Casa"] == {"modo": "zona", "entity_id": "zone.home"}
