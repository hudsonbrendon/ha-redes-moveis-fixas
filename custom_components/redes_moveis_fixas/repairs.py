"""Fix flows das issues de monitor."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .api import RMFError
from .const import CONF_MONITOR_ID, CONF_MONITOR_SECRET, SUBENTRY_MUNICIPIO


class MonitorInativoFlow(RepairsFlow):
    """Recria o monitor desativado pela API."""

    def __init__(self, data: dict) -> None:
        self._data = data

    async def async_step_init(self, user_input=None):
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        if user_input is not None:
            hass = self.hass
            entry = hass.config_entries.async_get_entry(self._data.get("entry_id"))
            # A issue sobrevive à entry: nada em async_remove_entry/reload a
            # apaga automaticamente se o usuário demora pra clicar "Corrigir".
            # Sem estes guards, uma entry removida (entry is None) ou só
            # descarregada (runtime_data já foi apagado pelo próprio
            # ConfigEntry.async_unload — ver object.__delattr__ no core) faz
            # este step estourar AttributeError puro em vez de abortar limpo.
            if entry is None:
                return self.async_abort(reason="entry_not_found")
            if entry.state is not ConfigEntryState.LOADED:
                return self.async_abort(reason="entry_not_loaded")
            subentry = entry.subentries.get(self._data.get("subentry_id"))
            if subentry is None:
                return self.async_abort(reason="subentry_not_found")
            client = entry.runtime_data.client

            tipo = "cidade" if subentry.subentry_type == SUBENTRY_MUNICIPIO else "ios"
            velho = subentry.data.get(CONF_MONITOR_ID)
            if velho:
                # melhor esforço: se a API já desativou/apagou, DELETE pode
                # falhar (404/erro) sem impedir a recriação abaixo.
                try:
                    await client.async_remover_monitor(tipo, velho)
                except RMFError:
                    pass
            # Só isto: tirar monitor_id/secret dispara o update listener, que
            # agenda um reload (via hass.async_create_task, não awaited). O
            # próprio async_setup_entry já reprovisiona sozinho qualquer
            # subentry sem monitor_id (_provisionar_monitor é idempotente
            # nisso) — chamá-lo de novo aqui, manualmente, corria em paralelo
            # com esse reload agendado e podia criar dois monitores pra
            # mesma subentry. Deixar só o reload provisionar elimina a
            # corrida: existe exatamente UM lugar que cria monitor (o loop de
            # subentries do setup), disparado por UM reload agendado por esta
            # única chamada.
            hass.config_entries.async_update_subentry(
                entry,
                subentry,
                data={
                    k: v
                    for k, v in subentry.data.items()
                    if k not in (CONF_MONITOR_ID, CONF_MONITOR_SECRET)
                },
            )
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None
) -> RepairsFlow:
    return MonitorInativoFlow(data or {})
