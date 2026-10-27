import logging
from typing import Any

import voluptuous as vol
import httpx
from atmeexpy.client import AtmeexClient
from atmeexpy.exceptions import AtmeexAuthError

from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlowWithReload, SOURCE_REAUTH
from homeassistant.const import CONF_PASSWORD, CONF_EMAIL
from homeassistant.core import callback
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
from .const import DOMAIN, CONF_ACCESS_TOKEN, CONF_CLOUD_RELAY, CONF_LOCAL_SERVER, CONF_REFRESH_TOKEN

_LOGGER = logging.getLogger(__name__)

CONF_PHONE = "phone"
CONF_PHONE_CODE = "phone_code"
CONF_AUTH_METHOD = "auth_method"

AUTH_METHOD_EMAIL = "auth_method_email"
AUTH_METHOD_PHONE = "auth_method_phone"


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AUTH_METHOD, default=AUTH_METHOD_EMAIL): SelectSelector(
            SelectSelectorConfig(
                options=[
                    AUTH_METHOD_EMAIL,
                    AUTH_METHOD_PHONE,
                ],
                mode=SelectSelectorMode.LIST,
                translation_key="auth_method",
            )
        ),
    }
)



STEP_EMAIL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    },
)

STEP_PHONE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PHONE): str,
    },
)

STEP_PHONE_CODE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PHONE_CODE): str,
    },
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LOCAL_SERVER, default=False): bool,
        vol.Required(CONF_CLOUD_RELAY, default=True): bool,
    },
)


async def _async_has_devices(client: AtmeexClient) -> bool:
    # client.get_devices() returns nothing when a device lacks a field atmeexpy requires,
    # and the cloud stopped sending some of them in October 2026
    resp = await client.http_client.get("/devices")
    resp.raise_for_status()
    return len(resp.json()) > 0


class AtmeexConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for atmeex cloud."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._phone: str = ""
        self._client: AtmeexClient | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "AtmeexOptionsFlow":
        return AtmeexOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Handle the initial step - select auth method."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        if user_input[CONF_AUTH_METHOD] == AUTH_METHOD_EMAIL:
            return await self.async_step_email()
        else:
            return await self.async_step_phone()

    async def async_step_email(self, user_input=None):
        """Handle email authentication."""
        errors = {}

        if user_input is not None:
            http_client = create_async_httpx_client(self.hass)
            client = AtmeexClient(http_client)
            try:
                await client.signin_with_email(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
                if not await _async_has_devices(client):
                    errors["base"] = "no_devices"
                else:
                    data = {
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_ACCESS_TOKEN: client.access_token,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                    }
                    await self.async_set_unique_id(user_input[CONF_EMAIL])
                    if self.source == SOURCE_REAUTH:
                        self._abort_if_unique_id_mismatch()
                        return self.async_update_reload_and_abort(
                            self._get_reauth_entry(),
                            data_updates=data,
                        )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user_input[CONF_EMAIL],
                        data=data,
                    )
            except (AtmeexAuthError, httpx.HTTPStatusError) as exc:
                _LOGGER.exception("Email authentication failed")
                errors["base"] = "auth"
            except httpx.TransportError as err:
                _LOGGER.warning("Atmeex cloud unavailable: %s %s", type(err).__name__, err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="email", data_schema=STEP_EMAIL_DATA_SCHEMA, errors=errors
        )

    async def async_step_phone(self, user_input=None):
        """Handle phone number input and send SMS code."""
        errors = {}

        if user_input is not None:
            try:
                self._phone = user_input[CONF_PHONE]
                http_client = create_async_httpx_client(self.hass)
                self._client = AtmeexClient(http_client)
                await self._client.request_sms_code(self._phone)
                return await self.async_step_phone_code()
            except (AtmeexAuthError, httpx.HTTPStatusError) as exc:
                _LOGGER.exception("Failed to send SMS code")
                errors["base"] = "sms_send_failed"
            except httpx.TransportError as err:
                _LOGGER.warning("Atmeex cloud unavailable: %s %s", type(err).__name__, err)
                errors["base"] = "cannot_connect"

        return self._show_phone_form(errors)

    def _show_phone_form(self, errors: dict):
        return self.async_show_form(
            step_id="phone",
            data_schema=self.add_suggested_values_to_schema(STEP_PHONE_DATA_SCHEMA, {CONF_PHONE: self._phone}),
            errors=errors,
        )

    async def async_step_phone_code(self, user_input=None):
        """Handle SMS code verification."""
        errors = {}

        if user_input is not None:
            try:
                await self._client.signin_with_phone(
                    self._phone, user_input[CONF_PHONE_CODE]
                )
                if not await _async_has_devices(self._client):
                    errors["base"] = "no_devices"
                else:
                    data = {
                        CONF_PHONE: self._phone,
                        CONF_ACCESS_TOKEN: self._client.access_token,
                        CONF_REFRESH_TOKEN: self._client.refresh_token,
                    }
                    await self.async_set_unique_id(self._phone)
                    if self.source == SOURCE_REAUTH:
                        self._abort_if_unique_id_mismatch()
                        return self.async_update_reload_and_abort(
                            self._get_reauth_entry(),
                            data_updates=data,
                        )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=self._phone,
                        data=data,
                    )
            except (AtmeexAuthError, httpx.HTTPStatusError) as exc:
                _LOGGER.exception("Phone authentication failed")
                errors["base"] = "invalid_code"
            except httpx.TransportError as err:
                _LOGGER.warning("Atmeex cloud unavailable: %s %s", type(err).__name__, err)
                errors["base"] = "cannot_connect"

        # A code works once and the form has no resend button: sending the number again brings a new SMS
        if errors.get("base") in ("invalid_code", "no_devices"):
            return self._show_phone_form(errors)

        return self.async_show_form(
            step_id="phone_code",
            data_schema=STEP_PHONE_CODE_DATA_SCHEMA,
            errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Handle re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Handle re-auth confirmation - redirect to appropriate auth method."""
        if user_input is not None:
            entry = self._get_reauth_entry()
            if CONF_EMAIL in entry.data:
                return await self.async_step_email()
            else:
                return await self.async_step_phone()

        entry = self._get_reauth_entry()
        if CONF_EMAIL in entry.data:
            account = entry.data[CONF_EMAIL]
        elif CONF_PHONE in entry.data:
            account = entry.data[CONF_PHONE]
        else:
            account = ""

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"account": account},
        )


class AtmeexOptionsFlow(OptionsFlowWithReload):
    """Handle options."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, self.config_entry.options),
        )
