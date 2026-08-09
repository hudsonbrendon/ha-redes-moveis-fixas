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
    ErbsCoordinator,
    HealthCoordinator,
    MonitoresCoordinator,
    MunicipioCoordinator,
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


async def test_erbs_ok(hass, entry):
    client = AsyncMock()
    client.async_estacoes.return_value = load_fixture("estacoes.json")["dados"]
    coord = ErbsCoordinator(
        hass, entry, client, "sub1", -23.56, -46.65, timedelta(minutes=30)
    )
    dados = await coord._async_update_data()
    assert dados["erbs"][0]["operadora"] == "Claro"
    client.async_estacoes.assert_awaited_once_with(-23.56, -46.65)


async def test_erbs_sem_coords(hass, entry):
    client = AsyncMock()
    coord = ErbsCoordinator(
        hass, entry, client, "sub1", None, None, timedelta(minutes=30)
    )
    assert await coord._async_update_data() == {}
    client.async_estacoes.assert_not_awaited()


async def test_municipio_ok(hass, entry):
    client = AsyncMock()
    client.async_resumo_municipio.return_value = load_fixture("resumo_municipio.json")[
        "dados"
    ]
    coord = MunicipioCoordinator(hass, entry, client, "sub1", 3550308, timedelta(hours=6))
    dados = await coord._async_update_data()
    assert dados["municipio"]["nome"] == "São Paulo"
    client.async_resumo_municipio.assert_awaited_once_with(3550308)


async def test_health_ok(hass, entry):
    client = AsyncMock()
    client.async_health.return_value = load_fixture("health.json")
    coord = HealthCoordinator(hass, entry, client, timedelta(minutes=5))
    dados = await coord._async_update_data()
    assert dados == load_fixture("health.json")
    client.async_health.assert_awaited_once_with()


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
