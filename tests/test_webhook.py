"""Testes do handler de webhook."""

import copy
import hashlib
import hmac
import json
import time

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
SECRET_MUNICIPIO = "whsec_muni_1d90aa"
SECRET_IOS = "whsec_ios_2e81bb"
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
                    "monitor_secret": SECRET_MUNICIPIO,
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
                    "monitor_secret": SECRET_IOS,
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
    ts, sig = _assinar(body, secret=SECRET_MUNICIPIO)

    sub_municipio = next(
        s for s in entry.subentries.values() if s.subentry_type == "municipio"
    )
    sub_ios = next(
        s for s in entry.subentries.values() if s.subentry_type == "monitor_ios"
    )
    recebidos = []
    async_dispatcher_connect(
        hass, SIGNAL_NOVIDADE.format(sub_municipio.subentry_id), recebidos.append
    )
    recebidos_ios = []
    async_dispatcher_connect(
        hass, SIGNAL_NOVIDADE.format(sub_ios.subentry_id), recebidos_ios.append
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
    # o roteamento por IBGE não deve vazar pro subentry de iOS
    assert recebidos_ios == []


async def test_webhook_ios_despacha(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    ts, sig = _assinar(body, secret=SECRET_IOS)

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


async def test_webhook_cidade_ibge_sem_correspondencia_401(hass, entry):
    payload = copy.deepcopy(load_fixture("webhook_cidade.json"))
    payload["municipio"]["codigo_ibge"] = 9999999
    body = json.dumps(payload).encode()
    ts, sig = _assinar(body, secret=SECRET_MUNICIPIO)

    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": sig}),
    )
    assert resp.status == 401


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


async def test_timestamp_futuro_401(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    ts_futuro = str(int(time.time()) + 3600)
    ts, sig = _assinar(body, secret=SECRET_IOS, ts=ts_futuro)
    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": sig}),
    )
    assert resp.status == 401


async def test_timestamp_ausente_401(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    _, sig = _assinar(body, secret=SECRET_IOS)
    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Signature": sig}),
    )
    assert resp.status == 401


async def test_assinatura_ausente_401(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts}),
    )
    assert resp.status == 401


async def test_assinatura_nao_ascii_401(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": "sha256=é"}),
    )
    assert resp.status == 401


async def test_json_malformado_400(hass, entry):
    body = b"\x80abc"  # UTF-8 inválido
    ts = str(int(time.time()))
    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": "sha256=x"}),
    )
    assert resp.status == 400


async def test_json_nao_objeto_400(hass, entry):
    body = json.dumps([1, 2]).encode()
    ts = str(int(time.time()))
    resp = await handle_webhook(
        hass,
        WEBHOOK_ID,
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": "sha256=x"}),
    )
    assert resp.status == 400


async def test_webhook_id_desconhecido_404(hass, entry):
    payload = load_fixture("webhook_ios.json")
    body = json.dumps(payload).encode()
    ts, sig = _assinar(body, secret=SECRET_IOS)
    resp = await handle_webhook(
        hass,
        "wh_outro_id",
        FakeRequest(body, {"X-RMF-Timestamp": ts, "X-RMF-Signature": sig}),
    )
    assert resp.status == 404
