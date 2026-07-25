"""Config and options flow for Glowmarkt."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import GlowmarktAuthError, GlowmarktClient, GlowmarktConnectionError
from .const import (
    CONF_BACKFILL_DAYS,
    DEFAULT_BACKFILL_DAYS,
    DOMAIN,
    MAX_BACKFILL_DAYS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _async_validate(hass, username: str, password: str) -> int:
    """Check the credentials work and return how many meters were found."""
    client = GlowmarktClient(async_get_clientsession(hass), username, password)
    await client.async_login()
    entities = await client.async_get_virtual_entities()
    return len(entities)


class GlowmarktConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup and reauthentication."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect Bright credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            try:
                found = await _async_validate(
                    self.hass, username, user_input[CONF_PASSWORD]
                )
            except GlowmarktAuthError:
                errors["base"] = "invalid_auth"
            except GlowmarktConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Glowmarkt credentials")
                errors["base"] = "unknown"
            else:
                if not found:
                    errors["base"] = "no_meters"
                else:
                    await self.async_set_unique_id(username.lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=username, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a fresh password for the existing account."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            username = reauth_entry.data[CONF_USERNAME]
            try:
                await _async_validate(self.hass, username, user_input[CONF_PASSWORD])
            except GlowmarktAuthError:
                errors["base"] = "invalid_auth"
            except GlowmarktConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Glowmarkt reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={
                CONF_USERNAME: reauth_entry.data[CONF_USERNAME]
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return GlowmarktOptionsFlow()


class GlowmarktOptionsFlow(OptionsFlow):
    """Lets the initial backfill depth be changed after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_BACKFILL_DAYS: int(user_input[CONF_BACKFILL_DAYS])}
            )

        current = self.config_entry.options.get(
            CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_BACKFILL_DAYS, default=current): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=MAX_BACKFILL_DAYS, mode=NumberSelectorMode.BOX
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
