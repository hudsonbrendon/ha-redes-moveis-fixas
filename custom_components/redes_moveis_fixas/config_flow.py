"""Config flow da integração RMF."""

from __future__ import annotations

import hashlib
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
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

SCHEMA_TOKEN = vol.Schema({vol.Required(CONF_TOKEN): str})


async def _validar_token(hass: HomeAssistant, token: str) -> None:
    """Chamada autenticada barata; levanta RMFAuthError se o token for ruim."""
    client = RMFClient(aiohttp_client.async_get_clientsession(hass), token)
    await client.async_listar_monitores("ios")


def _uid(token: str) -> str:
    """Hash do token usado como unique_id (nunca o token cru)."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


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
                await self.async_set_unique_id(_uid(user_input[CONF_TOKEN]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Redes Móveis Fixas", data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=SCHEMA_TOKEN, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
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
                    unique_id=_uid(user_input[CONF_TOKEN]),
                    data_updates={CONF_TOKEN: user_input[CONF_TOKEN]},
                )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=SCHEMA_TOKEN, errors=errors
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return {
            SUBENTRY_LOCAL: LocalSubentryFlow,
            SUBENTRY_MUNICIPIO: MunicipioSubentryFlow,
            SUBENTRY_MONITOR_IOS: MonitorIosSubentryFlow,
        }


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
                title=titulo,
                data={
                    CONF_MODO: self._modo,
                    CONF_ENTITY_ID: user_input[CONF_ENTITY_ID],
                    CONF_INTERVALO_COBERTURA: int(user_input[CONF_INTERVALO_COBERTURA]),
                    CONF_INTERVALO_ERBS: int(user_input[CONF_INTERVALO_ERBS]),
                    CONF_MAX_GEO: int(user_input[CONF_MAX_GEO]),
                },
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
                    NumberSelectorConfig(
                        min=5, max=1440, mode="box", unit_of_measurement="min"
                    )
                ),
                vol.Required(
                    CONF_INTERVALO_ERBS, default=DEFAULT_INTERVALO_ERBS_H
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=168, mode="box", unit_of_measurement="h"
                    )
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
                        CONF_INTERVALO_MUNICIPIO: int(
                            user_input[CONF_INTERVALO_MUNICIPIO]
                        ),
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_IBGE): str,
                vol.Required(CONF_MONITORAR, default=True): BooleanSelector(),
                vol.Required(
                    CONF_INTERVALO_MUNICIPIO, default=DEFAULT_INTERVALO_MUNICIPIO_H
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=168, mode="box", unit_of_measurement="h"
                    )
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
