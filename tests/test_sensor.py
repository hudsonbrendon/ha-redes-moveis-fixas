"""Testes dos sensores."""

from unittest.mock import patch


async def _setup(hass, entry, client):
    with (
        patch("custom_components.redes_moveis_fixas.RMFClient", return_value=client),
        patch(
            "custom_components.redes_moveis_fixas.webhook_async_generate_url",
            return_value="https://ha.example.com/api/webhook/wh_fixo",
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_sensores_de_cobertura(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    vivo = hass.states.get("sensor.cobertura_da_vivo_em_casa")
    assert vivo.state == "90"
    assert vivo.attributes["classificacao"] == "Excelente"
    assert vivo.attributes["5G"] == 5

    melhor = hass.states.get("sensor.melhor_cobertura_em_casa")
    assert melhor.state == "Vivo"

    erbs = hass.states.get("sensor.erbs_por_perto_de_casa")
    assert erbs.state == "418"
    assert erbs.attributes["por_operadora"]["Claro"] == 1

    dist = hass.states.get("sensor.distancia_da_erb_mais_proxima_de_casa")
    assert dist.state == "1.2"
    assert dist.attributes["operadora"] == "Claro"


async def test_sensores_de_municipio(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    assert hass.states.get("sensor.erbs_em_sao_paulo_sp").state == "6364"
    s5g = hass.states.get("sensor.erbs_5g_em_sao_paulo_sp")
    assert s5g.state == "3944"
    assert s5g.attributes["por_operadora"]["Vivo"] == 1402


async def test_sensores_da_api(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    base = hass.states.get("sensor.base_de_cobertura_atualizada_em")
    assert base.state.startswith("2026-07-22")
