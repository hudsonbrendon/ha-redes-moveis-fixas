"""Testes dos sensores."""

from unittest.mock import patch

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from .conftest import load_fixture


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
    # os dois device de dependência da entry, não só "cobertura"
    base_estacoes = hass.states.get("sensor.base_de_estacoes_atualizada_em")
    assert base_estacoes.state.startswith("2026-07-23")


async def test_sensores_extra_cobertura_e_municipio(hass, entry_completa, mock_client):
    """Cobre segundo provedor, campo 'estacoes', tecnologia != 5G e atributos.

    Também verifica os atributos de distância (endereco/tecnologias/bandas).
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    claro = hass.states.get("sensor.cobertura_da_claro_em_casa")
    assert claro.state == "72"
    assert claro.attributes["classificacao"] == "Boa"
    assert claro.attributes["4G"] == 4

    assert hass.states.get("sensor.estacoes_em_sao_paulo_sp").state == "77790"

    s4g = hass.states.get("sensor.erbs_4g_em_sao_paulo_sp")
    assert s4g.state == "6201"
    assert s4g.attributes["por_operadora"]["Vivo"] == 2190

    dist = hass.states.get("sensor.distancia_da_erb_mais_proxima_de_casa")
    assert dist.attributes["endereco"] == {
        "logradouro": "Av. Paulista, 1000",
        "cidade": "São Paulo",
        "uf": "SP",
    }
    assert dist.attributes["tecnologias"] == ["LTE", "NR"]
    assert dist.attributes["bandas"] == ["3", "1", "40", "78"]


async def test_atributos_dos_tipos_de_sensor(hass, entry_completa, mock_client):
    """Um sensor por 'tipo': device_class/state_class/unit não podem trocar em silêncio.

    Falha se algum destes for alterado sem querer numa refatoração.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    percentual = hass.states.get("sensor.cobertura_da_vivo_em_casa")
    assert percentual.attributes["unit_of_measurement"] == "%"
    assert percentual.attributes["state_class"] == SensorStateClass.MEASUREMENT
    assert "device_class" not in percentual.attributes

    distancia = hass.states.get("sensor.distancia_da_erb_mais_proxima_de_casa")
    assert distancia.attributes["device_class"] == SensorDeviceClass.DISTANCE
    assert distancia.attributes["unit_of_measurement"] == "km"
    assert distancia.attributes["state_class"] == SensorStateClass.MEASUREMENT

    timestamp = hass.states.get("sensor.base_de_cobertura_atualizada_em")
    assert timestamp.attributes["device_class"] == SensorDeviceClass.TIMESTAMP
    assert "unit_of_measurement" not in timestamp.attributes
    assert "state_class" not in timestamp.attributes

    contagem = hass.states.get("sensor.erbs_por_perto_de_casa")
    assert contagem.attributes["state_class"] == SensorStateClass.MEASUREMENT
    assert "device_class" not in contagem.attributes
    assert "unit_of_measurement" not in contagem.attributes

    total_municipio = hass.states.get("sensor.erbs_em_sao_paulo_sp")
    assert total_municipio.attributes["state_class"] == SensorStateClass.MEASUREMENT


async def test_sensores_toleram_dados_vazios(hass, entry_completa, mock_client):
    """Coordenadas e resumo do município ausentes: coordinator.data vira {}."""
    mock_client.async_resumo_municipio.return_value = {}
    await _setup(hass, entry_completa, mock_client)

    esperado_unknown = (
        "sensor.melhor_cobertura_em_casa",
        "sensor.erbs_por_perto_de_casa",
        "sensor.distancia_da_erb_mais_proxima_de_casa",
        "sensor.erbs_em_sao_paulo_sp",
        "sensor.estacoes_em_sao_paulo_sp",
        "sensor.erbs_5g_em_sao_paulo_sp",
        "sensor.base_de_sao_paulo_sp_atualizada_em",
    )
    for entity_id in esperado_unknown:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state == "unknown", entity_id

    # cobertura sem coordenadas: coordinator.data == {} -> nenhum provedor, nenhuma
    # entidade de cobertura por operadora é criada (limitação conhecida/aceita)
    assert hass.states.get("sensor.cobertura_da_vivo_em_casa") is None

    erbs = hass.states.get("sensor.erbs_por_perto_de_casa")
    assert erbs.attributes["por_operadora"] == {}
    assert erbs.attributes["por_tecnologia"] == {}

    dist = hass.states.get("sensor.distancia_da_erb_mais_proxima_de_casa")
    for chave in ("operadora", "endereco", "tecnologias", "bandas"):
        assert chave not in dist.attributes


