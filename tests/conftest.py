"""Fixtures compartilhadas."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigSubentryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.const import DOMAIN

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    """Carrega fixture JSON (re-lê a cada chamada; pode mutar)."""
    return json.loads((FIXTURE_DIR / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Habilita custom integrations em todos os testes."""
    yield


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.async_health.return_value = load_fixture("health.json")
    client.async_listar_monitores.return_value = []
    client.async_cobertura.return_value = load_fixture("cobertura.json")["dados"]
    client.async_estacoes.return_value = load_fixture("estacoes.json")["dados"]
    client.async_resumo_municipio.return_value = load_fixture("resumo_municipio.json")[
        "dados"
    ]
    client.async_criar_monitor_ios.return_value = load_fixture(
        "monitor_ios_criado.json"
    )["dados"]
    client.async_criar_monitor_cidade.return_value = {
        "id": "9f1c0001",
        "secret": "whsec_cidade_aa",
    }
    return client


@pytest.fixture
def entry_completa(hass):
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid1",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "modo": "zona",
                    "entity_id": "zone.home",
                    "intervalo_cobertura": 30,
                    "intervalo_erbs": 6,
                    "max_geo": 25,
                },
                subentry_type="local",
                title="Casa",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={
                    "codigo_ibge": 3550308,
                    "monitorar": True,
                    "intervalo_municipio": 12,
                },
                subentry_type="municipio",
                title="São Paulo (SP)",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={"paises": ["BR"], "operadoras": [], "incluir_beta": False},
                subentry_type="monitor_ios",
                title="Monitor iOS",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    return e
