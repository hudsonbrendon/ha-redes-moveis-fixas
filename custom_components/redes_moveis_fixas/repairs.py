"""Fix flows das issues de monitor."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import CONF_MONITOR_ID, CONF_MONITOR_SECRET, CONF_WEBHOOK_ID


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

            # import tardio evita ciclo (__init__ importa coordinators/services,
            # não repairs; repairs precisa do helper de provisionamento do __init__)
            from . import _provisionar_monitor
            from .api import RMFError
            from .const import SUBENTRY_MUNICIPIO

            tipo = "cidade" if subentry.subentry_type == SUBENTRY_MUNICIPIO else "ios"
            velho = subentry.data.get(CONF_MONITOR_ID)
            if velho:
                # melhor esforço: se a API já desativou/apagou, DELETE pode
                # falhar (404/erro) sem impedir a recriação abaixo.
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
            # _provisionar_monitor espera o webhook_id (não a URL): ele mesmo
            # resolve a URL via async_generate_url. Passar a URL aqui geraria
            # um webhook inválido (URL dentro de URL).
            await _provisionar_monitor(
                hass, entry, subentry, client, entry.data[CONF_WEBHOOK_ID]
            )
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None
) -> RepairsFlow:
    return MonitorInativoFlow(data or {})
