"""Testes dos coordinators."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFAuthError, RMFError
from custom_components.redes_moveis_fixas.const import DOMAIN
from custom_components.redes_moveis_fixas.coordinator import (
    CoberturaCoordinator,
    MonitoresCoordinator,
)

from .conftest import load_fixture


@pytest.fixture
def entry(hass):
    e = MockConfigEntry(domain=DOMAIN, data={"token": "tok"})
    e.add_to_hass(hass)
    return e


async def test_cobertura_ok(hass, entry):
    client = AsyncMock()
    client.async_cobertura.return_value = load_fixture("cobertura.json")["dados"]
    coord = CoberturaCoordinator(
        hass, entry, client, "sub1", -23.56, -46.65, timedelta(minutes=30)
    )
    dados = await coord._async_update_data()
    assert dados["cobertura"][0]["provedor"] == "Vivo"
    client.async_cobertura.assert_awaited_once_with(-23.56, -46.65)


async def test_cobertura_sem_coords(hass, entry):
    client = AsyncMock()
    coord = CoberturaCoordinator(
        hass, entry, client, "sub1", None, None, timedelta(minutes=30)
    )
    assert await coord._async_update_data() == {}
    client.async_cobertura.assert_not_awaited()


async def test_auth_falhou(hass, entry):
    client = AsyncMock()
    client.async_cobertura.side_effect = RMFAuthError("403")
    coord = CoberturaCoordinator(
        hass, entry, client, "sub1", 0.0, 0.0, timedelta(minutes=30)
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


async def test_erro_generico_vira_update_failed(hass, entry):
    client = AsyncMock()
    client.async_cobertura.side_effect = RMFError("boom")
    coord = CoberturaCoordinator(
        hass, entry, client, "sub1", 0.0, 0.0, timedelta(minutes=30)
    )
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_monitores_agrega_tipos(hass, entry):
    client = AsyncMock()
    client.async_listar_monitores.side_effect = [
        [],  # cidade
        load_fixture("monitores_ios_lista.json")["dados"],  # ios
    ]
    coord = MonitoresCoordinator(hass, entry, client, timedelta(hours=6))
    dados = await coord._async_update_data()
    assert dados["3ab7f001"]["tipo"] == "ios"
    assert dados["3ab7f001"]["ativo"] is True
