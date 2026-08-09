"""Recepção e verificação dos webhooks da API RMF."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
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
    esperado = f"sha256={mac.hexdigest()}".encode()
    # compare_digest exige ASCII puro pra strings; comparando bytes evita o
    # TypeError de um header de assinatura não-ASCII (ex.: "sha256=é").
    return hmac.compare_digest(esperado, assinatura.encode())


def _entry_por_webhook(hass: HomeAssistant, webhook_id: str) -> ConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_WEBHOOK_ID) == webhook_id:
            return entry
    return None


def _candidatos(entry: ConfigEntry, payload: dict) -> list[ConfigSubentry]:
    evento = payload.get("evento")
    subs = list(entry.subentries.values())
    if evento == EVENTO_CIDADE:
        municipio = payload.get("municipio")
        ibge = municipio.get("codigo_ibge") if isinstance(municipio, dict) else None
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
        ts_num = float(timestamp)
    except ValueError:
        _LOGGER.warning("Webhook RMF sem timestamp válido")
        return web.Response(status=401)
    # math.isfinite descarta nan/inf, que passariam ilesos pelo `abs(...) > tolerância`.
    if not math.isfinite(ts_num) or abs(time.time() - ts_num) > TOLERANCIA_TIMESTAMP_S:
        _LOGGER.warning("Webhook RMF com timestamp fora da tolerância")
        return web.Response(status=401)

    try:
        payload = json.loads(body)
    except ValueError:  # inclui json.JSONDecodeError e UnicodeDecodeError
        return web.Response(status=400)
    if not isinstance(payload, dict):
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
