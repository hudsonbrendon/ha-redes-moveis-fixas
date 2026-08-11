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
    """Monta o dump de diagnóstico com token/monitor_secret/webhook_id redigidos."""
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
