"""Testes de setup/unload da entry."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.const import DOMAIN

from .conftest import load_fixture


def _mock_client():
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
def entry(hass):
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


async def test_setup_e_unload(hass, entry):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    client = _mock_client()
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    rt = entry.runtime_data
    assert len(rt.cobertura) == 1
    assert len(rt.erbs) == 1
    assert len(rt.municipio) == 1
    # coordenadas da zona chegaram no coordinator
    coord = list(rt.cobertura.values())[0]
    assert coord.lat == -5.8
    assert coord.lon == -35.2

    # monitores provisionados: secret gravado na subentry
    subs = {s.subentry_type: s for s in entry.subentries.values()}
    assert subs["monitor_ios"].data["monitor_secret"] == "whsec_test_1d90aa"
    assert subs["monitor_ios"].data["monitor_id"] == "3ab7f001"
    assert subs["municipio"].data["monitor_id"] == "9f1c0001"
    assert subs["municipio"].data["monitor_secret"] == "whsec_cidade_aa"
    client.async_criar_monitor_ios.assert_awaited_once()
    client.async_criar_monitor_cidade.assert_awaited_once()

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_nao_recria_monitor_existente(hass):
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid2",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "paises": ["BR"],
                    "operadoras": [],
                    "incluir_beta": False,
                    "monitor_id": "3ab7f001",
                    "monitor_secret": "whsec_ja_tem",
                },
                subentry_type="monitor_ios",
                title="Monitor iOS",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    client = _mock_client()
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    client.async_criar_monitor_ios.assert_not_awaited()


async def test_webhook_registrado_e_publico(hass, entry):
    """O webhook precisa aceitar POST vindo da internet (local_only=False)."""
    client = _mock_client()
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_register"
        ) as registrar,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    kwargs = registrar.call_args.kwargs
    assert kwargs["local_only"] is False
    assert list(kwargs["allowed_methods"]) == ["POST"]


async def test_modo_pessoa_segue_deslocamento(hass, freezer):
    """Só refaz a consulta se andou >500 m; movimento curto é ignorado."""
    from custom_components.redes_moveis_fixas.const import SUBENTRY_LOCAL

    hass.states.async_set(
        "person.hudson", "home", {"latitude": -5.8, "longitude": -35.2}
    )
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid3",
        subentries_data=[
            ConfigSubentryData(
                data={
                    "modo": "pessoa",
                    "entity_id": "person.hudson",
                    "intervalo_cobertura": 30,
                    "intervalo_erbs": 6,
                    "max_geo": 25,
                },
                subentry_type=SUBENTRY_LOCAL,
                title="Hudson",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    client = _mock_client()
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()

    sid = next(iter(e.runtime_data.cobertura))
    coord = e.runtime_data.cobertura[sid]
    erbs = e.runtime_data.erbs[sid]

    # ~20 m: abaixo do mínimo, não atualiza
    hass.states.async_set(
        "person.hudson", "home", {"latitude": -5.8002, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert coord.lat == -5.8

    # ~2 km: passa do mínimo
    hass.states.async_set(
        "person.hudson", "not_home", {"latitude": -5.82, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert (coord.lat, coord.lon) == (-5.82, -35.2)
    assert (erbs.lat, erbs.lon) == (-5.82, -35.2)

    # outro salto longo dentro dos 10 min: barrado pelo intervalo mínimo
    freezer.tick(timedelta(minutes=2))
    hass.states.async_set(
        "person.hudson", "not_home", {"latitude": -5.90, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert coord.lat == -5.82

    # passados os 10 min, volta a seguir
    freezer.tick(timedelta(minutes=11))
    hass.states.async_set(
        "person.hudson", "not_home", {"latitude": -5.95, "longitude": -35.2}
    )
    await hass.async_block_till_done()
    assert coord.lat == -5.95
