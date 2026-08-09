"""Testes do RMFClient."""

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.redes_moveis_fixas.api import (
    RMFAuthError,
    RMFClient,
    RMFNotFoundError,
    RMFRateLimitError,
)
from custom_components.redes_moveis_fixas.const import BASE_URL

from .conftest import load_fixture


@pytest.fixture
async def client():
    async with aiohttp.ClientSession() as session:
        yield RMFClient(session, "tok_test")


async def test_cobertura(client):
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/cobertura?lat=-23.56&lon=-46.65",
            payload=load_fixture("cobertura.json"),
        )
        dados = await client.async_cobertura(-23.56, -46.65)
    assert dados["cobertura"][0]["provedor"] == "Vivo"


async def test_estacoes_com_filtros(client):
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/estacoes?lat=-23.56&limite=10&lon=-46.65&operadora=claro,vivo&tecnologia=NR",
            payload=load_fixture("estacoes.json"),
        )
        dados = await client.async_estacoes(
            -23.56, -46.65, operadora=["claro", "vivo"], tecnologia=["NR"], limite=10
        )
    assert dados["total_erbs"] == 418
    assert len(dados["erbs"]) == 2


async def test_resumo_municipio(client):
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/municipios/3550308/resumo",
            payload=load_fixture("resumo_municipio.json"),
        )
        dados = await client.async_resumo_municipio(3550308)
    assert dados["municipio"]["nome"] == "São Paulo"


async def test_health(client):
    with aioresponses() as m:
        m.get(f"{BASE_URL}/health", payload=load_fixture("health.json"))
        payload = await client.async_health()
    assert payload["status"] == "ok"


async def test_criar_e_listar_monitor_ios(client):
    with aioresponses() as m:
        m.post(
            f"{BASE_URL}/api/monitorar-ios",
            status=201,
            payload=load_fixture("monitor_ios_criado.json"),
        )
        dados = await client.async_criar_monitor_ios(
            "https://ha.example.com/api/webhook/abc", ["BR"]
        )
        assert dados["secret"].startswith("whsec_")

        m.get(
            f"{BASE_URL}/api/monitorar-ios",
            payload=load_fixture("monitores_ios_lista.json"),
        )
        lista = await client.async_listar_monitores("ios")
        assert lista[0]["ativo"] is True

        m.delete(f"{BASE_URL}/api/monitorar-ios/3ab7f001", status=204)
        await client.async_remover_monitor("ios", "3ab7f001")


@pytest.mark.parametrize(
    ("status", "exc"),
    [(403, RMFAuthError), (429, RMFRateLimitError), (404, RMFNotFoundError)],
)
async def test_erros(client, status, exc):
    with aioresponses() as m:
        m.get(f"{BASE_URL}/api/cobertura?lat=0&lon=0", status=status, payload={"error": "x"})
        with pytest.raises(exc):
            await client.async_cobertura(0, 0)
