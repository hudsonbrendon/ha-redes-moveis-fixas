# ha-redes-moveis-fixas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Custom component HA `redes_moveis_fixas` — cobertura móvel, ERBs próximas, resumo municipal e monitores por webhook (torres novas + carrier bundles iOS) da API RMF.

**Architecture:** Hub config entry (token) + subentries (Local / Município / Monitor iOS). Cliente aiohttp puro em `api.py`; DataUpdateCoordinators por tipo de dado; webhook único por entry com verificação HMAC e dispatch por dispatcher signal; entities só leem `coordinator.data` ou escutam o signal.

**Tech Stack:** Python 3.13, aiohttp, Home Assistant ≥ 2025.7 (config subentries), pytest + pytest-homeassistant-custom-component + aioresponses.

## Global Constraints

- Domain: `redes_moveis_fixas`; repo: `~/Github/ha-redes-moveis-fixas` (git já iniciado, spec commitado).
- Base URL: `https://api.redesmoveisfixas.com`; auth: header `Authorization: Bearer <token>`.
- Nomenclatura de entity: `<medida>_<prep>_<local>` PT-BR via `translation_key` + `has_entity_name = True`.
- Assinatura webhook: `X-RMF-Signature: sha256=<hex>` = HMAC-SHA256(`{X-RMF-Timestamp}.{corpo cru}`, key=`secret` do monitor); tolerância 300 s.
- Secret do monitor só aparece na criação (POST 201) — guardar em `subentry.data`; redigir em diagnostics.
- Manifest: `iot_class: cloud_polling`, `integration_type: hub`, `dependencies: ["webhook"]`, `codeowners: ["@hudsonbrendon"]`.
- Rodar testes: `cd ~/Github/ha-redes-moveis-fixas && .venv/bin/python -m pytest tests/ -q`.
- Commits frequentes, mensagens `feat:`/`test:`/`chore:` em inglês.
- TDD: teste primeiro, ver falhar, implementar, ver passar, commit.

---

### Task 1: Scaffold + fixtures + const

**Files:**
- Create: `hacs.json`, `custom_components/redes_moveis_fixas/manifest.json`, `custom_components/redes_moveis_fixas/const.py`, `custom_components/redes_moveis_fixas/__init__.py` (stub mínimo), `requirements_test.txt`, `pyproject.toml`, `tests/__init__.py`, `tests/conftest.py`, `tests/fixtures/{cobertura,estacoes,resumo_municipio,health,monitor_ios_criado,monitores_ios_lista,webhook_cidade,webhook_ios}.json`
- Test: `tests/test_const.py`

**Interfaces:**
- Produces: `DOMAIN = "redes_moveis_fixas"`; todas as const keys (código abaixo); `tests/conftest.py::load_fixture(name)`.

- [ ] **Step 1: Criar arquivos de projeto**