async def test_sensores_toleram_payload_malformado(hass, entry_completa, mock_client):
    """Registros incompletos da API degradam pra None/skip, sem derrubar a plataforma.

    Reproduz a Finding 1 do review: campos ausentes num item não crasham nem
    o setup da platform nem a leitura das entidades vizinhas.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    mock_client.async_cobertura.return_value = {
        "cobertura": [
            {"qualidade_global": {"score_percentual": 50, "classificacao": "Ok"}},
            {"provedor": "Tim"},  # sem qualidade_global
            {
                "provedor": "Vivo",
                "qualidade_global": {
                    "score_percentual": 90,
                    "classificacao": "Excelente",
                },
                "tecnologias_suportadas": [{"forca_sinal": 5}],  # sem "rede"
            },
        ]
    }
    mock_client.async_estacoes.return_value = {
        "total_erbs": 2,
        "erbs": [
            {"operadora": "Claro"},  # sem distancia_km
            {"distancia_km": 3.0},  # sem operadora
            "lixo",  # item não é nem um dict
        ],
    }
    mock_client.async_health.return_value = {
        "status": "ok",
        "dependencias": [
            {"atualizado_em": "2026-07-22T09:14:02.000Z"},  # sem "nome"
            {"nome": "estacoes", "atualizado_em": "2026-07-23T11:02:47.000Z"},
        ],
    }
    await _setup(hass, entry_completa, mock_client)

    # registro sem "provedor" foi pulado no setup — não derrubou a plataforma inteira
    assert hass.states.get("sensor.cobertura_da_tim_em_casa").state == "unknown"
    vivo = hass.states.get("sensor.cobertura_da_vivo_em_casa")
    assert vivo.state == "90"
    assert vivo.attributes.get("5G") is None  # tecnologia sem "rede" foi ignorada

    melhor = hass.states.get("sensor.melhor_cobertura_em_casa")
    assert melhor.state == "Vivo"

    dist = hass.states.get("sensor.distancia_da_erb_mais_proxima_de_casa")
    assert dist.state == "3.0"
    assert dist.attributes["operadora"] is None

    erbs = hass.states.get("sensor.erbs_por_perto_de_casa")
    assert erbs.attributes["por_operadora"] == {"Claro": 1}

    # dependência sem "nome" nunca casa com "cobertura" -> estado unknown, sem KeyError
    assert hass.states.get("sensor.base_de_cobertura_atualizada_em").state == "unknown"
    assert hass.states.get("sensor.base_de_estacoes_atualizada_em").state.startswith(
        "2026-07-23"
    )


async def test_timestamp_sem_timezone_nao_quebra(hass, entry_completa, mock_client):
    """parse_datetime sem offset volta naive; TIMESTAMP não pode receber isso cru."""
    mock_client.async_health.return_value = {
        "status": "ok",
        "dependencias": [
            {"nome": "cobertura", "atualizado_em": "2026-07-22T09:14:02"},
        ],
    }
    await _setup(hass, entry_completa, mock_client)

    state = hass.states.get("sensor.base_de_cobertura_atualizada_em")
    assert state is not None
    assert state.state != "unknown"


async def test_ultima_novidade_ios(hass, entry_completa, mock_client):
    """mock_client.async_listar_monitores devolve [] por padrão; sobrescrito só aqui."""

    async def _listar(tipo):
        if tipo == "ios":
            return load_fixture("monitores_ios_lista.json")["dados"]["monitores"]
        return []

    mock_client.async_listar_monitores.side_effect = _listar
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    state = hass.states.get("sensor.ultima_novidade_do_ios")
    assert state is not None
    assert state.state.startswith("2026-07-26")
