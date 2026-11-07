"""Poll the synchronous client off the event loop."""

from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client.auth import AuthenticationError
from .const import DOMAIN


class TecnoalarmCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN,
                         config_entry=entry, update_interval=timedelta(seconds=30))
        self.client = client
        self.entry = entry
        self._keep_alive_running = False

    async def async_keep_alive(self, _now):
        if self._keep_alive_running:
            return
        self._keep_alive_running = True
        try:
            await self.hass.async_add_executor_job(self.client.keep_alive)
        except (OSError, EOFError, ValueError):
            # The client drops failed sessions; the next status poll reconnects.
            pass
        finally:
            self._keep_alive_running = False

    async def _async_update_data(self):
        try:
            return await self.hass.async_add_executor_job(self.client.read_status)
        except AuthenticationError as error:
            raise UpdateFailed("Panel authentication failed") from error
        except (OSError, EOFError, ValueError) as error:
            raise UpdateFailed("Unable to read panel status") from error
