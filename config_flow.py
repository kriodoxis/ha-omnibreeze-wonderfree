"""Config flow for OmniBreeze Wonderfree."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_NAME, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .cloud import (
    WonderfreeCloudAuthenticationError,
    WonderfreeCloudClient,
    WonderfreeCloudConnectionError,
    WonderfreeCloudDeviceNotFoundError,
    WonderfreeCloudResponseError,
)
from .const import (
    CONF_AUTH_KEY,
    CONF_DEVICE_KEY,
    CONF_PORT,
    CONF_PRODUCT_KEY,
    CONF_REGION,
    CONF_BROADCAST_ADDRESSES,
    CONF_DEVICE_ADDRESSES,
    DEFAULT_REGION,
    DOMAIN,
    REGION_OPTIONS,
    SUPPORTED_PRODUCT_KEY,
    SUPPORTED_PRODUCT_KEYS,
)
from .models import DiscoveredDevice
from .protocol import WonderfreeClient, WonderfreeError, discover_devices

_LOGGER = logging.getLogger(__name__)


class WonderfreeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._devices: dict[str, DiscoveredDevice] = {}
        self._device: DiscoveredDevice | None = None
        self._broadcast_addresses: list[str] = []
        self._device_addresses: list[str] = []

    async def _async_get_and_validate_auth_key(
        self, email: str, password: str, region: str
    ) -> str:
        """Retrieve the key once from Wonderfree and verify local access."""
        if self._device is None:
            raise WonderfreeCloudDeviceNotFoundError
        cloud = WonderfreeCloudClient(async_get_clientsession(self.hass), region)
        auth_key = await cloud.async_get_auth_key(
            email.strip(), password, self._device.device_key
        )
        client = WonderfreeClient(self._device.host, self._device.port, auth_key)
        try:
            await client.read_status()
        finally:
            await client.disconnect()
        return auth_key

    @staticmethod
    def _account_schema(default_region: str = DEFAULT_REGION) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_REGION, default=default_region): vol.In(
                    REGION_OPTIONS
                ),
                vol.Required(CONF_EMAIL): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.EMAIL,
                        autocomplete="username",
                    )
                ),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="current-password",
                    )
                ),
            }
        )

    @staticmethod
    def _parse_ip_addresses(value: str) -> list[str]:
        """Parse and validate IPv4 addresses."""
        addresses = []
        for line in value.splitlines():
            address = line.strip()
            if not address:
                continue
            try:
                ipaddress.IPv4Address(address)
            except ValueError as err:
                raise ValueError(f"Invalid IPv4 address: {address}") from err
            addresses.append(address)
        return addresses

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        _LOGGER.debug("Recovered input: %s", user_input)
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self._discovery_schema(),
            )
        if CONF_DEVICE_KEY in user_input:
            self._device = self._devices[user_input[CONF_DEVICE_KEY]]
            await self.async_set_unique_id(self._device.device_key)
            self._abort_if_unique_id_configured(
                updates={
                    CONF_HOST: self._device.host,
                    CONF_PORT: self._device.port,
                }
            )
            return await self.async_step_account()

        try:
            broadcast_addresses = self._parse_ip_addresses(user_input.get(CONF_BROADCAST_ADDRESSES, ""))
        except ValueError:
            errors[CONF_BROADCAST_ADDRESSES] = "invalid_addresses"
            broadcast_addresses = []
        try:
            device_addresses = self._parse_ip_addresses(
                user_input.get(CONF_DEVICE_ADDRESSES, "")
            )
        except ValueError:
            errors[CONF_DEVICE_ADDRESSES] = "invalid_addresses"
            device_addresses = []

        if errors:
            return self.async_show_form(
                step_id="user",
                data_schema=self._discovery_schema(),
                errors=errors,
            )

        devices = await self.hass.async_add_executor_job(discover_devices, broadcast_addresses, device_addresses,)

        for device in devices:
            _LOGGER.debug(
                "Device %s: product_key=%s, supported=%s, supported_keys=%s",
                device.device_key,
                device.product_key,
                device.product_key in SUPPORTED_PRODUCT_KEYS,
                SUPPORTED_PRODUCT_KEYS,
            )

        self._devices = {
            device.device_key: device
            for device in devices
            if device.product_key in SUPPORTED_PRODUCT_KEYS
        }
        if not self._devices:
            return self.async_abort(reason="no_devices_found")
        options = {
            key: f"{device.name} ({device.host})"
            for key, device in self._devices.items()
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_KEY): vol.In(options)}),
        )

    @staticmethod
    def _discovery_schema() -> vol.Schema:
        return vol.Schema(
            {
                vol.Optional(CONF_BROADCAST_ADDRESSES, default=""): TextSelector(TextSelectorConfig(multiline=False)),
                vol.Optional(CONF_DEVICE_ADDRESSES, default=""): TextSelector(TextSelectorConfig(multiline=False)),
            }
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Obtain the local key using one-time Wonderfree account access."""
        errors: dict[str, str] = {}
        if user_input is not None and self._device is not None:
            try:
                auth_key = await self._async_get_and_validate_auth_key(
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_REGION],
                )
            except WonderfreeCloudAuthenticationError:
                errors["base"] = "invalid_auth"
            except WonderfreeCloudDeviceNotFoundError:
                errors["base"] = "device_not_found"
            except WonderfreeCloudResponseError:
                errors["base"] = "cloud_response_error"
            except WonderfreeCloudConnectionError:
                errors["base"] = "cloud_unavailable"
            except WonderfreeError:
                errors["base"] = "local_auth_failed"
            else:
                return self.async_create_entry(
                    title=self._device.name,
                    data={
                        CONF_NAME: self._device.name,
                        CONF_HOST: self._device.host,
                        CONF_PORT: self._device.port,
                        CONF_PRODUCT_KEY: self._device.product_key,
                        CONF_DEVICE_KEY: self._device.device_key,
                        CONF_AUTH_KEY: auth_key,
                    },
                )
        return self.async_show_form(
            step_id="account",
            data_schema=self._account_schema(
                user_input.get(CONF_REGION, DEFAULT_REGION)
                if user_input is not None
                else DEFAULT_REGION
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Start replacement of a rejected auth key."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown")
        self._device = DiscoveredDevice(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            product_key=entry.data[CONF_PRODUCT_KEY],
            device_key=entry.data[CONF_DEVICE_KEY],
            name=entry.data[CONF_NAME],
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._device is not None:
            try:
                auth_key = await self._async_get_and_validate_auth_key(
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_REGION],
                )
            except WonderfreeCloudAuthenticationError:
                errors["base"] = "invalid_auth"
            except WonderfreeCloudDeviceNotFoundError:
                errors["base"] = "device_not_found"
            except WonderfreeCloudResponseError:
                errors["base"] = "cloud_response_error"
            except WonderfreeCloudConnectionError:
                errors["base"] = "cloud_unavailable"
            except WonderfreeError:
                errors["base"] = "local_auth_failed"
            else:
                entry: ConfigEntry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_AUTH_KEY: auth_key},
                    reason="reauth_successful",
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._account_schema(
                user_input.get(CONF_REGION, DEFAULT_REGION)
                if user_input is not None
                else DEFAULT_REGION
            ),
            errors=errors,
        )
