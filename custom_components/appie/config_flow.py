"""Config flow: log in on login.ah.nl and paste the appie://login-exit link."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .api import AppieAuthError, AppieError, exchange_code, extract_code, member_id
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_FAVORITES_COUNT,
    CONF_FAVORITES_DAYS,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    FAVORITES_COUNT,
    FAVORITES_COUNT_RANGE,
    FAVORITES_DAYS,
    FAVORITES_DAYS_RANGE,
    LOGIN_URL,
)

_LOGGER = logging.getLogger(__name__)

CONF_LOGIN_LINK = "login_link"
SCHEMA = vol.Schema({vol.Required(CONF_LOGIN_LINK): str})


class AppieConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the login."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AppieOptionsFlow:
        return AppieOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, error = await self._login(user_input[CONF_LOGIN_LINK])
            if tokens:
                await self.async_set_unique_id(member_id(tokens["access_token"]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Albert Heijn", data=_entry_data(tokens))
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"login_url": LOGIN_URL},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, error = await self._login(user_input[CONF_LOGIN_LINK])
            if tokens:
                await self.async_set_unique_id(member_id(tokens["access_token"]))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=_entry_data(tokens)
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"login_url": LOGIN_URL},
        )

    async def _login(self, link: str) -> tuple[dict[str, Any] | None, str]:
        try:
            code = extract_code(link)
        except ValueError:
            return None, "invalid_link"
        try:
            return await exchange_code(async_get_clientsession(self.hass), code), ""
        except AppieAuthError:
            return None, "code_expired"
        except AppieError:
            _LOGGER.exception("login failed")
            return None, "cannot_connect"


def _number(low: int, high: int, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=low, max=high, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=unit)
    )


class AppieOptionsFlow(OptionsFlowWithReload):
    """How many "vaak gekocht" products, counted over how many days.

    Saving reloads the entry, so changes apply without a restart.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={key: int(value) for key, value in user_input.items()}
            )
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_FAVORITES_COUNT, default=options.get(CONF_FAVORITES_COUNT, FAVORITES_COUNT)
                ): _number(*FAVORITES_COUNT_RANGE, "producten"),
                vol.Required(
                    CONF_FAVORITES_DAYS, default=options.get(CONF_FAVORITES_DAYS, FAVORITES_DAYS)
                ): _number(*FAVORITES_DAYS_RANGE, "dagen"),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


def _entry_data(tokens: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_ACCESS_TOKEN: tokens["access_token"],
        CONF_REFRESH_TOKEN: tokens["refresh_token"],
        CONF_EXPIRES_AT: tokens["expires_at"],
    }
