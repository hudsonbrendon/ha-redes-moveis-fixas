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
