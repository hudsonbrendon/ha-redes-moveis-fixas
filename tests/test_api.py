"""Testes do RMFClient."""

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.redes_moveis_fixas.api import (
    RMFAuthError,
    RMFClient,
    RMFError,
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


async def test_listar_monitores_aceita_envelope_e_lista(client):
    """A API real devolve `dados` como envelope `{"total", "monitores"}`.

    Sem normalizar, o consumidor itera o dict e recebe as CHAVES (strings) —
    foi assim que o setup quebrou com "'str' object has no attribute 'get'" na
    primeira instalação real. Uma lista pura também precisa continuar valendo.
    """
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/monitorar-ios",
            payload={"status": "ok", "dados": {"total": 0, "monitores": []}},
        )
        assert await client.async_listar_monitores("ios") == []

        m.get(
            f"{BASE_URL}/api/monitorar-cidade",
            payload={"status": "ok", "dados": [{"id": "abc", "ativo": True}]},
        )
        lista = await client.async_listar_monitores("cidade")
        assert [mon["id"] for mon in lista] == ["abc"]

        m.get(
            f"{BASE_URL}/api/monitorar-ios",
            payload={"status": "ok", "dados": "nada disso"},
        )
        with pytest.raises(RMFError):
            await client.async_listar_monitores("ios")


@pytest.mark.parametrize(
    ("status", "exc"),
    [(403, RMFAuthError), (429, RMFRateLimitError), (404, RMFNotFoundError)],
)
async def test_erros(client, status, exc):
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/cobertura?lat=0&lon=0",
            status=status,
            payload={"error": "x"},
        )
        with pytest.raises(exc):
            await client.async_cobertura(0, 0)


async def test_erro_http_generico_mapeia_para_rmferror(client):
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/cobertura?lat=0&lon=0",
            status=500,
            payload={"error": "boom"},
        )
        with pytest.raises(RMFError):
            await client.async_cobertura(0, 0)


async def test_erro_conexao_mapeia_para_rmferror(client):
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/cobertura?lat=0&lon=0",
            exception=aiohttp.ClientConnectionError("boom"),
        )
        with pytest.raises(RMFError):
            await client.async_cobertura(0, 0)


def _headers_for(m, method: str, url: str) -> dict:
    key = (
        method,
        next(k[1] for k in m.requests if k[0] == method and str(k[1]) == url),
    )
    return m.requests[key][-1].kwargs["headers"]


async def test_auth_header_enviado_e_health_sem_auth(client):
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/cobertura?lat=0&lon=0",
            payload=load_fixture("cobertura.json"),
        )
        m.get(f"{BASE_URL}/health", payload=load_fixture("health.json"))

        await client.async_cobertura(0, 0)
        await client.async_health()

        cobertura_headers = _headers_for(
            m, "GET", f"{BASE_URL}/api/cobertura?lat=0&lon=0"
        )
        health_headers = _headers_for(m, "GET", f"{BASE_URL}/health")

    assert cobertura_headers["Authorization"] == "Bearer tok_test"
    assert "Authorization" not in health_headers


async def test_dados_ausente_vira_rmferror(client):
    """Finding 4: `payload["dados"]` cru levantava KeyError (fora da
    hierarquia RMFError), o que bypassa toda tradução de erro rio abaixo
    (SETUP_ERROR em vez de SETUP_RETRY, traceback cru em automações, etc).
    Uma resposta malformada (sem "dados") agora vira RMFError.
    """
    with aioresponses() as m:
        m.get(
            f"{BASE_URL}/api/cobertura?lat=0&lon=0",
            payload={"status": "ok"},  # sem "dados"
        )
        with pytest.raises(RMFError):
            await client.async_cobertura(0, 0)


async def test_criar_monitor_sem_id_ou_secret_vira_rmferror(client):
    """Resposta de criação de monitor sem `id`/`secret`: `_provisionar_monitor`
    (__init__.py) lê esses campos direto pra persistir na subentry — sem
    validação aqui, a mesma KeyError fora da hierarquia RMFError escaparia.
    """
    with aioresponses() as m:
        m.post(
            f"{BASE_URL}/api/monitorar-ios",
            status=201,
            payload={"status": "ok", "dados": {"id": "abc123"}},  # sem "secret"
        )
        with pytest.raises(RMFError):
            await client.async_criar_monitor_ios(
                "https://ha.example.com/api/webhook/abc", ["BR"]
            )


async def test_criar_monitor_cidade(client):
    fixture = {
        "status": "ok",
        "dados": {
            "id": "abc123",
            "url": "https://ha.example.com/api/webhook/xyz",
            "municipios": ["3550308"],
            "secret": "whsec_cidade_test",
        },
    }
    with aioresponses() as m:
        m.post(f"{BASE_URL}/api/monitorar-cidade", status=201, payload=fixture)
        dados = await client.async_criar_monitor_cidade(
            "https://ha.example.com/api/webhook/xyz", ["3550308"]
        )
        key = next(
            k for k in m.requests if str(k[1]) == f"{BASE_URL}/api/monitorar-cidade"
        )
        body_sem_descricao = m.requests[key][-1].kwargs["json"]
    assert dados["secret"] == "whsec_cidade_test"
    assert body_sem_descricao == {
        "url": "https://ha.example.com/api/webhook/xyz",
        "municipios": ["3550308"],
    }

    with aioresponses() as m:
        m.post(f"{BASE_URL}/api/monitorar-cidade", status=201, payload=fixture)
        await client.async_criar_monitor_cidade(
            "https://ha.example.com/api/webhook/xyz", ["3550308"], descricao="teste"
        )
        key = next(
            k for k in m.requests if str(k[1]) == f"{BASE_URL}/api/monitorar-cidade"
        )
        body_com_descricao = m.requests[key][-1].kwargs["json"]
    assert body_com_descricao["descricao"] == "teste"
