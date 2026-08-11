"""Testes das actions."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFError
from custom_components.redes_moveis_fixas.const import DOMAIN

from .test_sensor import _setup


async def test_consultar_cobertura_por_coords(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    resposta = await hass.services.async_call(
        "redes_moveis_fixas",
        "consultar_cobertura",
        {"latitude": -5.8, "longitude": -35.2},
        blocking=True,
        return_response=True,
    )
    assert resposta["cobertura"][0]["provedor"] == "Vivo"


async def test_consultar_cobertura_por_entity(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    resposta = await hass.services.async_call(
        "redes_moveis_fixas",
        "consultar_cobertura",
        {"entity_id": "zone.home"},
        blocking=True,
        return_response=True,
    )
    assert resposta["cobertura"][0]["provedor"] == "Vivo"


async def test_buscar_estacoes(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    resposta = await hass.services.async_call(
        "redes_moveis_fixas",
        "buscar_estacoes",
        {"latitude": -5.8, "longitude": -35.2, "operadora": "claro", "limite": 10},
        blocking=True,
        return_response=True,
    )
    assert resposta["total_erbs"] == 418


async def test_buscar_estacoes_converte_filtros_csv_em_lista(
    hass, entry_completa, mock_client
):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    # o coordinator de ERBs já chamou async_estacoes no setup; isola a chamada
    # feita pela action.
    mock_client.async_estacoes.reset_mock()

    await hass.services.async_call(
        "redes_moveis_fixas",
        "buscar_estacoes",
        {
            "latitude": -5.8,
            "longitude": -35.2,
            "operadora": "claro, vivo",
            "tecnologia": "NR,LTE",
            "banda": "78",
            "limite": 10,
        },
        blocking=True,
        return_response=True,
    )
    mock_client.async_estacoes.assert_awaited_once_with(
        -5.8,
        -35.2,
        operadora=["claro", "vivo"],
        tecnologia=["NR", "LTE"],
        banda=["78"],
        limite=10,
    )


async def test_resumo_do_municipio(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    resposta = await hass.services.async_call(
        "redes_moveis_fixas",
        "resumo_do_municipio",
        {"codigo_ibge": 3550308},
        blocking=True,
        return_response=True,
    )
    assert resposta["municipio"]["nome"] == "São Paulo"


async def test_consultar_cobertura_entity_inexistente(
    hass, entry_completa, mock_client
):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "consultar_cobertura",
            {"entity_id": "zone.nao_existe"},
            blocking=True,
            return_response=True,
        )


async def test_consultar_cobertura_entity_sem_coordenadas(
    hass, entry_completa, mock_client
):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    hass.states.async_set("zone.sem_coords", "0", {})
    await _setup(hass, entry_completa, mock_client)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "consultar_cobertura",
            {"entity_id": "zone.sem_coords"},
            blocking=True,
            return_response=True,
        )


async def test_consultar_cobertura_entity_so_com_longitude(
    hass, entry_completa, mock_client
):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    hass.states.async_set("zone.so_lon", "0", {"longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "consultar_cobertura",
            {"entity_id": "zone.so_lon"},
            blocking=True,
            return_response=True,
        )


async def test_consultar_cobertura_entity_so_com_latitude(
    hass, entry_completa, mock_client
):
    """Regressão: latitude sem longitude não pode estourar KeyError cru."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    hass.states.async_set("zone.so_lat", "0", {"latitude": -5.8})
    await _setup(hass, entry_completa, mock_client)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "consultar_cobertura",
            {"entity_id": "zone.so_lat"},
            blocking=True,
            return_response=True,
        )


async def test_consultar_cobertura_entity_tem_precedencia_sobre_coords(
    hass, entry_completa, mock_client
):
    """Quando ambos são informados, entity_id vence (comportamento fixado)."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    hass.states.async_set(
        "zone.outra", "0", {"latitude": -23.5, "longitude": -46.6}
    )
    await _setup(hass, entry_completa, mock_client)

    await hass.services.async_call(
        "redes_moveis_fixas",
        "consultar_cobertura",
        {"entity_id": "zone.outra", "latitude": -5.8, "longitude": -35.2},
        blocking=True,
        return_response=True,
    )
    mock_client.async_cobertura.assert_awaited_with(-23.5, -46.6)


async def test_consultar_cobertura_sem_coords_nem_entity(
    hass, entry_completa, mock_client
):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "consultar_cobertura",
            {},
            blocking=True,
            return_response=True,
        )


async def test_rmferror_vira_homeassistanterror(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    mock_client.async_cobertura.side_effect = RMFError("falha na API")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "consultar_cobertura",
            {"latitude": -5.8, "longitude": -35.2},
            blocking=True,
            return_response=True,
        )


async def test_buscar_estacoes_rmferror_vira_homeassistanterror(
    hass, entry_completa, mock_client
):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    mock_client.async_estacoes.side_effect = RMFError("falha na API")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "buscar_estacoes",
            {"latitude": -5.8, "longitude": -35.2},
            blocking=True,
            return_response=True,
        )


async def test_resumo_do_municipio_rmferror_vira_homeassistanterror(
    hass, entry_completa, mock_client
):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    mock_client.async_resumo_municipio.side_effect = RMFError("falha na API")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "resumo_do_municipio",
            {"codigo_ibge": 3550308},
            blocking=True,
            return_response=True,
        )


async def test_buscar_estacoes_usa_limite_default_quando_omitido(
    hass, entry_completa, mock_client
):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    mock_client.async_estacoes.reset_mock()

    await hass.services.async_call(
        "redes_moveis_fixas",
        "buscar_estacoes",
        {"latitude": -5.8, "longitude": -35.2},
        blocking=True,
        return_response=True,
    )
    mock_client.async_estacoes.assert_awaited_once_with(
        -5.8, -35.2, operadora=None, tecnologia=None, banda=None, limite=200
    )


async def test_sem_entry_carregada_erra_limpo(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    # Serviços são globais: descarregar a entry não os desregistra.
    assert hass.services.has_service("redes_moveis_fixas", "consultar_cobertura")
    assert await hass.config_entries.async_unload(entry_completa.entry_id)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "redes_moveis_fixas",
            "consultar_cobertura",
            {"latitude": -5.8, "longitude": -35.2},
            blocking=True,
            return_response=True,
        )


async def test_registro_das_actions_e_idempotente(hass, entry_completa, mock_client):
    """Uma segunda entry carregada não pode falhar ao re-registrar as actions."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    segunda = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok2", "webhook_id": "wh_fixo2"},
        unique_id="uid_idempotencia",
        subentries_data=[
            ConfigSubentryData(
                data={"paises": ["BR"], "operadoras": [], "incluir_beta": False},
                subentry_type="monitor_ios",
                title="Monitor iOS 2",
                unique_id=None,
            ),
        ],
    )
    segunda.add_to_hass(hass)
    with (
        patch(
            "custom_components.redes_moveis_fixas.RMFClient", return_value=mock_client
        ),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo2",
        ),
    ):
        assert await hass.config_entries.async_setup(segunda.entry_id)
        await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "consultar_cobertura")
    assert hass.services.has_service(DOMAIN, "buscar_estacoes")
    assert hass.services.has_service(DOMAIN, "resumo_do_municipio")