`requirements_test.txt`:
```
pytest>=8.0
pytest-asyncio>=0.23
pytest-homeassistant-custom-component>=0.13.230
aioresponses>=0.7
aiohttp
```

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py313"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP"]
```

`hacs.json`:
```json
{
    "name": "Redes Móveis Fixas",
    "homeassistant": "2025.7.0",
    "hacs": "2.0.1"
}
```

`custom_components/redes_moveis_fixas/manifest.json`:
```json
{
  "domain": "redes_moveis_fixas",
  "name": "Redes Móveis Fixas",
  "codeowners": ["@hudsonbrendon"],
  "config_flow": true,
  "dependencies": ["webhook"],
  "documentation": "https://github.com/hudsonbrendon/ha-redes-moveis-fixas",
  "integration_type": "hub",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/hudsonbrendon/ha-redes-moveis-fixas/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

`custom_components/redes_moveis_fixas/const.py`:
```python
"""Constantes da integração Redes Móveis Fixas."""

from datetime import timedelta

DOMAIN = "redes_moveis_fixas"

BASE_URL = "https://api.redesmoveisfixas.com"

# Config entry
CONF_TOKEN = "token"
CONF_WEBHOOK_ID = "webhook_id"

# Subentry types
SUBENTRY_LOCAL = "local"
SUBENTRY_MUNICIPIO = "municipio"
SUBENTRY_MONITOR_IOS = "monitor_ios"

# Subentry Local
CONF_MODO = "modo"  # "zona" | "pessoa"
CONF_ENTITY_ID = "entity_id"
CONF_INTERVALO_COBERTURA = "intervalo_cobertura"  # minutos
CONF_INTERVALO_ERBS = "intervalo_erbs"  # horas
CONF_MAX_GEO = "max_geo"

DEFAULT_INTERVALO_COBERTURA_MIN = 30
DEFAULT_INTERVALO_ERBS_H = 6
DEFAULT_MAX_GEO = 25

# Subentry Município
CONF_IBGE = "codigo_ibge"
CONF_MONITORAR = "monitorar"
CONF_INTERVALO_MUNICIPIO = "intervalo_municipio"  # horas
DEFAULT_INTERVALO_MUNICIPIO_H = 12

# Subentry Monitor iOS
CONF_PAISES = "paises"
CONF_OPERADORAS = "operadoras"
CONF_INCLUIR_BETA = "incluir_beta"

# Monitor (comum às subentries com webhook)
CONF_MONITOR_ID = "monitor_id"
CONF_MONITOR_SECRET = "monitor_secret"

# Intervalos fixos (entry-level)
INTERVALO_HEALTH = timedelta(minutes=15)
INTERVALO_MONITORES = timedelta(hours=6)

# Person-follow
DISTANCIA_MINIMA_M = 500
INTERVALO_MINIMO_PESSOA = timedelta(minutes=10)

# Webhook
TOLERANCIA_TIMESTAMP_S = 300
EVENTO_CIDADE = "novidades.cidade"
EVENTO_IOS = "novidades.ios"

# Bus / dispatcher
EVENT_NOVIDADE = "redes_moveis_fixas_novidade"
SIGNAL_NOVIDADE = "redes_moveis_fixas_novidade_{}"  # .format(subentry_id)

PLATFORMS = ["binary_sensor", "event", "geo_location", "sensor"]
```

`custom_components/redes_moveis_fixas/__init__.py` (stub, Task 6 completa):
```python
"""Integração Redes Móveis Fixas."""
```

`tests/__init__.py`: vazio. `tests/conftest.py`:
```python
"""Fixtures compartilhadas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    """Carrega fixture JSON (re-lê a cada chamada; pode mutar)."""
    return json.loads((FIXTURE_DIR / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Habilita custom integrations em todos os testes."""
    yield
```

- [ ] **Step 2: Criar fixtures JSON** (copiadas da doc da API)

`tests/fixtures/cobertura.json`:
```json
{
  "status": "ok",
  "dados": {
    "cobertura": [
      {
        "provedor": "Vivo",
        "qualidade_global": {"score_percentual": 90, "classificacao": "Excelente"},
        "tecnologias_suportadas": [
          {"rede": "5G", "forca_sinal": 5, "status": "Excelente"},
          {"rede": "4G", "forca_sinal": 4, "status": "Boa"}
        ]
      },
      {
        "provedor": "Claro",
        "qualidade_global": {"score_percentual": 72, "classificacao": "Boa"},
        "tecnologias_suportadas": [
          {"rede": "4G", "forca_sinal": 4, "status": "Boa"}
        ]
      }
    ]
  }
}
```

`tests/fixtures/estacoes.json`:
```json
{
  "status": "ok",
  "dados": {
    "raio_utilizado_km": 5,
    "filtros": {"operadora": null, "tecnologia": null, "banda": null},
    "total_erbs": 418,
    "retornadas": 2,
    "limite": 200,
    "offset": 0,
    "tem_mais": true,
    "erbs": [
      {
        "id": "1234567",
        "operadora": "Claro",
        "distancia_km": 1.2,
        "tecnologias": ["LTE", "NR"],
        "bandas": ["3", "1", "40", "78"],
        "coordenadas": {"lat": -23.5601, "lon": -46.6503},
        "endereco": {"logradouro": "Av. Paulista, 1000", "cidade": "São Paulo", "uf": "SP"},
        "estacao": {"tipo": "Estação base de celular (FB)", "infraestrutura": "Torre", "licenciamento": "2019-04-02", "validade": "2029-04-02"}
      },
      {
        "id": "7654321",
        "operadora": "Vivo",
        "distancia_km": 2.4,
        "tecnologias": ["LTE"],
        "bandas": ["7"],
        "coordenadas": {"lat": -23.5702, "lon": -46.6604},
        "endereco": {"logradouro": "Rua Augusta, 500", "cidade": "São Paulo", "uf": "SP"},
        "estacao": {"tipo": "Estação base de celular (FB)", "infraestrutura": "Poste", "licenciamento": "2020-01-15", "validade": "2030-01-15"}
      }
    ]
  }
}
```

`tests/fixtures/resumo_municipio.json`:
```json
{
  "status": "ok",
  "dados": {
    "municipio": {"codigo_ibge": 3550308, "nome": "São Paulo", "uf": "SP"},
    "base_atualizada_em": "2026-07-25T09:14:03.000Z",
    "totais": {"estacoes": 77790, "erbs_celular": 6364, "outras_estacoes": 71426},
    "por_tecnologia": {"2G": 4102, "3G": 4890, "4G": 6201, "5G": 3944},
    "por_operadora": [
      {"operadora": "Vivo", "erbs": 2230, "tecnologias": {"2G": 1480, "3G": 1712, "4G": 2190, "5G": 1402}}
    ],
    "fonte": "Anatel (Mosaico)"
  }
}
```

`tests/fixtures/health.json`:
```json
{
  "status": "ok",
  "service": "api.redesmoveisfixas.com",
  "uptime": 86400,
  "dependencias": [
    {"nome": "cobertura", "ok": true, "atualizado_em": "2026-07-22T09:14:02.000Z", "versao": "m8k2c1x-4rfz9"},
    {"nome": "estacoes", "ok": true, "atualizado_em": "2026-07-23T11:02:47.000Z", "versao": "m8mq7ab-2p0kd"}
  ]
}
```

`tests/fixtures/monitor_ios_criado.json`:
```json
{
  "status": "ok",
  "dados": {
    "id": "3ab7f001",
    "url": "https://ha.example.com/api/webhook/abc",
    "paises": ["BR"],
    "operadoras": [],
    "incluir_beta": false,
    "secret": "whsec_test_1d90aa"
  }
}
```

`tests/fixtures/monitores_ios_lista.json`:
```json
{
  "status": "ok",
  "dados": [
    {
      "id": "3ab7f001",
      "url": "https://ha.example.com/api/webhook/abc",
      "paises": ["BR"],
      "operadoras": [],
      "incluir_beta": false,
      "ativo": true,
      "falhas_seguidas": 0,
      "ultima_entrega": "2026-07-26T04:31:07.000Z",
      "ultimo_erro": null
    }
  ]
}
```

`tests/fixtures/webhook_cidade.json`:
```json
{
  "evento": "novidades.cidade",
  "entrega_id": "c7a1beef",
  "enviado_em": "2026-07-26T11:04:12.000Z",
  "municipio": {"codigo_ibge": 3170206, "nome": "Uberlândia", "uf": "MG"},
  "total": 2,
  "erbs": [
    {"id": "1234567", "operadora": "Vivo", "nova": true, "tecnologias": ["LTE", "NR"], "tecnologias_novas": ["NR"], "coordenadas": {"lat": -18.9186, "lon": -48.2772}},
    {"id": "2222222", "operadora": "TIM", "nova": false, "tecnologias": ["LTE", "NR"], "tecnologias_novas": ["NR"], "coordenadas": {"lat": -18.92, "lon": -48.28}}
  ],
  "fonte": "Anatel (Mosaico)"
}
```

`tests/fixtures/webhook_ios.json`:
```json
{
  "evento": "novidades.ios",
  "entrega_id": "8b52cafe",
  "enviado_em": "2026-07-26T04:31:07.000Z",
  "total": 1,
  "novidades": [
    {
      "operadora": {"id": "TIM_br", "nome": "TIM", "pais": "Brasil", "pais_iso": "BR"},
      "tipo": "alterada",
      "ocorrido_em": "2026-07-26T04:18:37.000Z",
      "beta": false,
      "ios_beta_versao": null,
      "bundle": {"from": "70.0", "to": "70.1"},
      "recursos_adicionados": ["cresimtr"],
      "recursos_removidos": [],
      "rotulos_adicionados": ["eSIM Cross-Platform"],
      "rotulos_removidos": []
    }
  ],
  "fonte": "Apple (carrier bundles)"
}
```

- [ ] **Step 3: Teste de sanidade**

`tests/test_const.py`:
```python
"""Sanidade do scaffold."""

import json
from pathlib import Path

from custom_components.redes_moveis_fixas.const import DOMAIN, PLATFORMS


def test_domain():
    assert DOMAIN == "redes_moveis_fixas"
    assert "sensor" in PLATFORMS


def test_manifest_valido():
    manifest = json.loads(
        Path("custom_components/redes_moveis_fixas/manifest.json").read_text()
    )
    assert manifest["domain"] == DOMAIN
    assert manifest["dependencies"] == ["webhook"]
    assert manifest["integration_type"] == "hub"
```

- [ ] **Step 4: Criar venv, instalar deps, rodar**

Run: `cd ~/Github/ha-redes-moveis-fixas && python3 -m venv .venv && .venv/bin/pip install -q -r requirements_test.txt && .venv/bin/python -m pytest tests/test_const.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "chore: scaffold integration, fixtures and test setup"
```

---

### Task 2: Cliente da API (`api.py`)

**Files:**
- Create: `custom_components/redes_moveis_fixas/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `const.BASE_URL`; fixtures da Task 1.
- Produces (usado por coordinators, config_flow, services, webhook):
```python
class RMFError(Exception)
class RMFAuthError(RMFError)          # HTTP 403
class RMFRateLimitError(RMFError)     # HTTP 429
class RMFNotFoundError(RMFError)      # HTTP 404

class RMFClient:
    def __init__(self, session: aiohttp.ClientSession, token: str) -> None
    async def async_cobertura(self, lat: float, lon: float) -> dict          # retorna payload["dados"]
    async def async_estacoes(self, lat, lon, *, operadora=None, tecnologia=None,
                             banda=None, limite=200, offset=0) -> dict       # payload["dados"]
    async def async_resumo_municipio(self, codigo_ibge: int) -> dict         # payload["dados"]
    async def async_health(self) -> dict                                     # payload completo (sem auth)
    async def async_listar_monitores(self, tipo: str) -> list[dict]          # tipo: "cidade"|"ios"; payload["dados"]
    async def async_criar_monitor_cidade(self, url, municipios: list[str], descricao=None) -> dict  # dados c/ id+secret
    async def async_criar_monitor_ios(self, url, paises: list[str], operadoras=None, incluir_beta=False) -> dict
    async def async_remover_monitor(self, tipo: str, monitor_id: str) -> None
```

- [ ] **Step 1: Escrever testes que falham**

`tests/test_api.py`:
```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_api.py -q`
Expected: FAIL — `ImportError` de `api`

- [ ] **Step 3: Implementar `api.py`**

```python
"""Cliente HTTP puro da API RMF (sem dependência do Home Assistant)."""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import BASE_URL


class RMFError(Exception):
    """Erro genérico da API RMF."""


class RMFAuthError(RMFError):
    """Token inválido ou expirado (403)."""


class RMFRateLimitError(RMFError):
    """Cota excedida (429)."""


class RMFNotFoundError(RMFError):
    """Recurso não encontrado (404)."""


def _rota(tipo: str) -> str:
    if tipo not in ("cidade", "ios"):
        raise ValueError(f"tipo inválido: {tipo}")
    return tipo


class RMFClient:
    """Cliente assíncrono da API redesmoveisfixas.com."""

    def __init__(self, session: aiohttp.ClientSession, token: str) -> None:
        self._session = session
        self._token = token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        headers = {"Authorization": f"Bearer {self._token}"} if auth else {}
        try:
            async with self._session.request(
                method,
                f"{BASE_URL}{path}",
                params=params,
                json=json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 403:
                    raise RMFAuthError(await resp.text())
                if resp.status == 429:
                    raise RMFRateLimitError(await resp.text())
                if resp.status == 404:
                    raise RMFNotFoundError(await resp.text())
                if resp.status >= 400:
                    raise RMFError(f"HTTP {resp.status}: {await resp.text()}")
                if resp.status == 204:
                    return None
                return await resp.json()
        except aiohttp.ClientError as err:
            raise RMFError(f"Erro de conexão: {err}") from err

    @staticmethod
    def _csv(value: list[str] | None) -> str | None:
        return ",".join(value) if value else None

    async def async_cobertura(self, lat: float, lon: float) -> dict:
        payload = await self._request(
            "GET", "/api/cobertura", params={"lat": lat, "lon": lon}
        )
        return payload["dados"]

    async def async_estacoes(
        self,
        lat: float,
        lon: float,
        *,
        operadora: list[str] | None = None,
        tecnologia: list[str] | None = None,
        banda: list[str] | None = None,
        limite: int = 200,
        offset: int = 0,
    ) -> dict:
        params: dict[str, Any] = {"lat": lat, "lon": lon, "limite": limite}
        if offset:
            params["offset"] = offset
        for key, val in (
            ("operadora", self._csv(operadora)),
            ("tecnologia", self._csv(tecnologia)),
            ("banda", self._csv(banda)),
        ):
            if val:
                params[key] = val
        payload = await self._request("GET", "/api/estacoes", params=params)
        return payload["dados"]

    async def async_resumo_municipio(self, codigo_ibge: int) -> dict:
        payload = await self._request("GET", f"/api/municipios/{codigo_ibge}/resumo")
        return payload["dados"]

    async def async_health(self) -> dict:
        return await self._request("GET", "/health", auth=False)

    async def async_listar_monitores(self, tipo: str) -> list[dict]:
        payload = await self._request("GET", f"/api/monitorar-{_rota(tipo)}")
        return payload["dados"]

    async def async_criar_monitor_cidade(
        self, url: str, municipios: list[str], descricao: str | None = None
    ) -> dict:
        body: dict[str, Any] = {"url": url, "municipios": municipios}
        if descricao:
            body["descricao"] = descricao
        payload = await self._request("POST", "/api/monitorar-cidade", json=body)
        return payload["dados"]

    async def async_criar_monitor_ios(
        self,
        url: str,
        paises: list[str],
        operadoras: list[str] | None = None,
        incluir_beta: bool = False,
    ) -> dict:
        body: dict[str, Any] = {
            "url": url,
            "paises": paises,
            "incluir_beta": incluir_beta,
        }
        if operadoras:
            body["operadoras"] = operadoras
        payload = await self._request("POST", "/api/monitorar-ios", json=body)
        return payload["dados"]

    async def async_remover_monitor(self, tipo: str, monitor_id: str) -> None:
        await self._request("DELETE", f"/api/monitorar-{_rota(tipo)}/{monitor_id}")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_api.py -q`
Expected: 8 passed. Se a URL com params não casar (ordem de query), mockar com `re.compile` ou ajustar pra ordem alfabética que o aiohttp gera.

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/api.py tests/test_api.py
git commit -m "feat: RMF API client with typed errors"
```

---

### Task 3: Coordinators

**Files:**
- Create: `custom_components/redes_moveis_fixas/coordinator.py`
- Test: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `RMFClient` e exceções (Task 2).
- Produces:
```python
class RMFCoordinator(DataUpdateCoordinator[dict])            # base; traduz RMFAuthError→ConfigEntryAuthFailed, RMFError→UpdateFailed
class CoberturaCoordinator(RMFCoordinator)                   # .lat/.lon mutáveis; data = dados de /api/cobertura ({} se sem coords)
class ErbsCoordinator(RMFCoordinator)                        # .lat/.lon mutáveis; data = dados de /api/estacoes
class MunicipioCoordinator(RMFCoordinator)                   # .ibge; data = dados do /resumo
class HealthCoordinator(RMFCoordinator)                      # data = payload do /health
class MonitoresCoordinator(RMFCoordinator)                   # data = {monitor_id: {**monitor, "tipo": "cidade"|"ios"}}
```
Todos: `__init__(hass, entry, client, subentry_id_ou_None, ..., interval: timedelta)`.

- [ ] **Step 1: Teste que falha**

`tests/test_coordinator.py`:
```python
"""Testes dos coordinators."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFAuthError, RMFError
from custom_components.redes_moveis_fixas.const import DOMAIN
from custom_components.redes_moveis_fixas.coordinator import (
    CoberturaCoordinator,
    MonitoresCoordinator,
)

from .conftest import load_fixture


@pytest.fixture
def entry(hass):
    e = MockConfigEntry(domain=DOMAIN, data={"token": "tok"})
    e.add_to_hass(hass)
    return e


async def test_cobertura_ok(hass, entry):
    client = AsyncMock()
    client.async_cobertura.return_value = load_fixture("cobertura.json")["dados"]
    coord = CoberturaCoordinator(
        hass, entry, client, "sub1", -23.56, -46.65, timedelta(minutes=30)
    )
    dados = await coord._async_update_data()
    assert dados["cobertura"][0]["provedor"] == "Vivo"
    client.async_cobertura.assert_awaited_once_with(-23.56, -46.65)


async def test_cobertura_sem_coords(hass, entry):
    client = AsyncMock()
    coord = CoberturaCoordinator(
        hass, entry, client, "sub1", None, None, timedelta(minutes=30)
    )
    assert await coord._async_update_data() == {}
    client.async_cobertura.assert_not_awaited()


async def test_auth_falhou(hass, entry):
    client = AsyncMock()
    client.async_cobertura.side_effect = RMFAuthError("403")
    coord = CoberturaCoordinator(
        hass, entry, client, "sub1", 0.0, 0.0, timedelta(minutes=30)
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()


async def test_erro_generico_vira_update_failed(hass, entry):
    client = AsyncMock()
    client.async_cobertura.side_effect = RMFError("boom")
    coord = CoberturaCoordinator(
        hass, entry, client, "sub1", 0.0, 0.0, timedelta(minutes=30)
    )
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_monitores_agrega_tipos(hass, entry):
    client = AsyncMock()
    client.async_listar_monitores.side_effect = [
        [],  # cidade
        load_fixture("monitores_ios_lista.json")["dados"],  # ios
    ]
    coord = MonitoresCoordinator(hass, entry, client, timedelta(hours=6))
    dados = await coord._async_update_data()
    assert dados["3ab7f001"]["tipo"] == "ios"
    assert dados["3ab7f001"]["ativo"] is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_coordinator.py -q` — Expected: FAIL (ImportError)

- [ ] **Step 3: Implementar `coordinator.py`**

```python
"""Coordinators da integração RMF."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import RMFAuthError, RMFClient, RMFError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class RMFCoordinator(DataUpdateCoordinator[dict]):
    """Base: traduz erros da API pra exceções do HA."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: RMFClient,
        name: str,
        interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{name}",
            update_interval=interval,
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        try:
            return await self._fetch()
        except RMFAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except RMFError as err:
            raise UpdateFailed(err) from err

    async def _fetch(self) -> dict:
        raise NotImplementedError


class CoberturaCoordinator(RMFCoordinator):
    """Cobertura por operadora num ponto (lat/lon mutável pra modo pessoa)."""

    def __init__(self, hass, entry, client, subentry_id, lat, lon, interval) -> None:
        super().__init__(hass, entry, client, f"cobertura_{subentry_id}", interval)
        self.lat: float | None = lat
        self.lon: float | None = lon

    async def _fetch(self) -> dict:
        if self.lat is None or self.lon is None:
            return {}
        return await self.client.async_cobertura(self.lat, self.lon)


class ErbsCoordinator(RMFCoordinator):
    """ERBs num raio de 5 km do ponto."""

    def __init__(self, hass, entry, client, subentry_id, lat, lon, interval) -> None:
        super().__init__(hass, entry, client, f"erbs_{subentry_id}", interval)
        self.lat: float | None = lat
        self.lon: float | None = lon

    async def _fetch(self) -> dict:
        if self.lat is None or self.lon is None:
            return {}
        return await self.client.async_estacoes(self.lat, self.lon)


class MunicipioCoordinator(RMFCoordinator):
    """Resumo de estações do município."""

    def __init__(self, hass, entry, client, subentry_id, ibge, interval) -> None:
        super().__init__(hass, entry, client, f"municipio_{subentry_id}", interval)
        self.ibge: int = ibge

    async def _fetch(self) -> dict:
        return await self.client.async_resumo_municipio(self.ibge)


class HealthCoordinator(RMFCoordinator):
    """Status do serviço."""

    def __init__(self, hass, entry, client, interval) -> None:
        super().__init__(hass, entry, client, "health", interval)

    async def _fetch(self) -> dict:
        return await self.client.async_health()


class MonitoresCoordinator(RMFCoordinator):
    """Lista os monitores registrados (cidade + ios), indexados por id."""

    def __init__(self, hass, entry, client, interval) -> None:
        super().__init__(hass, entry, client, "monitores", interval)

    async def _fetch(self) -> dict:
        monitores: dict[str, dict] = {}
        for tipo in ("cidade", "ios"):
            for mon in await self.client.async_listar_monitores(tipo):
                monitores[mon["id"]] = {**mon, "tipo": tipo}
        return monitores
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_coordinator.py -q` — Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/coordinator.py tests/test_coordinator.py
git commit -m "feat: data update coordinators with error translation"
```

---

### Task 4: Webhook (verificação HMAC + dispatch)

**Files:**
- Create: `custom_components/redes_moveis_fixas/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: const (`SIGNAL_NOVIDADE`, `EVENT_NOVIDADE`, `EVENTO_CIDADE`, `EVENTO_IOS`, `CONF_MONITOR_SECRET`, `CONF_IBGE`, `TOLERANCIA_TIMESTAMP_S`, subentry types).
- Produces:
```python
def verificar_assinatura(secret: str, timestamp: str, body: bytes, assinatura: str) -> bool
async def handle_webhook(hass, webhook_id: str, request) -> web.Response
# Efeitos num POST válido: async_dispatcher_send(hass, SIGNAL_NOVIDADE.format(subentry_id), payload)
#                          hass.bus.async_fire(EVENT_NOVIDADE, {"subentry_id": ..., "entry_id": ..., "payload": payload})
```
- O registro do webhook (`webhook.async_register`) acontece na Task 7 (`__init__.py`), passando `handle_webhook`.

- [ ] **Step 1: Teste que falha**

`tests/test_webhook.py`:
```python
"""Testes do handler de webhook."""

import hashlib
import hmac
import json
import time

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from custom_components.redes_moveis_fixas.const import (
    DOMAIN,
    EVENT_NOVIDADE,
    SIGNAL_NOVIDADE,
)
from custom_components.redes_moveis_fixas.webhook import (
    handle_webhook,
    verificar_assinatura,
)

from .conftest import load_fixture

SECRET = "whsec_test_1d90aa"
WEBHOOK_ID = "wh_test_123"


class FakeRequest:
    def __init__(self, body: bytes, headers: dict):
        self._body = body
        self.headers = headers

    async def read(self) -> bytes:
        return self._body


def _assinar(body: bytes, secret: str = SECRET, ts: str | None = None):
    ts = ts or str(int(time.time()))
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256)
    return ts, f"sha256={mac.hexdigest()}"


@pytest.fixture
def entry(hass):
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": WEBHOOK_ID},
        subentries_data=[
            ConfigSubentryData(
                data={
                    "codigo_ibge": 3170206,
                    "monitorar": True,
                    "monitor_id": "9f1c0001",
                    "monitor_secret": SECRET,
                },
                subentry_type="municipio",
                title="Uberlândia (MG)",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={
                    "paises": ["BR"],
                    "operadoras": [],
                    "incluir_beta": False,
                    "monitor_id": "3ab7f001",
                    "monitor_secret": SECRET,
                },
                subentry_type="monitor_ios",
                title="Monitor iOS",
                unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    return e


async def test_assinatura_valida():
    body = b'{"x":1}'
    ts, sig = _assinar(body)
    assert verificar_assinatura(SECRET, ts, body, sig)
    assert not verificar_assinatura("outro_secret", ts, body, sig)


async def test_webhook_cidade_despacha(hass, entry):
    payload = load_fixture("webhook_cidade.json")
    body = json.dumps(payload).encode()
    ts, sig = _assinar(body)

    sub_municipio = next(
        s for s in entry.subentries.values() if s.subentry_type == "municipio"
    )
    recebidos = []
    async_dispatcher_connect(
        hass, SIGNAL_NOVIDADE.format(sub_municipio.subentry_id), recebidos.append
    )
    eventos_bus = []
    hass.bus.async_listen(EVENT_NOVIDADE, lambda e: eventos_bus.append(e))

    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": sig}),
    )
    await hass.async_block_till_done()

    assert resp.status == 200
    assert recebidos[0]["evento"] == "novidades.cidade"
    assert eventos_bus[0].data["payload"]["total"] == 2


async def test_webhook_ios_despacha(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    ts, sig = _assinar(body)

    sub_ios = next(
        s for s in entry.subentries.values() if s.subentry_type == "monitor_ios"
    )
    recebidos = []
    async_dispatcher_connect(
        hass, SIGNAL_NOVIDADE.format(sub_ios.subentry_id), recebidos.append
    )

    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": sig}),
    )
    await hass.async_block_till_done()

    assert resp.status == 200
    assert recebidos[0]["novidades"][0]["operadora"]["nome"] == "TIM"


async def test_assinatura_invalida_401(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    ts, _ = _assinar(body)
    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(
            body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": "sha256=deadbeef"}
        ),
    )
    assert resp.status == 401


async def test_timestamp_velho_401(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    ts_velho = str(int(time.time()) - 3600)
    ts, sig = _assinar(body, ts=ts_velho)
    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": sig}),
    )
    assert resp.status == 401
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_webhook.py -q` — Expected: FAIL (ImportError)

- [ ] **Step 3: Implementar `webhook.py`**

```python
"""Recepção e verificação dos webhooks da API RMF."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

from aiohttp import web

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_IBGE,
    CONF_MONITOR_SECRET,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_NOVIDADE,
    EVENTO_CIDADE,
    EVENTO_IOS,
    SIGNAL_NOVIDADE,
    SUBENTRY_MONITOR_IOS,
    SUBENTRY_MUNICIPIO,
    TOLERANCIA_TIMESTAMP_S,
)

_LOGGER = logging.getLogger(__name__)


def verificar_assinatura(
    secret: str, timestamp: str, body: bytes, assinatura: str
) -> bool:
    """HMAC-SHA256 sobre `{timestamp}.{corpo cru}` com o secret do monitor."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return hmac.compare_digest(f"sha256={mac.hexdigest()}", assinatura)


def _entry_por_webhook(hass: HomeAssistant, webhook_id: str) -> ConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_WEBHOOK_ID) == webhook_id:
            return entry
    return None


def _candidatos(entry: ConfigEntry, payload: dict) -> list[ConfigSubentry]:
    evento = payload.get("evento")
    subs = list(entry.subentries.values())
    if evento == EVENTO_CIDADE:
        ibge = payload.get("municipio", {}).get("codigo_ibge")
        return [
            s
            for s in subs
            if s.subentry_type == SUBENTRY_MUNICIPIO and s.data.get(CONF_IBGE) == ibge
        ]
    if evento == EVENTO_IOS:
        return [s for s in subs if s.subentry_type == SUBENTRY_MONITOR_IOS]
    return []


async def handle_webhook(
    hass: HomeAssistant, webhook_id: str, request
) -> web.Response:
    """Valida assinatura+timestamp e despacha pro subentry dono do monitor."""
    entry = _entry_por_webhook(hass, webhook_id)
    if entry is None:
        return web.Response(status=404)

    body = await request.read()
    timestamp = request.headers.get("X-RMF-Timestamp", "")
    assinatura = request.headers.get("X-RMF-Signature", "")

    try:
        idade = abs(time.time() - float(timestamp))
    except ValueError:
        _LOGGER.warning("Webhook RMF sem timestamp válido")
        return web.Response(status=401)
    if idade > TOLERANCIA_TIMESTAMP_S:
        _LOGGER.warning("Webhook RMF com timestamp fora da tolerância (%ss)", idade)
        return web.Response(status=401)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return web.Response(status=400)

    for subentry in _candidatos(entry, payload):
        secret = subentry.data.get(CONF_MONITOR_SECRET)
        if secret and verificar_assinatura(secret, timestamp, body, assinatura):
            async_dispatcher_send(
                hass, SIGNAL_NOVIDADE.format(subentry.subentry_id), payload
            )
            hass.bus.async_fire(
                EVENT_NOVIDADE,
                {
                    "entry_id": entry.entry_id,
                    "subentry_id": subentry.subentry_id,
                    "payload": payload,
                },
            )
            return web.Response(status=200)

    _LOGGER.warning("Webhook RMF com assinatura inválida ou sem monitor casando")
    return web.Response(status=401)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_webhook.py -q` — Expected: 5 passed
Nota: se `ConfigSubentryData`/`subentries_data` não existirem na versão instalada do `pytest-homeassistant-custom-component`, atualizar o pacote (subentries chegaram no HA 2025.3+).

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/webhook.py tests/test_webhook.py
git commit -m "feat: webhook handler with HMAC verification and dispatch"
```

---

### Task 5: Config flow — entry + reauth

**Files:**
- Create: `custom_components/redes_moveis_fixas/config_flow.py` (só entry/reauth; subentries na Task 6)
- Create: `custom_components/redes_moveis_fixas/strings.json` (mínimo pro flow)
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `RMFClient.async_listar_monitores("ios")` (valida token — 403 → `RMFAuthError`).
- Produces: `RMFConfigFlow(ConfigFlow, domain=DOMAIN)` com `async_step_user`, `async_step_reauth`, `async_step_reauth_confirm`; helper `_validar_token(hass, token)`. Task 6 adiciona `async_get_supported_subentry_types` nesta mesma classe.

- [ ] **Step 1: Teste que falha**

`tests/test_config_flow.py`:
```python
"""Testes do config flow (entry + reauth)."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFAuthError, RMFError
from custom_components.redes_moveis_fixas.const import DOMAIN


async def test_flow_cria_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "tok_abc"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Redes Móveis Fixas"
    assert result["data"] == {"token": "tok_abc"}


async def test_flow_token_invalido(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(side_effect=RMFAuthError("403")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "ruim"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_flow_sem_conexao(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(side_effect=RMFError("boom")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "tok"}
        )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_token_duplicado_aborta(hass):
    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(return_value=None),
    ):
        r1 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        r1 = await hass.config_entries.flow.async_configure(
            r1["flow_id"], {"token": "tok_igual"}
        )
        assert r1["type"] is FlowResultType.CREATE_ENTRY

        r2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        r2 = await hass.config_entries.flow.async_configure(
            r2["flow_id"], {"token": "tok_igual"}
        )
    assert r2["type"] is FlowResultType.ABORT
    assert r2["reason"] == "already_configured"


async def test_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"token": "velho"}, unique_id="uid1")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.redes_moveis_fixas.config_flow._validar_token",
        AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token": "novo"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["token"] == "novo"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_config_flow.py -q` — Expected: FAIL

- [ ] **Step 3: Implementar `config_flow.py` (parte entry)**

```python
"""Config flow da integração RMF."""

from __future__ import annotations

import hashlib
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .api import RMFAuthError, RMFClient, RMFError
from .const import CONF_TOKEN, DOMAIN

SCHEMA_TOKEN = vol.Schema({vol.Required(CONF_TOKEN): str})


async def _validar_token(hass: HomeAssistant, token: str) -> None:
    """Chamada autenticada barata; levanta RMFAuthError se o token for ruim."""
    client = RMFClient(aiohttp_client.async_get_clientsession(hass), token)
    await client.async_listar_monitores("ios")


class RMFConfigFlow(ConfigFlow, domain=DOMAIN):
    """Flow da entry hub (token)."""

    VERSION = 1

    async def _checar(self, token: str) -> dict[str, str]:
        try:
            await _validar_token(self.hass, token)
        except RMFAuthError:
            return {"base": "invalid_auth"}
        except RMFError:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._checar(user_input[CONF_TOKEN])
            if not errors:
                uid = hashlib.sha256(user_input[CONF_TOKEN].encode()).hexdigest()[:16]
                await self.async_set_unique_id(uid)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Redes Móveis Fixas", data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=SCHEMA_TOKEN, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._checar(user_input[CONF_TOKEN])
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_TOKEN: user_input[CONF_TOKEN]},
                )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=SCHEMA_TOKEN, errors=errors
        )
```

`strings.json` (base; Task 14 completa com subentries e traduções):
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Redes Móveis Fixas",
        "description": "Token da API (Bearer). Crie o seu em redesmoveisfixas.com/createapi.",
        "data": {"token": "Token"}
      },
      "reauth_confirm": {
        "title": "Token expirado",
        "description": "O token da API RMF expirou (validade de 90 dias). Informe um novo.",
        "data": {"token": "Token"}
      }
    },
    "error": {
      "invalid_auth": "Token inválido ou expirado",
      "cannot_connect": "Falha ao conectar na API"
    },
    "abort": {
      "already_configured": "Este token já está configurado",
      "reauth_successful": "Token atualizado"
    }
  }
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_config_flow.py -q` — Expected: 5 passed
Nota: reauth precisa da entry com `unique_id`; `start_reauth_flow` vem do `pytest_homeassistant_custom_component.common.MockConfigEntry`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/config_flow.py custom_components/redes_moveis_fixas/strings.json tests/test_config_flow.py
git commit -m "feat: config flow with token validation and reauth"
```

---

### Task 6: Subentry flows (Local, Município, Monitor iOS)

**Files:**
- Modify: `custom_components/redes_moveis_fixas/config_flow.py` (adicionar as 3 classes + `async_get_supported_subentry_types` no fim da classe `RMFConfigFlow`)
- Test: `tests/test_subentry_flows.py`

**Interfaces:**
- Consumes: `RMFClient.async_resumo_municipio` (validação do IBGE), consts das subentries.
- Produces: subentries com `subentry_type` ∈ {`local`, `municipio`, `monitor_ios`} e `data`:
  - local: `{modo, entity_id, intervalo_cobertura, intervalo_erbs, max_geo}`
  - municipio: `{codigo_ibge: int, monitorar: bool, intervalo_municipio}` (+ `monitor_id`/`monitor_secret` gravados depois pela Task 7)
  - monitor_ios: `{paises: list[str], operadoras: list[str], incluir_beta: bool}` (+ `monitor_id`/`monitor_secret` via Task 7)

- [ ] **Step 1: Teste que falha**

`tests/test_subentry_flows.py`:
```python
"""Testes dos subentry flows."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.api import RMFNotFoundError
from custom_components.redes_moveis_fixas.const import DOMAIN

from .conftest import load_fixture


@pytest.fixture
async def entry(hass):
    e = MockConfigEntry(
        domain=DOMAIN, data={"token": "tok"}, unique_id="uid1", state=config_entries.ConfigEntryState.LOADED
    )
    e.add_to_hass(hass)
    return e


async def test_subentry_local_zona(hass, entry):
    hass.states.async_set(
        "zone.home", "0", {"latitude": -5.8, "longitude": -35.2, "friendly_name": "Casa"}
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "local"), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"modo": "zona"}
    )
    assert result["step_id"] == "alvo"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "entity_id": "zone.home",
            "intervalo_cobertura": 30,
            "intervalo_erbs": 6,
            "max_geo": 25,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = list(entry.subentries.values())[0]
    assert sub.subentry_type == "local"
    assert sub.data["modo"] == "zona"
    assert sub.data["entity_id"] == "zone.home"


