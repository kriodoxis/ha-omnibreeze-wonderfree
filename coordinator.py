"""Coordinator for OmniBreeze Wonderfree."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AUTH_KEY,
    CONF_DEVICE_KEY,
    CONF_PORT,
    DOMAIN,
    UPDATE_INTERVAL,
)
from .models import FanStatus
from .protocol import (
    WonderfreeAuthenticationError,
    WonderfreeClient,
    WonderfreeConnectionError,
    WonderfreeError,
    discover_devices,
)

_LOGGER = logging.getLogger(__name__)


class WonderfreeCoordinator(DataUpdateCoordinator[FanStatus]):
    """Coordinate one local fan."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.device_name = entry.data[CONF_NAME]
        self.client = WonderfreeClient(
            entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_AUTH_KEY]
        )
        self._consecutive_failures = 0
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.unique_id}",
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )

    async def _async_update_data(self) -> FanStatus:
        try:
            status = await self.client.read_status()
        except WonderfreeAuthenticationError as err:
            raise ConfigEntryAuthFailed("OmniBreeze auth key was rejected") from err
        except WonderfreeConnectionError as err:
            if await self._async_refresh_network_location():
                try:
                    status = await self.client.read_status()
                except WonderfreeAuthenticationError as retry_err:
                    raise ConfigEntryAuthFailed(
                        "OmniBreeze auth key was rejected"
                    ) from retry_err
                except WonderfreeError as retry_err:
                    raise UpdateFailed(
                        "Error communicating with OmniBreeze after rediscovery: "
                        f"{retry_err}"
                    ) from retry_err
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures < 2 and self.data is not None:
                    _LOGGER.warning("Transient OmniBreeze communication failure: %s", err)
                    return self.data
                raise UpdateFailed(f"Error communicating with OmniBreeze: {err}") from err
        except WonderfreeError as err:
            self._consecutive_failures += 1
            if self._consecutive_failures < 2 and self.data is not None:
                _LOGGER.warning("Transient OmniBreeze communication failure: %s", err)
                return self.data
            raise UpdateFailed(f"Error communicating with OmniBreeze: {err}") from err
        self._consecutive_failures = 0
        return status

    async def _async_refresh_network_location(self) -> bool:
        """Rediscover this fan and update its stored address when it changed."""
        devices = await self.hass.async_add_executor_job(discover_devices)
        device = next(
            (
                candidate
                for candidate in devices
                if candidate.device_key == self.entry.data[CONF_DEVICE_KEY]
            ),
            None,
        )
        if device is None:
            return False

        current_host = self.entry.data[CONF_HOST]
        current_port = self.entry.data[CONF_PORT]
        if (device.host, device.port) != (current_host, current_port):
            _LOGGER.info(
                "OmniBreeze device %s moved from %s:%s to %s:%s",
                device.device_key,
                current_host,
                current_port,
                device.host,
                device.port,
            )
            await self.client.disconnect()
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={
                    **self.entry.data,
                    CONF_HOST: device.host,
                    CONF_PORT: device.port,
                },
            )
            self.client = WonderfreeClient(
                device.host, device.port, self.entry.data[CONF_AUTH_KEY]
            )
        return True

    async def async_write(self, *values: tuple[int, bool | int]) -> None:
        try:
            status = await self.client.write(values)
        except WonderfreeConnectionError as err:
            if not await self._async_refresh_network_location():
                raise UpdateFailed(
                    f"Error writing OmniBreeze state: {err}"
                ) from err
            try:
                status = await self.client.write(values)
            except WonderfreeAuthenticationError as retry_err:
                raise ConfigEntryAuthFailed(
                    "OmniBreeze auth key was rejected"
                ) from retry_err
            except WonderfreeError as retry_err:
                raise UpdateFailed(
                    "Error writing OmniBreeze state after rediscovery: "
                    f"{retry_err}"
                ) from retry_err
        except WonderfreeError as err:
            raise UpdateFailed(f"Error writing OmniBreeze state: {err}") from err
        self.async_set_updated_data(status)

    async def async_shutdown(self) -> None:
        await self.client.disconnect()
