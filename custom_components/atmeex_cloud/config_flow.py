import logging

import voluptuous as vol
from atmeexpy.client import AtmeexClient

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_PASSWORD, CONF_EMAIL
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
from .const import DOMAIN, CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN

_LOGGER = logging.getLogger(__name__)

CONF_PHONE = "phone"
CONF_PHONE_CODE = "phone_code"
CONF_AUTH_METHOD = "auth_method"

AUTH_METHOD_EMAIL = "email"
AUTH_METHOD_PHONE = "phone"


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AUTH_METHOD, default=AUTH_METHOD_EMAIL): SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": AUTH_METHOD_EMAIL, "label": "email"},
                    {"value": AUTH_METHOD_PHONE, "label": "phone"},
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


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for atmeex cloud."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._phone: str = ""
        self._client: AtmeexClient | None = None

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
            try:
                client = AtmeexClient()
                await client.signin_with_email(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
                devices = await client.get_devices()

                if len(devices) == 0:
                    errors["base"] = "no_devices"
                else:
                    data = {
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_ACCESS_TOKEN: client.auth._access_token,
                        CONF_REFRESH_TOKEN: client.auth._refresh_token,
                    }
                    return self.async_create_entry(
                        title=user_input[CONF_EMAIL],
                        data=data,
                    )
            except Exception as exc:
                _LOGGER.exception("Email authentication failed")
                errors["base"] = "auth"

        return self.async_show_form(
            step_id="email", data_schema=STEP_EMAIL_DATA_SCHEMA, errors=errors
        )

    async def async_step_phone(self, user_input=None):
        """Handle phone number input and send SMS code."""
        errors = {}

        if user_input is not None:
            try:
                self._phone = user_input[CONF_PHONE]
                self._client = AtmeexClient()
                await self._client.request_sms_code(self._phone)
                return await self.async_step_phone_code()
            except Exception as exc:
                _LOGGER.exception("Failed to send SMS code")
                errors["base"] = "sms_send_failed"

        return self.async_show_form(
            step_id="phone", data_schema=STEP_PHONE_DATA_SCHEMA, errors=errors
        )

    async def async_step_phone_code(self, user_input=None):
        """Handle SMS code verification."""
        errors = {}

        if user_input is not None:
            try:
                await self._client.signin_with_phone(
                    self._phone, user_input[CONF_PHONE_CODE]
                )
                devices = await self._client.get_devices()

                if len(devices) == 0:
                    errors["base"] = "no_devices"
                else:
                    data = {
                        CONF_PHONE: self._phone,
                        CONF_ACCESS_TOKEN: self._client.auth._access_token,
                        CONF_REFRESH_TOKEN: self._client.auth._refresh_token,
                    }
                    return self.async_create_entry(
                        title=self._phone,
                        data=data,
                    )
            except Exception as exc:
                _LOGGER.exception("Phone authentication failed")
                errors["base"] = "invalid_code"

        return self.async_show_form(
            step_id="phone_code",
            data_schema=STEP_PHONE_CODE_DATA_SCHEMA,
            errors=errors
        )
