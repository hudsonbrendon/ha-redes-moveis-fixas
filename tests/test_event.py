"""Testes das event entities."""

import logging

from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.redes_moveis_fixas.const import SIGNAL_NOVIDADE

from .conftest import load_fixture
from .test_sensor import _setup


def _sub(entry, tipo: str):
    return next(s for s in entry.subentries.values() if s.subentry_type == tipo)


async def test_event_ios(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_ios = _sub(entry_completa, "monitor_ios")
    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_ios.subentry_id),
        load_fixture("webhook_ios.json"),
    )
    await hass.async_block_till_done()

    estado = hass.states.get("event.monitor_ios_novidades")
    assert estado.attributes["event_type"] == "alterada"
    assert estado.attributes["operadora"] == "TIM"
    assert estado.attributes["pais"] == "BR"
    assert estado.attributes["bundle"] == {"from": "70.0", "to": "70.1"}
    assert estado.attributes["icon"] == "mdi:apple"


async def test_event_cidade(hass, entry_completa, mock_client):
    """Uma entrega com 2 ERBs de tipos diferentes dispara os DOIS eventos —
    um state_changed por item, não só o último (async_write_ha_state está
    dentro do loop, não depois dele)."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_mun = _sub(entry_completa, "municipio")
    entity_id = "event.sao_paulo_sp_novas_torres"
    eventos = async_capture_events(hass, "state_changed")

    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_mun.subentry_id),
        load_fixture("webhook_cidade.json"),
    )
    await hass.async_block_till_done()

    mudancas = [e for e in eventos if e.data["entity_id"] == entity_id]
    assert len(mudancas) == 2
    tipos = [e.data["new_state"].attributes["event_type"] for e in mudancas]
    # webhook_cidade.json: 1ª ERB nova=true, 2ª nova=false
    assert tipos == ["nova_erb", "upgrade_tecnologia"]
    assert mudancas[0].data["new_state"].attributes["operadora"] == "Vivo"
    assert mudancas[1].data["new_state"].attributes["operadora"] == "TIM"

    # e o estado final publicado é o do último item
    estado = hass.states.get(entity_id)
    assert estado.attributes["event_type"] == "upgrade_tecnologia"
    assert estado.attributes["operadora"] == "TIM"
    assert estado.attributes["icon"] == "mdi:radio-tower"


async def test_event_cidade_nova_erb(hass, entry_completa, mock_client):
    """Entrega com uma única ERB nova=true dispara nova_erb."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_mun = _sub(entry_completa, "municipio")
    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_mun.subentry_id),
        {
            "evento": "novidades.cidade",
            "municipio": {"codigo_ibge": 3550308, "nome": "São Paulo", "uf": "SP"},
            "erbs": [
                {
                    "id": "999",
                    "operadora": "Claro",
                    "nova": True,
                    "tecnologias": ["LTE"],
                    "tecnologias_novas": ["LTE"],
                    "coordenadas": {"lat": -23.5, "lon": -46.6},
                }
            ],
        },
    )
    await hass.async_block_till_done()

    estado = hass.states.get("event.sao_paulo_sp_novas_torres")
    assert estado.attributes["event_type"] == "nova_erb"
    assert estado.attributes["operadora"] == "Claro"
    assert estado.attributes["id"] == "999"


async def test_event_ios_nova_e_removida(hass, entry_completa, mock_client):
    """Duas entregas separadas cobrem os tipos nova e removida."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_ios = _sub(entry_completa, "monitor_ios")

    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_ios.subentry_id),
        {
            "evento": "novidades.ios",
            "novidades": [
                {
                    "operadora": {"nome": "Vivo", "pais_iso": "BR"},
                    "tipo": "nova",
                    "bundle": {"from": None, "to": "1.0"},
                }
            ],
        },
    )
    await hass.async_block_till_done()
    estado = hass.states.get("event.monitor_ios_novidades")
    assert estado.attributes["event_type"] == "nova"
    assert estado.attributes["operadora"] == "Vivo"

    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_ios.subentry_id),
        {
            "evento": "novidades.ios",
            "novidades": [
                {
                    "operadora": {"nome": "Claro", "pais_iso": "BR"},
                    "tipo": "removida",
                    "bundle": None,
                }
            ],
        },
    )
    await hass.async_block_till_done()
    estado = hass.states.get("event.monitor_ios_novidades")
    assert estado.attributes["event_type"] == "removida"
    assert estado.attributes["operadora"] == "Claro"


async def test_event_payload_malformado_nao_explode(
    hass, entry_completa, mock_client, caplog
):
    """Campos ausentes/formato errado no payload remoto não podem gerar uma
    exceção. `async_dispatcher_send` engole exceções do callback e só loga em
    ERROR (homeassistant/helpers/dispatcher.py via util/logging.log_exception),
    então a checagem real é "nenhum ERROR logado" — um `assert` sozinho não
    veria o crash. Cada payload roda isolado (caplog limpo + estado checado
    logo depois) para que um crash seja atribuível ao caso que o causou."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_mun = _sub(entry_completa, "municipio")
    sub_ios = _sub(entry_completa, "monitor_ios")
    entidade_mun = "event.sao_paulo_sp_novas_torres"
    entidade_ios = "event.monitor_ios_novidades"

    casos_municipio = [
        {},
        {"erbs": "não é lista"},
        {"erbs": ["string_solta"]},
    ]
    for payload in casos_municipio:
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            async_dispatcher_send(
                hass, SIGNAL_NOVIDADE.format(sub_mun.subentry_id), payload
            )
            await hass.async_block_till_done()
        erros = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert not erros, f"payload {payload!r} (município) gerou erro: {erros}"
        assert hass.states.get(entidade_mun) is not None

    casos_ios = [
        {},
        {"novidades": [{"tipo": "tipo_desconhecido"}]},
        {"novidades": [{"operadora": None, "tipo": None}]},
    ]
    for payload in casos_ios:
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            async_dispatcher_send(
                hass, SIGNAL_NOVIDADE.format(sub_ios.subentry_id), payload
            )
            await hass.async_block_till_done()
        erros = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert not erros, f"payload {payload!r} (iOS) gerou erro: {erros}"
        assert hass.states.get(entidade_ios) is not None

    # tipo inválido/ausente/operadora None do último caso caem no default seguro
    estado_ios = hass.states.get(entidade_ios)
    assert estado_ios.attributes["event_type"] == "alterada"
    assert estado_ios.attributes["operadora"] is None


async def test_event_teardown_desconecta_dispatcher(hass, entry_completa, mock_client):
    """async_on_remove deve desligar a assinatura do dispatcher ao descarregar
    a entry — sem isso, um sinal enviado depois do unload ainda mudaria o
    estado (ou explodiria numa entidade já removida)."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_mun = _sub(entry_completa, "municipio")
    entity_id = "event.sao_paulo_sp_novas_torres"

    assert await hass.config_entries.async_unload(entry_completa.entry_id)
    await hass.async_block_till_done()
    estado_apos_unload = hass.states.get(entity_id)

    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_mun.subentry_id),
        {"erbs": [{"id": "1", "operadora": "Vivo", "nova": True}]},
    )
    await hass.async_block_till_done()

    assert hass.states.get(entity_id) is estado_apos_unload
