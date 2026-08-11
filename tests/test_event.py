"""Testes das event entities."""

from homeassistant.helpers.dispatcher import async_dispatcher_send

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
        hass, SIGNAL_NOVIDADE.format(sub_ios.subentry_id), load_fixture("webhook_ios.json")
    )
    await hass.async_block_till_done()

    estado = hass.states.get("event.novidades_do_ios")
    assert estado.attributes["event_type"] == "alterada"
    assert estado.attributes["operadora"] == "TIM"
    assert estado.attributes["pais"] == "BR"
    assert estado.attributes["bundle"] == {"from": "70.0", "to": "70.1"}


async def test_event_cidade(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_mun = _sub(entry_completa, "municipio")
    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_mun.subentry_id),
        load_fixture("webhook_cidade.json"),
    )
    await hass.async_block_till_done()

    estado = hass.states.get("event.novas_torres_em_sao_paulo_sp")
    # última ERB do payload: nova=false → upgrade_tecnologia (limitação:
    # com múltiplos itens na mesma entrega, só o último fica visível no estado)
    assert estado.attributes["event_type"] == "upgrade_tecnologia"
    assert estado.attributes["operadora"] == "TIM"


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

    estado = hass.states.get("event.novas_torres_em_sao_paulo_sp")
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
    estado = hass.states.get("event.novidades_do_ios")
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
    estado = hass.states.get("event.novidades_do_ios")
    assert estado.attributes["event_type"] == "removida"
    assert estado.attributes["operadora"] == "Claro"


async def test_event_payload_malformado_nao_explode(hass, entry_completa, mock_client):
    """Campos ausentes/formato errado no payload remoto não devem derrubar a entidade."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_mun = _sub(entry_completa, "municipio")
    sub_ios = _sub(entry_completa, "monitor_ios")

    # município: payload sem "erbs", "erbs" com formato errado, item que não é dict
    async_dispatcher_send(hass, SIGNAL_NOVIDADE.format(sub_mun.subentry_id), {})
    async_dispatcher_send(
        hass, SIGNAL_NOVIDADE.format(sub_mun.subentry_id), {"erbs": "não é lista"}
    )
    async_dispatcher_send(
        hass, SIGNAL_NOVIDADE.format(sub_mun.subentry_id), {"erbs": ["string_solta"]}
    )

    # iOS: sem "novidades", "operadora" ausente/None, "tipo" inválido/None
    async_dispatcher_send(hass, SIGNAL_NOVIDADE.format(sub_ios.subentry_id), {})
    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_ios.subentry_id),
        {"novidades": [{"tipo": "tipo_desconhecido"}]},
    )
    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_ios.subentry_id),
        {"novidades": [{"operadora": None, "tipo": None}]},
    )
    await hass.async_block_till_done()

    # sobrevive: entidades continuam existindo e com estado válido
    assert hass.states.get("event.novas_torres_em_sao_paulo_sp") is not None
    estado_ios = hass.states.get("event.novidades_do_ios")
    assert estado_ios is not None
    # tipo inválido/ausente cai no default "alterada" (um dos tipos válidos)
    assert estado_ios.attributes["event_type"] == "alterada"
    assert estado_ios.attributes["operadora"] is None
