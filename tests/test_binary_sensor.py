"""Testes dos binary sensors."""

from types import MappingProxyType
from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.config_entries import ConfigSubentry

from custom_components.redes_moveis_fixas.binary_sensor import (
    Disponivel5GBinarySensor,
    MonitorAtivoBinarySensor,
    StatusApiBinarySensor,
)

from .conftest import load_fixture
from .test_sensor import _setup


async def test_binary_sensors(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    mock_client.async_listar_monitores.side_effect = None
    mock_client.async_listar_monitores.return_value = []
    await _setup(hass, entry_completa, mock_client)

    status = hass.states.get("binary_sensor.status_da_api_rmf")
    assert status.state == "on"
    assert status.attributes["device_class"] == BinarySensorDeviceClass.CONNECTIVITY

    assert hass.states.get("binary_sensor.5g_disponivel_em_casa").state == "on"
    # monitor recém-criado ainda não aparece na listagem mockada (vazia) → off
    assert hass.states.get("binary_sensor.monitor_ios_ativo").state == "off"
    # idem pro monitor do município
    assert hass.states.get("binary_sensor.monitor_de_sao_paulo_sp_ativo").state == "off"


async def test_monitor_ativo_quando_listado(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    def _listar(tipo):
        if tipo == "ios":
            return load_fixture("monitores_ios_lista.json")["dados"]["monitores"]
        return []

    mock_client.async_listar_monitores.side_effect = _listar
    await _setup(hass, entry_completa, mock_client)

    estado = hass.states.get("binary_sensor.monitor_ios_ativo")
    assert estado.state == "on"
    assert estado.attributes["falhas_seguidas"] == 0


async def test_monitor_cidade_ativo_quando_listado(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    def _listar(tipo):
        if tipo == "cidade":
            return [
                {
                    "id": "9f1c0001",
                    "ativo": True,
                    "falhas_seguidas": 2,
                    "ultima_entrega": "2026-07-25T00:00:00.000Z",
                    "ultimo_erro": "timeout",
                }
            ]
        return []

    mock_client.async_listar_monitores.side_effect = _listar
    await _setup(hass, entry_completa, mock_client)

    estado = hass.states.get("binary_sensor.monitor_de_sao_paulo_sp_ativo")
    assert estado.state == "on"
    assert estado.attributes["falhas_seguidas"] == 2
    assert estado.attributes["ultimo_erro"] == "timeout"


async def test_5g_indisponivel(hass, entry_completa, mock_client):
    """Cobertura sem tecnologia 5G em nenhum provedor -> sensor off."""
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    mock_client.async_cobertura.return_value = {
        "cobertura": [
            {
                "provedor": "Claro",
                "tecnologias_suportadas": [{"rede": "4G", "forca_sinal": 4}],
            }
        ]
    }
    await _setup(hass, entry_completa, mock_client)

    assert hass.states.get("binary_sensor.5g_disponivel_em_casa").state == "off"


async def test_status_api_off_quando_health_nao_ok(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    mock_client.async_health.return_value = {"status": "degraded"}
    await _setup(hass, entry_completa, mock_client)

    assert hass.states.get("binary_sensor.status_da_api_rmf").state == "off"


def _subentry(subentry_type: str, data: dict, title: str = "Teste") -> ConfigSubentry:
    return ConfigSubentry(
        data=MappingProxyType(data),
        subentry_id="sub_teste",
        subentry_type=subentry_type,
        title=title,
        unique_id=None,
    )


def test_monitor_ativo_tolera_id_ausente():
    """Subentry sem monitor_id (ainda não provisionado): não pode explodir."""
    coordinator = MagicMock()
    coordinator.data = {"outro_id": {"ativo": True}}
    subentry = _subentry("municipio", {})

    sensor = MonitorAtivoBinarySensor(coordinator, subentry, "Monitor de Teste ativo")

    assert sensor.is_on is False
    assert sensor.extra_state_attributes == {
        "falhas_seguidas": None,
        "ultima_entrega": None,
        "ultimo_erro": None,
    }


def test_monitor_ativo_tolera_coordinator_data_vazio():
    """coordinator.data ausente/None (nunca atualizou): não pode explodir."""
    coordinator = MagicMock()
    coordinator.data = None
    subentry = _subentry("monitor_ios", {"monitor_id": "abc123"})

    sensor = MonitorAtivoBinarySensor(coordinator, subentry, "Monitor iOS ativo")

    assert sensor.is_on is False
    assert sensor.extra_state_attributes == {
        "falhas_seguidas": None,
        "ultima_entrega": None,
        "ultimo_erro": None,
    }


def test_5g_tolera_coordinator_data_vazio():
    coordinator = MagicMock()
    coordinator.data = None
    subentry = _subentry("local", {}, title="Casa")

    sensor = Disponivel5GBinarySensor(coordinator, subentry)

    assert sensor.is_on is False


def test_status_api_tolera_data_vazio():
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.last_update_success = True

    sensor = StatusApiBinarySensor(coordinator, MagicMock(entry_id="entry1"))

    assert sensor.is_on is False
