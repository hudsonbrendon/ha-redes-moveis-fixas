"""Cliente HTTP puro da API RMF (sem dependência do Home Assistant)."""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import BASE_URL


class RMFError(Exception):
    """Erro genérico da API RMF."""


class RMFAuthError(RMFError):
    """Token inválido, expirado ou revogado (401/403).

    A API real responde 401 ("Token inválido, expirado ou revogado.") quando o
    token de 90 dias vence; tratar só o 403 deixava a entry presa em
    SETUP_RETRY em vez de abrir o reauth.
    """


class RMFRateLimitError(RMFError):
    """Cota excedida (429)."""


class RMFGoneError(RMFError):
    """Recurso descontinuado pela API (410), ex.: novos monitores de iOS."""


class RMFNotFoundError(RMFError):
    """Recurso não encontrado (404)."""


def _rota(tipo: str) -> str:
    if tipo not in ("cidade", "ios"):
        raise ValueError(f"tipo inválido: {tipo}")
    return tipo


def _dados(payload: Any) -> Any:
    """Extrai `payload["dados"]`, sem KeyError pra resposta malformada.

    Sem isto, um `payload["dados"]` cru levanta KeyError — fora da hierarquia
    RMFError, então bypassa toda tradução de erro rio abaixo: SETUP_ERROR em
    vez de SETUP_RETRY no provisionamento, traceback cru pras automações em
    services.py, "erro desconhecido" no form da subentry de município.
    """
    if not isinstance(payload, dict) or "dados" not in payload:
        raise RMFError("Resposta da API sem campo 'dados'")
    return payload["dados"]


def _dados_monitor(payload: Any) -> dict:
    """Como `_dados`, mas também garante id/secret pra criação de monitor.

    `_provisionar_monitor` (__init__.py) lê `dados["id"]`/`dados["secret"]`
    direto pra persistir na subentry — sem esta validação aqui, a mesma
    KeyError fora da hierarquia RMFError escaparia dali.
    """
    dados = _dados(payload)
    if not isinstance(dados, dict) or "id" not in dados or "secret" not in dados:
        raise RMFError("Resposta de criação de monitor sem 'id'/'secret'")
    return dados


def _lista_monitores(dados: Any) -> list[dict]:
    """Normaliza a listagem de monitores para uma lista de dicts.

    A API devolve `dados` como envelope: `{"total": N, "monitores": [...]}`.
    Iterar o envelope direto rende as CHAVES (strings), e o consumidor quebra
    com "'str' object has no attribute 'get'" — foi o que derrubou o setup na
    primeira instalação real. Uma lista pura também é aceita, caso a API volte
    a devolvê-la.
    """
    if isinstance(dados, dict):
        dados = dados.get("monitores", [])
    if not isinstance(dados, list):
        raise RMFError("Listagem de monitores em formato inesperado")
    return [m for m in dados if isinstance(m, dict)]


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
                if resp.status in (401, 403):
                    raise RMFAuthError(await resp.text())
                if resp.status == 429:
                    raise RMFRateLimitError(await resp.text())
                if resp.status == 410:
                    raise RMFGoneError(await resp.text())
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
        return _dados(payload)

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
        return _dados(payload)

    async def async_resumo_municipio(self, codigo_ibge: int) -> dict:
        payload = await self._request("GET", f"/api/municipios/{codigo_ibge}/resumo")
        return _dados(payload)

    async def async_health(self) -> dict:
        return await self._request("GET", "/health", auth=False)

    async def async_listar_monitores(self, tipo: str) -> list[dict]:
        payload = await self._request("GET", f"/api/monitorar-{_rota(tipo)}")
        return _lista_monitores(_dados(payload))

    async def async_criar_monitor_cidade(
        self, url: str, municipios: list[str], descricao: str | None = None
    ) -> dict:
        body: dict[str, Any] = {"url": url, "municipios": municipios}
        if descricao:
            body["descricao"] = descricao
        payload = await self._request("POST", "/api/monitorar-cidade", json=body)
        return _dados_monitor(payload)

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
        return _dados_monitor(payload)

    async def async_remover_monitor(self, tipo: str, monitor_id: str) -> None:
        await self._request("DELETE", f"/api/monitorar-{_rota(tipo)}/{monitor_id}")
