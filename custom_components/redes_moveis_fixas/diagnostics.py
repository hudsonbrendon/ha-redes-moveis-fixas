"""Diagnostics com redação de segredos."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MONITOR_SECRET, CONF_TOKEN, CONF_WEBHOOK_ID

A_REDIGIR = {CONF_TOKEN, CONF_MONITOR_SECRET, CONF_WEBHOOK_ID}

# Campos dos objetos de monitor (rt.monitores.data, direto da API — não passa
# por async_redact_data) que vazam segredo: "secret" é o monitor_secret cru;
# "url" é a URL completa do nosso webhook (host externo do usuário + o
# próprio webhook_id que A_REDIGIR já redige em entry.data). Sem isto, um
# usuário que anexa diagnostics a uma issue pública do GitHub publica os dois.
_CAMPOS_MONITOR_A_OMITIR = {"secret", "url"}


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
            mid: {k: v for k, v in m.items() if k not in _CAMPOS_MONITOR_A_OMITIR}
            for mid, m in (rt.monitores.data or {}).items()
        },
    }
