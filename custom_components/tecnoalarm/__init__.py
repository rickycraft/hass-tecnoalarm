"""Read-only Tecnoalarm integration; the client can also be imported without HA."""

PLATFORMS = ["alarm_control_panel", "binary_sensor"]


async def async_setup_entry(hass, entry):
    from datetime import timedelta
    from homeassistant.helpers.event import async_track_time_interval

    from .client import Client
    from .coordinator import TecnoalarmCoordinator
    from .const import CONF_PERSISTENT_CONNECTION

    persistent = entry.options.get(CONF_PERSISTENT_CONNECTION, True)
    client = Client(**entry.data, persistent_connection=persistent)
    coordinator = TecnoalarmCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        if persistent:
            entry.async_on_unload(async_track_time_interval(
                hass, coordinator.async_keep_alive, timedelta(seconds=5)))
    except BaseException:
        await hass.async_add_executor_job(client.close)
        raise
    return True


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.async_add_executor_job(entry.runtime_data.client.close)
    return unloaded
