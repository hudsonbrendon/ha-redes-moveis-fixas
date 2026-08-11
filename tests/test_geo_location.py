"""Testes das entities geo_location."""

import asyncio

from custom_components.redes_moveis_fixas.const import SUBENTRY_LOCAL
from custom_components.redes_moveis_fixas.geo_location import (
    ErbGeolocationEvent,
    _GerenteErbs,
    _remover,
)

from .test_sensor import _setup


def _erbs_geo(hass):
    return [
        s
        for s in hass.states.async_all("geo_location")
        if s.attributes.get("source") == "redes_moveis_fixas"
    ]


def _sid_local(entry):
    return next(
        s.subentry_id
        for s in entry.subentries.values()
        if s.subentry_type == SUBENTRY_LOCAL
    )


async def test_erbs_no_mapa(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    estados = _erbs_geo(hass)
    assert len(estados) == 2  # fixture tem 2 ERBs
    claro = next(s for s in estados if "claro" in s.name.lower())
    assert claro.attributes["latitude"] == -23.5601
    assert float(claro.state) == 1.2


async def test_max_geo_zero_nao_cria_entidades(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    sid = _sid_local(entry_completa)
    sub = entry_completa.subentries[sid]
    hass.config_entries.async_update_subentry(
        entry_completa, sub, data={**sub.data, "max_geo": 0}
    )

    await _setup(hass, entry_completa, mock_client)

    assert _erbs_geo(hass) == []


async def test_top_n_trunca(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    sid = _sid_local(entry_completa)
    sub = entry_completa.subentries[sid]
    hass.config_entries.async_update_subentry(
        entry_completa, sub, data={**sub.data, "max_geo": 1}
    )

    await _setup(hass, entry_completa, mock_client)

    estados = _erbs_geo(hass)
    assert len(estados) == 1
    # a mais próxima (Claro, 1.2 km) vence sobre a Vivo (2.4 km)
    assert "claro" in estados[0].name.lower()


async def test_atualizacao_adiciona_erb(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    assert len(_erbs_geo(hass)) == 2

    sid = _sid_local(entry_completa)
    rt = entry_completa.runtime_data
    dados = dict(mock_client.async_estacoes.return_value)
    nova = {
        "id": "9999999",
        "operadora": "Tim",
        "distancia_km": 0.5,
        "tecnologias": ["LTE"],
        "bandas": ["3"],
        "coordenadas": {"lat": -23.5, "lon": -46.6},
        "endereco": {},
    }
    dados["erbs"] = [*dados["erbs"], nova]
    mock_client.async_estacoes.return_value = dados
    await rt.erbs[sid].async_refresh()
    await hass.async_block_till_done()

    estados = _erbs_geo(hass)
    assert len(estados) == 3
    assert any("tim" in s.name.lower() for s in estados)


async def test_atualizacao_remove_erb(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    assert len(_erbs_geo(hass)) == 2

    sid = _sid_local(entry_completa)
    rt = entry_completa.runtime_data
    dados = dict(mock_client.async_estacoes.return_value)
    dados["erbs"] = [e for e in dados["erbs"] if e["operadora"] != "Vivo"]
    mock_client.async_estacoes.return_value = dados
    await rt.erbs[sid].async_refresh()
    await hass.async_block_till_done()

    estados = _erbs_geo(hass)
    assert len(estados) == 1
    assert "vivo" not in estados[0].name.lower()


async def test_remover_nao_gira_pra_sempre_em_add_abortado(
    hass, entry_completa, mock_client
):
    """Regressão do fix 1/5: add_to_platform_abort() zera `hass` pra sempre.

    Antes do teto, `_remover` fazia `while ent.hass is None: await
    asyncio.sleep(0)` — pra uma entity cujo add nunca aconteceu (abortado)
    isso girava pelo resto do processo. `asyncio.wait_for` prova o teto:
    sem ele, este teste estouraria em TimeoutError.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    sid = _sid_local(entry_completa)
    coord = entry_completa.runtime_data.erbs[sid]
    sub = entry_completa.subentries[sid]

    # Entity construída direto, nunca passada por async_add_entities/entity_platform
    # — `hass` nunca é setado, exatamente como no caso de um add abortado.
    orfa = ErbGeolocationEvent(
        coord,
        sub,
        {
            "id": "orfa",
            "operadora": "X",
            "distancia_km": 9.9,
            "coordenadas": {"lat": 0, "lon": 0},
        },
    )
    assert orfa.hass is None

    await asyncio.wait_for(_remover(orfa), timeout=2)
    # não levantou, não travou — desistiu em silêncio.


async def test_gerente_recupera_entity_com_add_abortado(
    hass, entry_completa, mock_client
):
    """Regressão do fix 2/5: entity abortada não pode ficar "tracked" pra sempre.

    Simula o add sempre abortando (callback fake nunca seta `ent.hass`).
    Sem o purge no início de `_sincronizar`, a torre continuaria tracked
    como se estivesse viva e nunca mais seria recriada.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)
    sid = _sid_local(entry_completa)
    coord = entry_completa.runtime_data.erbs[sid]
    sub = entry_completa.subentries[sid]

    lotes_adicionados = []
    gerente = _GerenteErbs(
        coord, sub, lambda ents, **kw: lotes_adicionados.append(ents), max_geo=25
    )
    # __init__ já rodou uma sincronização: 2 ERBs tracked, todas com hass
    # None (o callback fake nunca as adiciona de verdade — abortadas).
    assert len(lotes_adicionados) == 1
    assert len(lotes_adicionados[0]) == 2
    assert all(ent.hass is None for ent in gerente._entities.values())

    # dados do coordinator não mudaram — mesmas 2 ERBs continuam no top-N.
    gerente._sincronizar()

    # sem o purge, isto seria [] (as duas já estariam "tracked"); com o
    # purge, as duas foram descartadas e recriadas.
    assert len(lotes_adicionados) == 2
    assert len(lotes_adicionados[1]) == 2


async def test_unload_remove_listener_do_gerente(hass, entry_completa, mock_client):
    """O unsub do _GerenteErbs precisa sair do coordinator no unload.

    Sem isso o coordinator (que sobrevive ao unload em runtime_data) fica
    chamando _sincronizar pra sempre, mesmo com a entry descarregada.
    """
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sid = _sid_local(entry_completa)
    coord = entry_completa.runtime_data.erbs[sid]
    # cada entity também escuta o coordinator (CoordinatorEntity) — o que
    # importa aqui é que o listener do _GerenteErbs (o extra, fora das
    # entities) some do coordinator.
    listeners_antes = len(coord._listeners)
    assert listeners_antes > 0

    assert await hass.config_entries.async_unload(entry_completa.entry_id)
    await hass.async_block_till_done()

    # todas as entities saíram (unsub próprio delas) e o unsub manual do
    # gerente também rodou: nada deve sobrar escutando o coordinator.
    assert len(coord._listeners) == 0


async def test_registro_malformado_nao_quebra(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    mock_client.async_estacoes.return_value = {
        "total_erbs": 4,
        "erbs": [
            {
                "operadora": "SemId",
                "distancia_km": 1.0,
                "coordenadas": {"lat": 0, "lon": 0},
            },
            {"id": "sem-coords", "operadora": "SemCoords", "distancia_km": 1.0},
            {
                "id": "coords-invalidas",
                "operadora": "X",
                "coordenadas": {"lat": "n/d", "lon": -46},
            },
            {
                "id": "ok1",
                "operadora": "Claro",
                "distancia_km": 3.0,
                "coordenadas": {"lat": -23.5, "lon": -46.6},
            },
        ],
    }

    # Não pode levantar exceção durante o setup.
    await _setup(hass, entry_completa, mock_client)

    estados = _erbs_geo(hass)
    assert len(estados) == 1
    assert "claro" in estados[0].name.lower()
