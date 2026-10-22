"""Config flow: Husqvarna developer key and secret (reused from the official integration if present)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GardenaAppClient, GardenaAuthError, GardenaError
from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES, DOMAIN


class GardenaAppConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = GardenaAppClient(
                async_get_clientsession(self.hass), user_input[CONF_CLIENT_ID], user_input[CONF_CLIENT_SECRET]
            )
            try:
                name = await client.async_locate()
            except GardenaAuthError:
                errors["base"] = "invalid_auth"
            except GardenaError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(client.location_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"{name} (App)", data=user_input)

        # Offer the key of the official GARDENA smart system integration.
        defaults: dict[str, Any] = {}
        for entry in self.hass.config_entries.async_entries("gardena_smart_system"):
            if CONF_CLIENT_ID in entry.data:
                defaults = {k: entry.data[k] for k in (CONF_CLIENT_ID, CONF_CLIENT_SECRET) if k in entry.data}
                break
        schema = vol.Schema({
            vol.Required(CONF_CLIENT_ID, default=defaults.get(CONF_CLIENT_ID, vol.UNDEFINED)): str,
            vol.Required(CONF_CLIENT_SECRET, default=defaults.get(CONF_CLIENT_SECRET, vol.UNDEFINED)): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GardenaAppOptionsFlow()


class GardenaAppOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_SCAN_MINUTES, default=current): vol.All(int, vol.Range(min=2, max=120))}),
        )