async def test_subentry_municipio_valida_ibge(hass, entry):
    with patch(
        "custom_components.redes_moveis_fixas.config_flow.RMFClient"
    ) as client_cls:
        client_cls.return_value.async_resumo_municipio = AsyncMock(
            return_value=load_fixture("resumo_municipio.json")["dados"]
        )
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "municipio"),
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"codigo_ibge": "3550308", "monitorar": True, "intervalo_municipio": 12},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = list(entry.subentries.values())[0]
    assert sub.title == "São Paulo (SP)"
    assert sub.data["codigo_ibge"] == 3550308


async def test_subentry_municipio_ibge_invalido(hass, entry):
    with patch(
        "custom_components.redes_moveis_fixas.config_flow.RMFClient"
    ) as client_cls:
        client_cls.return_value.async_resumo_municipio = AsyncMock(
            side_effect=RMFNotFoundError("404")
        )
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "municipio"),
            context={"source": config_entries.SOURCE_USER},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"codigo_ibge": "9999999", "monitorar": False, "intervalo_municipio": 12},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "ibge_invalido"}


async def test_subentry_monitor_ios(hass, entry):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "monitor_ios"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"paises": "br, pt", "operadoras": "vivo, tim", "incluir_beta": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = list(entry.subentries.values())[0]
    assert sub.data["paises"] == ["BR", "PT"]
    assert sub.data["operadoras"] == ["vivo", "tim"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_subentry_flows.py -q` — Expected: FAIL

- [ ] **Step 3: Adicionar ao `config_flow.py`**

Imports extras no topo:
```python
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import RMFAuthError, RMFClient, RMFError, RMFNotFoundError
from .const import (
    CONF_ENTITY_ID,
    CONF_IBGE,
    CONF_INCLUIR_BETA,
    CONF_INTERVALO_COBERTURA,
    CONF_INTERVALO_ERBS,
    CONF_INTERVALO_MUNICIPIO,
    CONF_MAX_GEO,
    CONF_MODO,
    CONF_MONITORAR,
    CONF_OPERADORAS,
    CONF_PAISES,
    CONF_TOKEN,
    DEFAULT_INTERVALO_COBERTURA_MIN,
    DEFAULT_INTERVALO_ERBS_H,
    DEFAULT_INTERVALO_MUNICIPIO_H,
    DEFAULT_MAX_GEO,
    DOMAIN,
    SUBENTRY_LOCAL,
    SUBENTRY_MONITOR_IOS,
    SUBENTRY_MUNICIPIO,
)
```

Dentro de `RMFConfigFlow`, no fim:
```python
    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return {
            SUBENTRY_LOCAL: LocalSubentryFlow,
            SUBENTRY_MUNICIPIO: MunicipioSubentryFlow,
            SUBENTRY_MONITOR_IOS: MonitorIosSubentryFlow,
        }
```

Classes novas (fim do arquivo):
```python
class LocalSubentryFlow(ConfigSubentryFlow):
    """Adiciona um local (zona ou pessoa)."""

    _modo: str

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        if user_input is not None:
            self._modo = user_input[CONF_MODO]
            return await self.async_step_alvo()
        schema = vol.Schema(
            {
                vol.Required(CONF_MODO, default="zona"): SelectSelector(
                    SelectSelectorConfig(
                        options=["zona", "pessoa"],
                        mode=SelectSelectorMode.LIST,
                        translation_key="modo",
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_alvo(self, user_input=None) -> SubentryFlowResult:
        if user_input is not None:
            state = self.hass.states.get(user_input[CONF_ENTITY_ID])
            titulo = (
                state.attributes.get("friendly_name", user_input[CONF_ENTITY_ID])
                if state
                else user_input[CONF_ENTITY_ID]
            )
            return self.async_create_entry(
                title=titulo, data={CONF_MODO: self._modo, **user_input}
            )
        dominio = "zone" if self._modo == "zona" else "person"
        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): EntitySelector(
                    EntitySelectorConfig(domain=dominio)
                ),
                vol.Required(
                    CONF_INTERVALO_COBERTURA, default=DEFAULT_INTERVALO_COBERTURA_MIN
                ): NumberSelector(
                    NumberSelectorConfig(min=5, max=1440, mode="box", unit_of_measurement="min")
                ),
                vol.Required(
                    CONF_INTERVALO_ERBS, default=DEFAULT_INTERVALO_ERBS_H
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=168, mode="box", unit_of_measurement="h")
                ),
                vol.Required(CONF_MAX_GEO, default=DEFAULT_MAX_GEO): NumberSelector(
                    NumberSelectorConfig(min=0, max=100, mode="box")
                ),
            }
        )
        return self.async_show_form(step_id="alvo", data_schema=schema)


class MunicipioSubentryFlow(ConfigSubentryFlow):
    """Adiciona um município por código IBGE."""

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_entry()
            client = RMFClient(
                aiohttp_client.async_get_clientsession(self.hass),
                entry.data[CONF_TOKEN],
            )
            try:
                dados = await client.async_resumo_municipio(int(user_input[CONF_IBGE]))
            except (RMFNotFoundError, ValueError):
                errors["base"] = "ibge_invalido"
            except RMFError:
                errors["base"] = "cannot_connect"
            else:
                mun = dados["municipio"]
                return self.async_create_entry(
                    title=f"{mun['nome']} ({mun['uf']})",
                    data={
                        CONF_IBGE: int(user_input[CONF_IBGE]),
                        CONF_MONITORAR: user_input[CONF_MONITORAR],
                        CONF_INTERVALO_MUNICIPIO: user_input[CONF_INTERVALO_MUNICIPIO],
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_IBGE): str,
                vol.Required(CONF_MONITORAR, default=True): BooleanSelector(),
                vol.Required(
                    CONF_INTERVALO_MUNICIPIO, default=DEFAULT_INTERVALO_MUNICIPIO_H
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=168, mode="box", unit_of_measurement="h")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class MonitorIosSubentryFlow(ConfigSubentryFlow):
    """Adiciona um monitor de carrier bundles do iOS."""

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        if user_input is not None:
            paises = [
                p.strip().upper()
                for p in user_input[CONF_PAISES].split(",")
                if p.strip()
            ]
            operadoras = [
                o.strip()
                for o in user_input.get(CONF_OPERADORAS, "").split(",")
                if o.strip()
            ]
            return self.async_create_entry(
                title="Monitor iOS",
                data={
                    CONF_PAISES: paises,
                    CONF_OPERADORAS: operadoras,
                    CONF_INCLUIR_BETA: user_input[CONF_INCLUIR_BETA],
                },
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_PAISES, default="BR"): str,
                vol.Optional(CONF_OPERADORAS, default=""): str,
                vol.Required(CONF_INCLUIR_BETA, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_subentry_flows.py tests/test_config_flow.py -q` — Expected: 9 passed
Nota: se `hass.config_entries.subentries.async_init` exigir a entry LOADED, manter o `state=...LOADED` do fixture.

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/config_flow.py tests/test_subentry_flows.py
git commit -m "feat: subentry flows for local, municipality and iOS monitor"
```

---

### Task 7: `__init__.py` (setup, webhook, monitores, person-follow) + `entity.py`

**Files:**
- Modify: `custom_components/redes_moveis_fixas/__init__.py` (substituir stub)
- Create: `custom_components/redes_moveis_fixas/entity.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: Tasks 2–4 (client, coordinators, `handle_webhook`).
- Produces (usado por todas as platforms):
```python
@dataclass
class RMFRuntime:
    client: RMFClient
    health: HealthCoordinator
    monitores: MonitoresCoordinator
    cobertura: dict[str, CoberturaCoordinator]    # subentry_id -> coordinator
    erbs: dict[str, ErbsCoordinator]
    municipio: dict[str, MunicipioCoordinator]

# entry.runtime_data = RMFRuntime(...)
# entity.py:
class RMFEntity(CoordinatorEntity):               # device por subentry
    def __init__(self, coordinator, subentry, chave: str, nome: str)  # unique_id = f"{subentry.subentry_id}_{chave}"
class RMFEntryEntity(CoordinatorEntity):          # device da entry ("API RMF")
    def __init__(self, coordinator, entry, chave: str, nome: str)
```
- Regra de naming: `_attr_has_entity_name = False` e `_attr_name = nome` completo em PT-BR (ex. "Cobertura da Vivo em Casa") — o HA gera `entity_id` no padrão `sensor.cobertura_da_vivo_em_casa` (padrão de nomenclatura do usuário).

- [ ] **Step 1: Teste que falha**

`tests/test_init.py`:
```python
"""Testes de setup/unload da entry."""

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
    client.async_resumo_municipio.return_value = load_fixture(
        "resumo_municipio.json"
    )["dados"]
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
                data={"codigo_ibge": 3550308, "monitorar": True, "intervalo_municipio": 12},
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
    hass.states.async_set(
        "zone.home", "0", {"latitude": -5.8, "longitude": -35.2}
    )
    client = _mock_client()
    with (
        patch(
            "custom_components.redes_moveis_fixas.RMFClient", return_value=client
        ),
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
    assert len(rt.municipio) == 1
    # coordenadas da zona chegaram no coordinator
    coord = list(rt.cobertura.values())[0]
    assert coord.lat == -5.8

    # monitores provisionados: secret gravado na subentry
    subs = {s.subentry_type: s for s in entry.subentries.values()}
    assert subs["monitor_ios"].data["monitor_secret"] == "whsec_test_1d90aa"
    assert subs["municipio"].data["monitor_id"] == "9f1c0001"
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_init.py -q` — Expected: FAIL

- [ ] **Step 3: Implementar `__init__.py`**

```python
"""Integração Redes Móveis Fixas."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.components.webhook import (
    async_generate_url as webhook_async_generate_url,
    async_register as webhook_async_register,
    async_unregister as webhook_async_unregister,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .api import RMFClient, RMFError
from .const import (
    CONF_ENTITY_ID,
    CONF_IBGE,
    CONF_INCLUIR_BETA,
    CONF_INTERVALO_COBERTURA,
    CONF_INTERVALO_ERBS,
    CONF_INTERVALO_MUNICIPIO,
    CONF_MODO,
    CONF_MONITOR_ID,
    CONF_MONITOR_SECRET,
    CONF_MONITORAR,
    CONF_OPERADORAS,
    CONF_PAISES,
    CONF_TOKEN,
    CONF_WEBHOOK_ID,
    DEFAULT_INTERVALO_COBERTURA_MIN,
    DEFAULT_INTERVALO_ERBS_H,
    DEFAULT_INTERVALO_MUNICIPIO_H,
    DISTANCIA_MINIMA_M,
    DOMAIN,
    INTERVALO_HEALTH,
    INTERVALO_MINIMO_PESSOA,
    INTERVALO_MONITORES,
    PLATFORMS,
    SUBENTRY_LOCAL,
    SUBENTRY_MONITOR_IOS,
    SUBENTRY_MUNICIPIO,
)
from .coordinator import (
    CoberturaCoordinator,
    ErbsCoordinator,
    HealthCoordinator,
    MonitoresCoordinator,
    MunicipioCoordinator,
)
from .webhook import handle_webhook

_LOGGER = logging.getLogger(__name__)


@dataclass
class RMFRuntime:
    """Estado de runtime da entry."""

    client: RMFClient
    health: HealthCoordinator
    monitores: MonitoresCoordinator
    cobertura: dict[str, CoberturaCoordinator] = field(default_factory=dict)
    erbs: dict[str, ErbsCoordinator] = field(default_factory=dict)
    municipio: dict[str, MunicipioCoordinator] = field(default_factory=dict)


def _coords_do_estado(hass: HomeAssistant, entity_id: str):
    state = hass.states.get(entity_id)
    if state is None:
        return None, None
    lat = state.attributes.get("latitude")
    lon = state.attributes.get("longitude")
    if lat is None or lon is None:
        return None, None
    return float(lat), float(lon)


async def _provisionar_monitor(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
    client: RMFClient,
    url: str,
) -> None:
    """Cria o monitor na API se a subentry ainda não tem um."""
    if subentry.data.get(CONF_MONITOR_ID):
        return
    if subentry.subentry_type == SUBENTRY_MUNICIPIO:
        dados = await client.async_criar_monitor_cidade(
            url, [str(subentry.data[CONF_IBGE])], descricao=subentry.title
        )
    else:
        dados = await client.async_criar_monitor_ios(
            url,
            subentry.data[CONF_PAISES],
            operadoras=subentry.data.get(CONF_OPERADORAS) or None,
            incluir_beta=subentry.data.get(CONF_INCLUIR_BETA, False),
        )
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data={
            **subentry.data,
            CONF_MONITOR_ID: dados["id"],
            CONF_MONITOR_SECRET: dados["secret"],
        },
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura a entry hub."""
    client = RMFClient(
        aiohttp_client.async_get_clientsession(hass), entry.data[CONF_TOKEN]
    )

    # Webhook: id estável guardado na entry
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if not webhook_id:
        webhook_id = secrets.token_hex(16)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_WEBHOOK_ID: webhook_id}
        )
    webhook_async_register(
        hass, DOMAIN, "Redes Móveis Fixas", webhook_id, handle_webhook
    )
    entry.async_on_unload(lambda: webhook_async_unregister(hass, webhook_id))

    health = HealthCoordinator(hass, entry, client, INTERVALO_HEALTH)
    monitores = MonitoresCoordinator(hass, entry, client, INTERVALO_MONITORES)
    await health.async_config_entry_first_refresh()
    await monitores.async_config_entry_first_refresh()

    rt = RMFRuntime(client=client, health=health, monitores=monitores)
    entry.runtime_data = rt

    # URL pública pros monitores (exige external_url/cloud configurado)
    try:
        url_webhook = webhook_async_generate_url(hass, webhook_id)
    except Exception as err:  # NoURLAvailableError
        raise ConfigEntryNotReady(f"Sem URL externa pro webhook: {err}") from err

    for subentry in entry.subentries.values():
        sid = subentry.subentry_id
        if subentry.subentry_type == SUBENTRY_LOCAL:
            lat, lon = _coords_do_estado(hass, subentry.data[CONF_ENTITY_ID])
            rt.cobertura[sid] = CoberturaCoordinator(
                hass, entry, client, sid, lat, lon,
                timedelta(minutes=subentry.data.get(
                    CONF_INTERVALO_COBERTURA, DEFAULT_INTERVALO_COBERTURA_MIN
                )),
            )
            rt.erbs[sid] = ErbsCoordinator(
                hass, entry, client, sid, lat, lon,
                timedelta(hours=subentry.data.get(
                    CONF_INTERVALO_ERBS, DEFAULT_INTERVALO_ERBS_H
                )),
            )
            await rt.cobertura[sid].async_config_entry_first_refresh()
            await rt.erbs[sid].async_config_entry_first_refresh()
            if subentry.data[CONF_MODO] == "pessoa":
                _seguir_pessoa(hass, entry, subentry, rt)
        elif subentry.subentry_type == SUBENTRY_MUNICIPIO:
            rt.municipio[sid] = MunicipioCoordinator(
                hass, entry, client, sid, subentry.data[CONF_IBGE],
                timedelta(hours=subentry.data.get(
                    CONF_INTERVALO_MUNICIPIO, DEFAULT_INTERVALO_MUNICIPIO_H
                )),
            )
            await rt.municipio[sid].async_config_entry_first_refresh()
            if subentry.data.get(CONF_MONITORAR):
                await _provisionar_monitor(hass, entry, subentry, client, url_webhook)
        elif subentry.subentry_type == SUBENTRY_MONITOR_IOS:
            await _provisionar_monitor(hass, entry, subentry, client, url_webhook)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


@callback
def _seguir_pessoa(
    hass: HomeAssistant, entry: ConfigEntry, subentry: ConfigSubentry, rt: RMFRuntime
) -> None:
    """Atualiza coords quando a pessoa se move (>500 m e >=10 min)."""
    sid = subentry.subentry_id
    ultima: dict[str, datetime | None] = {"em": None}

    async def _mudou(event: Event) -> None:
        novo = event.data.get("new_state")
        if novo is None:
            return
        lat = novo.attributes.get("latitude")
        lon = novo.attributes.get("longitude")
        coord = rt.cobertura[sid]
        if lat is None or lon is None:
            return
        agora = dt_util.utcnow()
        if ultima["em"] and agora - ultima["em"] < INTERVALO_MINIMO_PESSOA:
            return
        if coord.lat is not None:
            dist = distance(coord.lat, coord.lon, float(lat), float(lon))
            if dist is not None and dist < DISTANCIA_MINIMA_M:
                return
        ultima["em"] = agora
        for c in (rt.cobertura[sid], rt.erbs[sid]):
            c.lat, c.lon = float(lat), float(lon)
            await c.async_request_refresh()

    entry.async_on_unload(
        async_track_state_change_event(
            hass, [subentry.data[CONF_ENTITY_ID]], _mudou
        )
    )


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Entry removida: apaga os monitores na API (melhor esforço)."""
    client = RMFClient(
        aiohttp_client.async_get_clientsession(hass), entry.data[CONF_TOKEN]
    )
    for subentry in entry.subentries.values():
        monitor_id = subentry.data.get(CONF_MONITOR_ID)
        if not monitor_id:
            continue
        tipo = "cidade" if subentry.subentry_type == SUBENTRY_MUNICIPIO else "ios"
        try:
            await client.async_remover_monitor(tipo, monitor_id)
        except RMFError as err:
            _LOGGER.warning("Falha ao remover monitor %s: %s", monitor_id, err)
```

Nota de projeto: remoção de **subentry** individual não tem hook próprio no HA — a limpeza acontece por varredura de órfãos na Task 13 (repairs) e na remoção da entry acima.

`entity.py`:
```python
"""Entidades base."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RMFCoordinator


class RMFEntity(CoordinatorEntity[RMFCoordinator]):
    """Base: um device por subentry, nome completo em PT-BR."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: RMFCoordinator,
        subentry: ConfigSubentry,
        chave: str,
        nome: str,
    ) -> None:
        super().__init__(coordinator)
        self._subentry = subentry
        self._attr_unique_id = f"{subentry.subentry_id}_{chave}"
        self._attr_name = nome
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Redes Móveis Fixas",
            entry_type=DeviceEntryType.SERVICE,
        )


class RMFEntryEntity(CoordinatorEntity[RMFCoordinator]):
    """Base: device da própria entry ("API RMF")."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: RMFCoordinator,
        entry: ConfigEntry,
        chave: str,
        nome: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{chave}"
        self._attr_name = nome
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="API RMF",
            manufacturer="Redes Móveis Fixas",
            entry_type=DeviceEntryType.SERVICE,
        )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_init.py -q` — Expected: 2 passed
Notas: os platforms ainda não existem (Task 8+) — criar 4 arquivos stub com `async_setup_entry` vazio pra `PLATFORMS` carregar:
```python
async def async_setup_entry(hass, entry, async_add_entities):  # stub Task N
    pass
```
em `sensor.py`, `binary_sensor.py`, `event.py`, `geo_location.py`. Cada task seguinte substitui o seu. `async_add_entities` nos platforms recebe `config_subentry_id` — ver Task 8.

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/ tests/test_init.py
git commit -m "feat: entry setup with webhook registration, monitor provisioning and person tracking"
```

---

### Task 8: `sensor.py`

**Files:**
- Modify: `custom_components/redes_moveis_fixas/sensor.py` (substituir stub)
- Test: `tests/test_sensor.py`

**Interfaces:**
- Consumes: `RMFRuntime` (`entry.runtime_data`), `RMFEntity`/`RMFEntryEntity`, coordinators.
- Produces: sensores por device conforme spec. Naming: `nome` completo PT-BR (ex.: `f"Cobertura da {provedor} em {subentry.title}"`).

- [ ] **Step 1: Teste que falha**

`tests/test_sensor.py` (usa o mesmo fixture `entry` + `_mock_client` de `test_init.py` — extrair ambos pro `conftest.py` neste passo e importar nos dois testes):
```python
"""Testes dos sensores."""

from unittest.mock import patch

from .conftest import entry_completa, mock_client  # fixtures movidas pro conftest


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
```

No `conftest.py`, adicionar (movendo de `test_init.py`, que passa a importar daqui):
```python
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigSubentryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.redes_moveis_fixas.const import DOMAIN


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.async_health.return_value = load_fixture("health.json")
    client.async_listar_monitores.return_value = []
    client.async_cobertura.return_value = load_fixture("cobertura.json")["dados"]
    client.async_estacoes.return_value = load_fixture("estacoes.json")["dados"]
    client.async_resumo_municipio.return_value = load_fixture("resumo_municipio.json")["dados"]
    client.async_criar_monitor_ios.return_value = load_fixture("monitor_ios_criado.json")["dados"]
    client.async_criar_monitor_cidade.return_value = {"id": "9f1c0001", "secret": "whsec_cidade_aa"}
    return client


@pytest.fixture
def entry_completa(hass):
    e = MockConfigEntry(
        domain=DOMAIN,
        data={"token": "tok", "webhook_id": "wh_fixo"},
        unique_id="uid1",
        subentries_data=[
            ConfigSubentryData(
                data={"modo": "zona", "entity_id": "zone.home", "intervalo_cobertura": 30, "intervalo_erbs": 6, "max_geo": 25},
                subentry_type="local", title="Casa", unique_id=None,
            ),
            ConfigSubentryData(
                data={"codigo_ibge": 3550308, "monitorar": True, "intervalo_municipio": 12},
                subentry_type="municipio", title="São Paulo (SP)", unique_id=None,
            ),
            ConfigSubentryData(
                data={"paises": ["BR"], "operadoras": [], "incluir_beta": False},
                subentry_type="monitor_ios", title="Monitor iOS", unique_id=None,
            ),
        ],
    )
    e.add_to_hass(hass)
    return e
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_sensor.py -q` — Expected: FAIL (stub não cria entities)

- [ ] **Step 3: Implementar `sensor.py`**

```python
"""Sensores da integração RMF."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import SUBENTRY_LOCAL, SUBENTRY_MONITOR_IOS, SUBENTRY_MUNICIPIO
from .entity import RMFEntity, RMFEntryEntity

TECNOLOGIAS = ("2G", "3G", "4G", "5G")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    rt = entry.runtime_data

    # Device da entry
    async_add_entities(
        [
            BaseAtualizadaEntrySensor(rt.health, entry, dep)
            for dep in ("cobertura", "estacoes")
        ]
    )

    for subentry in entry.subentries.values():
        sid = subentry.subentry_id
        entities: list[SensorEntity] = []
        if subentry.subentry_type == SUBENTRY_LOCAL:
            cob = rt.cobertura[sid]
            provedores = [
                c["provedor"] for c in (cob.data or {}).get("cobertura", [])
            ]
            entities += [
                CoberturaOperadoraSensor(cob, subentry, p) for p in provedores
            ]
            entities.append(MelhorCoberturaSensor(cob, subentry))
            entities.append(ErbsPorPertoSensor(rt.erbs[sid], subentry))
            entities.append(DistanciaErbSensor(rt.erbs[sid], subentry))
        elif subentry.subentry_type == SUBENTRY_MUNICIPIO:
            mun = rt.municipio[sid]
            entities.append(TotalSensor(mun, subentry, "erbs_celular", "ERBs"))
            entities.append(TotalSensor(mun, subentry, "estacoes", "Estações"))
            entities += [
                ErbsTecnologiaSensor(mun, subentry, tec) for tec in TECNOLOGIAS
            ]
            entities.append(BaseMunicipioSensor(mun, subentry))
        elif subentry.subentry_type == SUBENTRY_MONITOR_IOS:
            entities.append(UltimaNovidadeIosSensor(rt.monitores, subentry))
        if entities:
            async_add_entities(entities, config_subentry_id=sid)


class BaseAtualizadaEntrySensor(RMFEntryEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry, dependencia: str) -> None:
        super().__init__(
            coordinator,
            entry,
            f"base_{dependencia}",
            f"Base de {dependencia.capitalize()} atualizada em",
        )
        self._dependencia = dependencia

    @property
    def native_value(self):
        for dep in (self.coordinator.data or {}).get("dependencias", []):
            if dep["nome"] == self._dependencia and dep.get("atualizado_em"):
                return dt_util.parse_datetime(dep["atualizado_em"])
        return None


class CoberturaOperadoraSensor(RMFEntity, SensorEntity):
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, subentry, provedor: str) -> None:
        super().__init__(
            coordinator,
            subentry,
            f"cobertura_{provedor.lower()}",
            f"Cobertura da {provedor} em {subentry.title}",
        )
        self._provedor = provedor

    def _item(self) -> dict | None:
        for c in (self.coordinator.data or {}).get("cobertura", []):
            if c["provedor"] == self._provedor:
                return c
        return None

    @property
    def native_value(self):
        item = self._item()
        return item["qualidade_global"]["score_percentual"] if item else None

    @property
    def extra_state_attributes(self):
        item = self._item()
        if not item:
            return {}
        attrs = {"classificacao": item["qualidade_global"]["classificacao"]}
        for tec in item.get("tecnologias_suportadas", []):
            attrs[tec["rede"]] = tec["forca_sinal"]
        return attrs


class MelhorCoberturaSensor(RMFEntity, SensorEntity):
    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator, subentry, "melhor", f"Melhor cobertura em {subentry.title}"
        )

    @property
    def native_value(self):
        itens = (self.coordinator.data or {}).get("cobertura", [])
        if not itens:
            return None
        melhor = max(itens, key=lambda c: c["qualidade_global"]["score_percentual"])
        return melhor["provedor"]


class ErbsPorPertoSensor(RMFEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator, subentry, "erbs_total", f"ERBs por perto de {subentry.title}"
        )

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("total_erbs")

    @property
    def extra_state_attributes(self):
        erbs = (self.coordinator.data or {}).get("erbs", [])
        por_op: dict[str, int] = {}
        por_tec: dict[str, int] = {}
        for erb in erbs:
            por_op[erb["operadora"]] = por_op.get(erb["operadora"], 0) + 1
            for tec in erb.get("tecnologias", []):
                por_tec[tec] = por_tec.get(tec, 0) + 1
        return {"por_operadora": por_op, "por_tecnologia": por_tec}


class DistanciaErbSensor(RMFEntity, SensorEntity):
    _attr_native_unit_of_measurement = "km"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator,
            subentry,
            "erb_proxima",
            f"Distância da ERB mais próxima de {subentry.title}",
        )

    def _mais_proxima(self) -> dict | None:
        erbs = (self.coordinator.data or {}).get("erbs", [])
        return min(erbs, key=lambda e: e["distancia_km"]) if erbs else None

    @property
    def native_value(self):
        erb = self._mais_proxima()
        return erb["distancia_km"] if erb else None

    @property
    def extra_state_attributes(self):
        erb = self._mais_proxima()
        if not erb:
            return {}
        return {
            "operadora": erb["operadora"],
            "endereco": erb.get("endereco"),
            "tecnologias": erb.get("tecnologias"),
            "bandas": erb.get("bandas"),
        }


class TotalSensor(RMFEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, subentry, campo: str, rotulo: str) -> None:
        super().__init__(
            coordinator, subentry, campo, f"{rotulo} em {subentry.title}"
        )
        self._campo = campo

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("totais", {}).get(self._campo)


class ErbsTecnologiaSensor(RMFEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, subentry, tec: str) -> None:
        super().__init__(
            coordinator,
            subentry,
            f"erbs_{tec.lower()}",
            f"ERBs {tec} em {subentry.title}",
        )
        self._tec = tec

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("por_tecnologia", {}).get(self._tec)

    @property
    def extra_state_attributes(self):
        por_op = {}
        for op in (self.coordinator.data or {}).get("por_operadora", []):
            por_op[op["operadora"]] = op.get("tecnologias", {}).get(self._tec)
        return {"por_operadora": por_op}


class BaseMunicipioSensor(RMFEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator,
            subentry,
            "base_atualizada",
            f"Base de {subentry.title} atualizada em",
        )

    @property
    def native_value(self):
        valor = (self.coordinator.data or {}).get("base_atualizada_em")
        return dt_util.parse_datetime(valor) if valor else None


class UltimaNovidadeIosSensor(RMFEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator, subentry, "ultima_novidade", "Última novidade do iOS"
        )
        self._monitor_id = subentry.data.get("monitor_id")

    @property
    def native_value(self):
        mon = (self.coordinator.data or {}).get(self._monitor_id)
        if mon and mon.get("ultima_entrega"):
            return dt_util.parse_datetime(mon["ultima_entrega"])
        return None
```

Limitação registrada: sensores de cobertura por operadora são criados no setup a partir do primeiro refresh — operadora nova só aparece após reload da entry (documentar no README, Task 14).

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_sensor.py tests/test_init.py -q` — Expected: todos passam (entity_ids gerados do nome: conferir slugs com acento — "São Paulo (SP)" vira `sao_paulo_sp`).

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/sensor.py tests/ && git commit -m "feat: sensor platform for coverage, stations and municipality"
```

---

### Task 9: `binary_sensor.py`

**Files:**
- Modify: `custom_components/redes_moveis_fixas/binary_sensor.py` (substituir stub)
- Test: `tests/test_binary_sensor.py`

**Interfaces:**
- Consumes: `RMFRuntime`, `RMFEntity`/`RMFEntryEntity`, `CONF_MONITOR_ID`.
- Produces: `binary_sensor.status_da_api_rmf` (connectivity), `binary_sensor.5g_disponivel_em_<local>`, `binary_sensor.monitor_de_<municipio>_ativo`, `binary_sensor.monitor_ios_ativo`.

- [ ] **Step 1: Teste que falha**

`tests/test_binary_sensor.py`:
```python
"""Testes dos binary sensors."""

from unittest.mock import patch

from .conftest import entry_completa, mock_client
from .test_sensor import _setup


async def test_binary_sensors(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    mock_client.async_listar_monitores.side_effect = None
    mock_client.async_listar_monitores.return_value = []
    await _setup(hass, entry_completa, mock_client)

    assert hass.states.get("binary_sensor.status_da_api_rmf").state == "on"
    assert hass.states.get("binary_sensor.5g_disponivel_em_casa").state == "on"
    # monitor recém-criado ainda não aparece na listagem mockada (vazia) → off
    assert hass.states.get("binary_sensor.monitor_ios_ativo").state == "off"


async def test_monitor_ativo_quando_listado(hass, entry_completa, mock_client):
    from .conftest import load_fixture

    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    def _listar(tipo):
        if tipo == "ios":
            return load_fixture("monitores_ios_lista.json")["dados"]
        return []

    mock_client.async_listar_monitores.side_effect = _listar
    await _setup(hass, entry_completa, mock_client)

    estado = hass.states.get("binary_sensor.monitor_ios_ativo")
    assert estado.state == "on"
    assert estado.attributes["falhas_seguidas"] == 0
```

- [ ] **Step 2: Rodar e ver falhar** — `.venv/bin/python -m pytest tests/test_binary_sensor.py -q`

- [ ] **Step 3: Implementar `binary_sensor.py`**

```python
"""Binary sensors da integração RMF."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MONITOR_ID,
    SUBENTRY_LOCAL,
    SUBENTRY_MONITOR_IOS,
    SUBENTRY_MUNICIPIO,
)
from .entity import RMFEntity, RMFEntryEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    rt = entry.runtime_data
    async_add_entities([StatusApiBinarySensor(rt.health, entry)])

    for subentry in entry.subentries.values():
        sid = subentry.subentry_id
        entities: list[BinarySensorEntity] = []
        if subentry.subentry_type == SUBENTRY_LOCAL:
            entities.append(Disponivel5GBinarySensor(rt.cobertura[sid], subentry))
        elif subentry.subentry_type == SUBENTRY_MUNICIPIO and subentry.data.get(
            CONF_MONITOR_ID
        ):
            entities.append(
                MonitorAtivoBinarySensor(
                    rt.monitores, subentry, f"Monitor de {subentry.title} ativo"
                )
            )
        elif subentry.subentry_type == SUBENTRY_MONITOR_IOS:
            entities.append(
                MonitorAtivoBinarySensor(rt.monitores, subentry, "Monitor iOS ativo")
            )
        if entities:
            async_add_entities(entities, config_subentry_id=sid)


class StatusApiBinarySensor(RMFEntryEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "status", "Status da API RMF")

    @property
    def is_on(self) -> bool:
        return (
            self.coordinator.last_update_success
            and (self.coordinator.data or {}).get("status") == "ok"
        )


class Disponivel5GBinarySensor(RMFEntity, BinarySensorEntity):
    def __init__(self, coordinator, subentry) -> None:
        super().__init__(
            coordinator, subentry, "5g", f"5G disponível em {subentry.title}"
        )

    @property
    def is_on(self) -> bool:
        for cob in (self.coordinator.data or {}).get("cobertura", []):
            for tec in cob.get("tecnologias_suportadas", []):
                if tec["rede"] == "5G":
                    return True
        return False


class MonitorAtivoBinarySensor(RMFEntity, BinarySensorEntity):
    def __init__(self, coordinator, subentry, nome: str) -> None:
        super().__init__(coordinator, subentry, "monitor_ativo", nome)
        self._monitor_id = subentry.data.get(CONF_MONITOR_ID)

    def _monitor(self) -> dict | None:
        return (self.coordinator.data or {}).get(self._monitor_id)

    @property
    def is_on(self) -> bool:
        mon = self._monitor()
        return bool(mon and mon.get("ativo"))

    @property
    def extra_state_attributes(self):
        mon = self._monitor() or {}
        return {
            "falhas_seguidas": mon.get("falhas_seguidas"),
            "ultima_entrega": mon.get("ultima_entrega"),
            "ultimo_erro": mon.get("ultimo_erro"),
        }
```

Nota: o binary_sensor do monitor iOS existe mesmo sem `monitor_id` prévio (o provisionamento da Task 7 roda antes dos platforms, então `subentry.data` já tem o id). Pro município, só cria se `monitorar` gerou monitor.

- [ ] **Step 4: Rodar e ver passar** — `.venv/bin/python -m pytest tests/test_binary_sensor.py -q` — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/binary_sensor.py tests/test_binary_sensor.py
git commit -m "feat: binary sensor platform for API status, 5G and monitor health"
```

---

### Task 10: `event.py`

**Files:**
- Modify: `custom_components/redes_moveis_fixas/event.py` (substituir stub)
- Test: `tests/test_event.py`

**Interfaces:**
- Consumes: `SIGNAL_NOVIDADE` (dispatcher, payload cru do webhook).
- Produces: `event.novas_torres_em_<municipio>` (types `nova_erb`/`upgrade_tecnologia`) e `event.novidades_do_ios` (types `nova`/`alterada`/`removida`).

- [ ] **Step 1: Teste que falha**

`tests/test_event.py`:
```python
"""Testes das event entities."""

from homeassistant.helpers.dispatcher import async_dispatcher_send

from custom_components.redes_moveis_fixas.const import SIGNAL_NOVIDADE

from .conftest import entry_completa, load_fixture, mock_client
from .test_sensor import _setup


async def test_event_ios(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_ios = next(
        s
        for s in entry_completa.subentries.values()
        if s.subentry_type == "monitor_ios"
    )
    async_dispatcher_send(
        hass, SIGNAL_NOVIDADE.format(sub_ios.subentry_id), load_fixture("webhook_ios.json")
    )
    await hass.async_block_till_done()

    estado = hass.states.get("event.novidades_do_ios")
    assert estado.attributes["event_type"] == "alterada"
    assert estado.attributes["operadora"] == "TIM"
    assert estado.attributes["bundle"] == {"from": "70.0", "to": "70.1"}


async def test_event_cidade(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    sub_mun = next(
        s
        for s in entry_completa.subentries.values()
        if s.subentry_type == "municipio"
    )
    async_dispatcher_send(
        hass,
        SIGNAL_NOVIDADE.format(sub_mun.subentry_id),
        load_fixture("webhook_cidade.json"),
    )
    await hass.async_block_till_done()

    estado = hass.states.get("event.novas_torres_em_sao_paulo_sp")
    # última ERB do payload: nova=false → upgrade_tecnologia
    assert estado.attributes["event_type"] == "upgrade_tecnologia"
    assert estado.attributes["operadora"] == "TIM"
```

- [ ] **Step 2: Rodar e ver falhar** — `.venv/bin/python -m pytest tests/test_event.py -q`

- [ ] **Step 3: Implementar `event.py`**

```python
"""Event entities da integração RMF."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SIGNAL_NOVIDADE, SUBENTRY_MONITOR_IOS, SUBENTRY_MUNICIPIO
from .entity import RMFEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    rt = entry.runtime_data
    for subentry in entry.subentries.values():
        sid = subentry.subentry_id
        if subentry.subentry_type == SUBENTRY_MUNICIPIO:
            async_add_entities(
                [NovasTorresEvent(rt.municipio[sid], subentry)],
                config_subentry_id=sid,
            )
        elif subentry.subentry_type == SUBENTRY_MONITOR_IOS:
            async_add_entities(
                [NovidadesIosEvent(rt.monitores, subentry)], config_subentry_id=sid
            )


class RMFEventBase(RMFEntity, EventEntity):
    """Escuta o dispatcher do subentry."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_NOVIDADE.format(self._subentry.subentry_id),
                self._recebido,
            )
        )

    @callback
    def _recebido(self, payload: dict) -> None:
        raise NotImplementedError


class NovasTorresEvent(RMFEventBase):
    _attr_event_types = ["nova_erb", "upgrade_tecnologia"]

    def __init__(self, coordinator, subentry: ConfigSubentry) -> None:
        super().__init__(
            coordinator,
            subentry,
            "novas_torres",
            f"Novas torres em {subentry.title}",
        )

    @callback
    def _recebido(self, payload: dict) -> None:
        for erb in payload.get("erbs", []):
            tipo = "nova_erb" if erb.get("nova") else "upgrade_tecnologia"
            self._trigger_event(
                tipo,
                {
                    "operadora": erb.get("operadora"),
                    "id": erb.get("id"),
                    "tecnologias": erb.get("tecnologias"),
                    "tecnologias_novas": erb.get("tecnologias_novas"),
                    "coordenadas": erb.get("coordenadas"),
                    "municipio": payload.get("municipio"),
                },
            )
        self.async_write_ha_state()


class NovidadesIosEvent(RMFEventBase):
    _attr_event_types = ["nova", "alterada", "removida"]

    def __init__(self, coordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator, subentry, "novidades_ios", "Novidades do iOS")

    @callback
    def _recebido(self, payload: dict) -> None:
        for nov in payload.get("novidades", []):
            self._trigger_event(
                nov.get("tipo", "alterada"),
                {
                    "operadora": nov.get("operadora", {}).get("nome"),
                    "pais": nov.get("operadora", {}).get("pais_iso"),
                    "bundle": nov.get("bundle"),
                    "recursos_adicionados": nov.get("recursos_adicionados"),
                    "recursos_removidos": nov.get("recursos_removidos"),
                    "rotulos_adicionados": nov.get("rotulos_adicionados"),
                    "rotulos_removidos": nov.get("rotulos_removidos"),
                    "beta": nov.get("beta"),
                    "ocorrido_em": nov.get("ocorrido_em"),
                },
            )
        self.async_write_ha_state()
```

- [ ] **Step 4: Rodar e ver passar** — `.venv/bin/python -m pytest tests/test_event.py -q` — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/event.py tests/test_event.py
git commit -m "feat: event entities for city towers and iOS carrier bundle updates"
```

---

### Task 11: `geo_location.py`

**Files:**
- Modify: `custom_components/redes_moveis_fixas/geo_location.py` (substituir stub)
- Test: `tests/test_geo_location.py`

**Interfaces:**
- Consumes: `ErbsCoordinator.data["erbs"]`, `CONF_MAX_GEO`.
- Produces: entities `geo_location` das N ERBs mais próximas por subentry local; `source = "redes_moveis_fixas"`; adiciona/remove conforme o coordinator atualiza.

- [ ] **Step 1: Teste que falha**

`tests/test_geo_location.py`:
```python
"""Testes das entities geo_location."""

from .conftest import entry_completa, mock_client
from .test_sensor import _setup


async def test_erbs_no_mapa(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    estados = [
        s for s in hass.states.async_all("geo_location")
        if s.attributes.get("source") == "redes_moveis_fixas"
    ]
    assert len(estados) == 2  # fixture tem 2 ERBs
    claro = next(s for s in estados if "claro" in s.name.lower())
    assert claro.attributes["latitude"] == -23.5601
    assert float(claro.state) == 1.2
```

- [ ] **Step 2: Rodar e ver falhar** — `.venv/bin/python -m pytest tests/test_geo_location.py -q`

- [ ] **Step 3: Implementar `geo_location.py`**

```python
"""ERBs próximas como entidades geo_location (aparecem no mapa)."""

from __future__ import annotations

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MAX_GEO, DEFAULT_MAX_GEO, DOMAIN, SUBENTRY_LOCAL
from .coordinator import ErbsCoordinator
from .entity import RMFEntity

SOURCE = DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    rt = entry.runtime_data
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_LOCAL:
            continue
        max_geo = int(subentry.data.get(CONF_MAX_GEO, DEFAULT_MAX_GEO))
        if max_geo == 0:
            continue
        _GerenteErbs(
            rt.erbs[subentry.subentry_id], subentry, async_add_entities, max_geo
        )


class _GerenteErbs:
    """Mantém as entities em sincronia com o top-N do coordinator."""

    def __init__(
        self,
        coordinator: ErbsCoordinator,
        subentry: ConfigSubentry,
        async_add_entities: AddEntitiesCallback,
        max_geo: int,
    ) -> None:
        self._coordinator = coordinator
        self._subentry = subentry
        self._add = async_add_entities
        self._max = max_geo
        self._entities: dict[str, ErbGeolocationEvent] = {}
        coordinator.async_add_listener(self._sincronizar)
        self._sincronizar()

    @callback
    def _sincronizar(self) -> None:
        erbs = sorted(
            (self._coordinator.data or {}).get("erbs", []),
            key=lambda e: e["distancia_km"],
        )[: self._max]
        atuais = {e["id"]: e for e in erbs}

        novos = [
            ErbGeolocationEvent(self._coordinator, self._subentry, erb)
            for erb_id, erb in atuais.items()
            if erb_id not in self._entities
        ]
        for ent in novos:
            self._entities[ent.erb_id] = ent
        if novos:
            self._add(novos, config_subentry_id=self._subentry.subentry_id)

        for erb_id in list(self._entities):
            if erb_id not in atuais:
                ent = self._entities.pop(erb_id)
                ent.hass.async_create_task(ent.async_remove())


class ErbGeolocationEvent(RMFEntity, GeolocationEvent):
    _attr_source = SOURCE
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_icon = "mdi:radio-tower"

    def __init__(self, coordinator, subentry, erb: dict) -> None:
        self.erb_id: str = erb["id"]
        super().__init__(
            coordinator,
            subentry,
            f"erb_{erb['id']}",
            f"ERB {erb['operadora']} {erb['id']}",
        )
        self._erb = erb

    def _atual(self) -> dict | None:
        for erb in (self.coordinator.data or {}).get("erbs", []):
            if erb["id"] == self.erb_id:
                return erb
        return None

    @property
    def distance(self) -> float | None:
        erb = self._atual() or self._erb
        return erb.get("distancia_km")

    @property
    def latitude(self) -> float | None:
        erb = self._atual() or self._erb
        return erb.get("coordenadas", {}).get("lat")

    @property
    def longitude(self) -> float | None:
        erb = self._atual() or self._erb
        return erb.get("coordenadas", {}).get("lon")

    @property
    def extra_state_attributes(self):
        erb = self._atual() or self._erb
        return {
            "operadora": erb.get("operadora"),
            "tecnologias": erb.get("tecnologias"),
            "bandas": erb.get("bandas"),
            "endereco": erb.get("endereco"),
        }
```

- [ ] **Step 4: Rodar e ver passar** — `.venv/bin/python -m pytest tests/test_geo_location.py -q` — Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/geo_location.py tests/test_geo_location.py
git commit -m "feat: geo_location platform showing nearby towers on the map"
```

---

### Task 12: Actions (`services.py` + `services.yaml`)

**Files:**
- Create: `custom_components/redes_moveis_fixas/services.py`, `custom_components/redes_moveis_fixas/services.yaml`
- Modify: `custom_components/redes_moveis_fixas/__init__.py` (chamar `async_setup_services(hass)` dentro de `async_setup_entry`, antes do forward)
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: `RMFRuntime.client` da primeira entry carregada.
- Produces: actions `redes_moveis_fixas.consultar_cobertura`, `.buscar_estacoes`, `.resumo_do_municipio` — todas `SupportsResponse.ONLY`.

- [ ] **Step 1: Teste que falha**

`tests/test_services.py`:
```python
"""Testes das actions."""

from .conftest import entry_completa, mock_client
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
```

- [ ] **Step 2: Rodar e ver falhar** — `.venv/bin/python -m pytest tests/test_services.py -q`

- [ ] **Step 3: Implementar**

`services.py`:
```python
"""Actions da integração RMF."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import RMFClient, RMFError
from .const import DOMAIN

SCHEMA_COBERTURA = vol.Schema(
    {
        vol.Optional("latitude"): vol.Coerce(float),
        vol.Optional("longitude"): vol.Coerce(float),
        vol.Optional("entity_id"): cv.entity_id,
    }
)

SCHEMA_ESTACOES = SCHEMA_COBERTURA.extend(
    {
        vol.Optional("operadora"): cv.string,
        vol.Optional("tecnologia"): cv.string,
        vol.Optional("banda"): cv.string,
        vol.Optional("limite", default=200): vol.All(int, vol.Range(min=1, max=1000)),
    }
)

SCHEMA_RESUMO = vol.Schema({vol.Required("codigo_ibge"): vol.Coerce(int)})


def _client(hass: HomeAssistant) -> RMFClient:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data.client
    raise HomeAssistantError("Nenhuma entry da RMF carregada")


def _coords(hass: HomeAssistant, call: ServiceCall) -> tuple[float, float]:
    if "entity_id" in call.data:
        state = hass.states.get(call.data["entity_id"])
        if state is None or state.attributes.get("latitude") is None:
            raise HomeAssistantError(
                f"{call.data.get('entity_id')} sem coordenadas"
            )
        return state.attributes["latitude"], state.attributes["longitude"]
    if "latitude" not in call.data or "longitude" not in call.data:
        raise HomeAssistantError("Informe latitude/longitude ou entity_id")
    return call.data["latitude"], call.data["longitude"]


def _csv(valor: str | None) -> list[str] | None:
    if not valor:
        return None
    return [v.strip() for v in valor.split(",") if v.strip()]


async def _consultar_cobertura(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    lat, lon = _coords(hass, call)
    try:
        return await _client(hass).async_cobertura(lat, lon)
    except RMFError as err:
        raise HomeAssistantError(str(err)) from err


async def _buscar_estacoes(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    lat, lon = _coords(hass, call)
    try:
        return await _client(hass).async_estacoes(
            lat,
            lon,
            operadora=_csv(call.data.get("operadora")),
            tecnologia=_csv(call.data.get("tecnologia")),
            banda=_csv(call.data.get("banda")),
            limite=call.data["limite"],
        )
    except RMFError as err:
        raise HomeAssistantError(str(err)) from err


async def _resumo_do_municipio(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    try:
        return await _client(hass).async_resumo_municipio(call.data["codigo_ibge"])
    except RMFError as err:
        raise HomeAssistantError(str(err)) from err


def async_setup_services(hass: HomeAssistant) -> None:
    """Registra as actions (idempotente)."""
    if hass.services.has_service(DOMAIN, "consultar_cobertura"):
        return
    hass.services.async_register(
        DOMAIN,
        "consultar_cobertura",
        _consultar_cobertura,
        schema=SCHEMA_COBERTURA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "buscar_estacoes",
        _buscar_estacoes,
        schema=SCHEMA_ESTACOES,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "resumo_do_municipio",
        _resumo_do_municipio,
        schema=SCHEMA_RESUMO,
        supports_response=SupportsResponse.ONLY,
    )
```

No `__init__.py`, adicionar import `from .services import async_setup_services` e chamar `async_setup_services(hass)` logo antes de `await hass.config_entries.async_forward_entry_setups(...)`.

`services.yaml`:
```yaml
consultar_cobertura:
  fields:
    latitude:
      example: -5.812757
      selector:
        number:
          min: -35
          max: 6
          step: any
    longitude:
      example: -35.255127
      selector:
        number:
          min: -75
          max: -28
          step: any
    entity_id:
      selector:
        entity:
          filter:
            domain: ["zone", "person"]

buscar_estacoes:
  fields:
    latitude:
      selector:
        number:
          min: -35
          max: 6
          step: any
    longitude:
      selector:
        number:
          min: -75
          max: -28
          step: any
    entity_id:
      selector:
        entity:
          filter:
            domain: ["zone", "person"]
    operadora:
      example: "claro,vivo"
      selector:
        text:
    tecnologia:
      example: "NR,LTE"
      selector:
        text:
    banda:
      example: "78"
      selector:
        text:
    limite:
      selector:
        number:
          min: 1
          max: 1000

resumo_do_municipio:
  fields:
    codigo_ibge:
      required: true
      example: 3550308
      selector:
        number:
          min: 1100015
          max: 5300108
          mode: box
```

- [ ] **Step 4: Rodar e ver passar** — `.venv/bin/python -m pytest tests/test_services.py -q` — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/services.py custom_components/redes_moveis_fixas/services.yaml custom_components/redes_moveis_fixas/__init__.py tests/test_services.py
git commit -m "feat: response-returning actions for coverage, stations and municipality"
```

---

### Task 13: Repairs (monitor inativo / URL mudou / órfãos)

**Files:**
- Create: `custom_components/redes_moveis_fixas/repairs.py`
- Modify: `custom_components/redes_moveis_fixas/__init__.py` (listener do MonitoresCoordinator + varredura de órfãos)
- Test: `tests/test_repairs.py`

**Interfaces:**
- Consumes: `MonitoresCoordinator.data`, `CONF_MONITOR_ID`/`CONF_MONITOR_SECRET`, `_provisionar_monitor`.
- Produces:
  - Issue `monitor_inativo_{subentry_id}` (fixável) quando o monitor da subentry está `ativo: false` ou sumiu da listagem.
  - Varredura de órfãos no setup: monitor listado na API apontando pra nossa URL de webhook mas sem subentry dona → DELETE (cobre remoção de subentry, que não tem hook).
  - `async_create_fix_flow(hass, issue_id, data)` em `repairs.py` — confirm step recria o monitor (novo id+secret na subentry) e fecha a issue.

- [ ] **Step 1: Teste que falha**

`tests/test_repairs.py`:
```python
"""Testes de repairs e órfãos."""

from unittest.mock import patch

import homeassistant.helpers.issue_registry as ir

from .conftest import entry_completa, load_fixture, mock_client
from .test_sensor import _setup


async def test_issue_quando_monitor_inativo(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    lista = load_fixture("monitores_ios_lista.json")["dados"]
    lista[0]["ativo"] = False
    lista[0]["falhas_seguidas"] = 10

    def _listar(tipo):
        return lista if tipo == "ios" else []

    mock_client.async_listar_monitores.side_effect = _listar
    # subentry ios já com monitor_id igual ao da listagem
    for sub in entry_completa.subentries.values():
        if sub.subentry_type == "monitor_ios":
            object.__setattr__(sub, "data", {**sub.data, "monitor_id": "3ab7f001", "monitor_secret": "s"})

    await _setup(hass, entry_completa, mock_client)

    registry = ir.async_get(hass)
    sub_ios = next(
        s for s in entry_completa.subentries.values() if s.subentry_type == "monitor_ios"
    )
    issue = registry.async_get_issue(
        "redes_moveis_fixas", f"monitor_inativo_{sub_ios.subentry_id}"
    )
    assert issue is not None


async def test_orfao_removido(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})

    orfao = {
        "id": "deadbeef",
        "url": "https://ha.example.com/api/webhook/wh_fixo",
        "ativo": True,
        "falhas_seguidas": 0,
        "ultima_entrega": None,
        "ultimo_erro": None,
    }

    def _listar(tipo):
        return [orfao] if tipo == "cidade" else []

    mock_client.async_listar_monitores.side_effect = _listar
    await _setup(hass, entry_completa, mock_client)

    mock_client.async_remover_monitor.assert_any_await("cidade", "deadbeef")
```

- [ ] **Step 2: Rodar e ver falhar** — `.venv/bin/python -m pytest tests/test_repairs.py -q`

- [ ] **Step 3: Implementar**

No `__init__.py`, após o first refresh do `monitores` e da criação do `rt`, adicionar:

```python
from homeassistant.helpers import issue_registry as ir


def _checar_monitores(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Cria/fecha issues conforme o estado dos monitores."""
    rt: RMFRuntime = entry.runtime_data
    dados = rt.monitores.data or {}
    for subentry in entry.subentries.values():
        monitor_id = subentry.data.get(CONF_MONITOR_ID)
        if not monitor_id:
            continue
        mon = dados.get(monitor_id)
        issue_id = f"monitor_inativo_{subentry.subentry_id}"
        if mon is None or not mon.get("ativo"):
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="monitor_inativo",
                translation_placeholders={"nome": subentry.title},
                data={"entry_id": entry.entry_id, "subentry_id": subentry.subentry_id},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


async def _remover_orfaos(
    hass: HomeAssistant, entry: ConfigEntry, client: RMFClient, url_webhook: str
) -> None:
    """Apaga monitores da API que apontam pro nosso webhook mas não têm subentry."""
    nossos = {
        s.data.get(CONF_MONITOR_ID)
        for s in entry.subentries.values()
        if s.data.get(CONF_MONITOR_ID)
    }
    for tipo in ("cidade", "ios"):
        try:
            lista = await client.async_listar_monitores(tipo)
        except RMFError:
            continue
        for mon in lista:
            if mon.get("url") == url_webhook and mon["id"] not in nossos:
                try:
                    await client.async_remover_monitor(tipo, mon["id"])
                    _LOGGER.info("Monitor órfão %s removido", mon["id"])
                except RMFError as err:
                    _LOGGER.warning("Falha ao remover órfão %s: %s", mon["id"], err)
```

Chamadas dentro de `async_setup_entry` (depois do loop das subentries, antes do forward):
```python
    await _remover_orfaos(hass, entry, client, url_webhook)
    _checar_monitores(hass, entry)
    entry.async_on_unload(
        rt.monitores.async_add_listener(lambda: _checar_monitores(hass, entry))
    )
```

`repairs.py`:
```python
"""Fix flows das issues de monitor."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.components.webhook import async_generate_url
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_MONITOR_ID, CONF_MONITOR_SECRET, CONF_WEBHOOK_ID, DOMAIN


class MonitorInativoFlow(RepairsFlow):
    """Recria o monitor desativado pela API."""

    def __init__(self, data: dict) -> None:
        self._data = data

    async def async_step_init(self, user_input=None):
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        if user_input is not None:
            hass = self.hass
            entry = hass.config_entries.async_get_entry(self._data["entry_id"])
            subentry = entry.subentries[self._data["subentry_id"]]
            client = entry.runtime_data.client
            # apaga o registro morto (melhor esforço) e recria
            from . import _provisionar_monitor  # import tardio evita ciclo
            from .api import RMFError
            from .const import SUBENTRY_MUNICIPIO

            tipo = (
                "cidade" if subentry.subentry_type == SUBENTRY_MUNICIPIO else "ios"
            )
            velho = subentry.data.get(CONF_MONITOR_ID)
            if velho:
                try:
                    await client.async_remover_monitor(tipo, velho)
                except RMFError:
                    pass
            hass.config_entries.async_update_subentry(
                entry,
                subentry,
                data={
                    k: v
                    for k, v in subentry.data.items()
                    if k not in (CONF_MONITOR_ID, CONF_MONITOR_SECRET)
                },
            )
            url = async_generate_url(hass, entry.data[CONF_WEBHOOK_ID])
            await _provisionar_monitor(hass, entry, subentry, client, url)
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None
) -> RepairsFlow:
    return MonitorInativoFlow(data or {})
```

Nota: `hass.config_entries.async_update_subentry` reloada a entry via update listener — o fix flow termina antes; o reload re-registra tudo com o monitor novo.

- [ ] **Step 4: Rodar e ver passar** — `.venv/bin/python -m pytest tests/test_repairs.py -q` — Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add custom_components/redes_moveis_fixas/repairs.py custom_components/redes_moveis_fixas/__init__.py tests/test_repairs.py
git commit -m "feat: repair issues for dead monitors and orphan cleanup"
```

---

### Task 14: Diagnostics, strings/traduções, README e passada final

**Files:**
- Create: `custom_components/redes_moveis_fixas/diagnostics.py`, `custom_components/redes_moveis_fixas/translations/pt-BR.json`, `custom_components/redes_moveis_fixas/translations/en.json`, `README.md`, `.gitignore`
- Modify: `custom_components/redes_moveis_fixas/strings.json` (completar subentries + issues)
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: tudo anterior.
- Produces: `async_get_config_entry_diagnostics(hass, entry) -> dict` com `token`, `monitor_secret` e `webhook_id` redigidos.

- [ ] **Step 1: Teste que falha**

`tests/test_diagnostics.py`:
```python
"""Testes de diagnostics."""

from custom_components.redes_moveis_fixas.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import entry_completa, mock_client
from .test_sensor import _setup


async def test_diagnostics_redige_segredos(hass, entry_completa, mock_client):
    hass.states.async_set("zone.home", "0", {"latitude": -5.8, "longitude": -35.2})
    await _setup(hass, entry_completa, mock_client)

    diag = await async_get_config_entry_diagnostics(hass, entry_completa)
    assert diag["entry"]["data"]["token"] == "**REDACTED**"
    for sub in diag["subentries"]:
        assert sub["data"].get("monitor_secret") in (None, "**REDACTED**")
    assert diag["health"]["status"] == "ok"
```

- [ ] **Step 2: Rodar e ver falhar** — `.venv/bin/python -m pytest tests/test_diagnostics.py -q`

- [ ] **Step 3: Implementar `diagnostics.py`**

```python
"""Diagnostics com redação de segredos."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MONITOR_SECRET, CONF_TOKEN, CONF_WEBHOOK_ID

A_REDIGIR = {CONF_TOKEN, CONF_MONITOR_SECRET, CONF_WEBHOOK_ID}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    rt = entry.runtime_data
    return {
        "entry": {"data": async_redact_data(dict(entry.data), A_REDIGIR)},
        "subentries": [
            {
                "type": s.subentry_type,
                "title": s.title,
                "data": async_redact_data(dict(s.data), A_REDIGIR),
            }
            for s in entry.subentries.values()
        ],
        "health": rt.health.data,
        "monitores": {
            mid: {k: v for k, v in m.items() if k != "secret"}
            for mid, m in (rt.monitores.data or {}).items()
        },
    }
```

- [ ] **Step 4: Completar `strings.json`** (adicionar ao existente)

```json
{
  "config_subentries": {
    "local": {
      "title": "Local",
      "step": {
        "user": {
          "title": "Tipo de local",
          "data": {"modo": "Acompanhar"}
        },
        "alvo": {
          "title": "Local e intervalos",
          "data": {
            "entity_id": "Zona ou pessoa",
            "intervalo_cobertura": "Intervalo de cobertura (min)",
            "intervalo_erbs": "Intervalo de ERBs (h)",
            "max_geo": "Máx. de torres no mapa (0 desliga)"
          }
        }
      },
      "initiate_flow": {"user": "Adicionar local"},
      "entry_type": "Local"
    },
    "municipio": {
      "title": "Município",
      "step": {
        "user": {
          "title": "Município (código IBGE)",
          "data": {
            "codigo_ibge": "Código IBGE (7 dígitos)",
            "monitorar": "Monitorar novas torres (webhook diário)",
            "intervalo_municipio": "Intervalo do resumo (h)"
          }
        }
      },
      "error": {
        "ibge_invalido": "Código IBGE não encontrado",
        "cannot_connect": "Falha ao conectar na API"
      },
      "initiate_flow": {"user": "Adicionar município"},
      "entry_type": "Município"
    },
    "monitor_ios": {
      "title": "Monitor iOS",
      "step": {
        "user": {
          "title": "Carrier bundles do iOS",
          "data": {
            "paises": "Países (ISO-2, separados por vírgula; * = todos)",
            "operadoras": "Operadoras (opcional, separadas por vírgula)",
            "incluir_beta": "Incluir versões beta do iOS"
          }
        }
      },
      "initiate_flow": {"user": "Adicionar monitor iOS"},
      "entry_type": "Monitor iOS"
    }
  },
  "issues": {
    "monitor_inativo": {
      "title": "Monitor \"{nome}\" desativado",
      "fix_flow": {
        "step": {
          "confirm": {
            "title": "Recriar monitor",
            "description": "A API RMF desativou este monitor após 10 falhas de entrega. Confirme pra registrar um novo com a URL atual do seu Home Assistant."
          }
        }
      }
    }
  },
  "selector": {
    "modo": {
      "options": {"zona": "Zona fixa", "pessoa": "Seguir pessoa"}
    }
  }
}
```

Copiar `strings.json` → `translations/pt-BR.json` (idêntico) e criar `translations/en.json` com os mesmos campos em inglês (traduzir os textos: "Add location", "IBGE code (7 digits)", "Monitor \"{nome}\" deactivated", etc.).

- [ ] **Step 5: README.md**

Conteúdo mínimo: badge HACS, o que a integração faz (4 blocos: cobertura, ERBs+mapa, município, monitores webhook), requisito de `external_url` HTTPS pro webhook, instalação via HACS custom repository, tabela de entities, as 3 actions com exemplo YAML, limitação "operadora nova exige reload", cotas da API e defaults de intervalo.

`.gitignore`:
```
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 6: Passada final**

Run: `.venv/bin/python -m pytest tests/ -q` — Expected: todos passam.
Run: `.venv/bin/pip install -q ruff && .venv/bin/ruff check custom_components/ tests/ --fix && .venv/bin/ruff format custom_components/ tests/`
Re-rodar pytest depois do format.

- [ ] **Step 7: Commit final**

```bash
git add -A && git commit -m "feat: diagnostics, translations and docs"
```

---

## Verificação final do plano (self-review executada)

- **Cobertura do spec:** arquitetura (T1/T7), api (T2), coordinators+cotas (T3), webhook HMAC+bus (T4), config flow+reauth (T5), subentries (T6), person-follow+provisionamento+DELETE na remoção (T7/T13), sensores (T8), binary (T9), events (T10), geo_location (T11), actions (T12), repairs+órfãos (T13), diagnostics/traduções/README/empacotamento (T14). Item do spec "repair quando external_url muda" coberto parcialmente: a issue `monitor_inativo` dispara quando as entregas começam a falhar após mudança de URL (o monitor morre em ≤10 tentativas e o fix flow recria com a URL nova) — caminho direto de detecção de URL divergente ficou de fora por YAGNI; documentar no README.
- **Placeholders:** nenhum "TBD"; único texto delegado é a tradução `en.json` e o corpo do README (conteúdo enumerado no passo).
- **Consistência de tipos:** `RMFRuntime` (T7) é a interface usada por T8–T13; assinaturas de `RMFClient` fixadas em T2 e usadas idênticas em T3/T7/T12/T13; `SIGNAL_NOVIDADE.format(subentry_id)` consistente em T4/T10.
- **Riscos conhecidos (pro executor):** APIs de subentry (`hass.config_entries.subentries.async_init`, `async_update_subentry`, `config_subentry_id` em `async_add_entities`) variam entre versões do HA — se der `AttributeError`, atualizar `pytest-homeassistant-custom-component` e conferir assinatura na versão instalada antes de mudar o design.
