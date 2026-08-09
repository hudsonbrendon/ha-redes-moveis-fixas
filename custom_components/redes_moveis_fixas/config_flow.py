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
