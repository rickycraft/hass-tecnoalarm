"""Poll the synchronous client off the event loop."""

import asyncio
from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client.auth import AuthenticationError
from .const import DEFAULT_POLLING_INTERVAL, DOMAIN, polling_interval


class TecnoalarmCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN,
                         config_entry=entry, update_interval=timedelta(
                             seconds=polling_interval(entry.options) or DEFAULT_POLLING_INTERVAL))
        self.client = client
        self.entry = entry
        self._keep_alive_running = False
        self._connection_lock = asyncio.Lock()
        self._reconfiguring = False

    async def async_authenticate_for_reconfiguration(self, client):
        """Release the active session and pause panel traffic until reload."""
        async with self._connection_lock:
            self._reconfiguring = True

            async def authenticate():
                await self.hass.async_add_executor_job(self.client.disconnect)
                await self.hass.async_add_executor_job(client.authenticate)

            task = asyncio.create_task(authenticate())
            try:
                # An executor job keeps running if its flow is cancelled. Wait for
                # it to release the panel before allowing background traffic again.
                await asyncio.shield(task)
            except BaseException:
                try:
                    await asyncio.gather(task, return_exceptions=True)
                finally:
                    self._reconfiguring = False
                raise

    async def async_keep_alive(self, _now):
        if self._keep_alive_running:
            return
        self._keep_alive_running = True
        try:
            async with self._connection_lock:
                if not self._reconfiguring:
                    await self.hass.async_add_executor_job(self.client.keep_alive)
        except (OSError, EOFError, ValueError):
            # The client drops failed sessions; the next status poll reconnects.
            pass
        finally:
            self._keep_alive_running = False

    async def _async_update_data(self):
        try:
            async with self._connection_lock:
                if self._reconfiguring:
                    return self.data
                return await self.hass.async_add_executor_job(self.client.read_status)
        except AuthenticationError as error:
            raise UpdateFailed("Panel authentication failed") from error
        except (OSError, EOFError, ValueError) as error:
            raise UpdateFailed("Unable to read panel status") from error
