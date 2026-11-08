"""Direct connection configuration, authenticated before saving."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .client import Client
from .client.auth import AuthenticationError
from .const import (CONF_PERSISTENT_CONNECTION, CONF_POLLING, CONF_POLLING_INTERVAL,
                    DEFAULT_POLLING_INTERVAL, DOMAIN, MAX_POLLING_INTERVAL, polling_interval)


async def authenticate_connection(hass, entry, client):
    """Validate credentials without competing with the loaded integration."""
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        await hass.async_add_executor_job(client.authenticate)
    else:
        await coordinator.async_authenticate_for_reconfiguration(client)


def setup_schema(*, interval=DEFAULT_POLLING_INTERVAL):
    password = selector.TextSelector(selector.TextSelectorConfig(
        type=selector.TextSelectorType.PASSWORD))
    fields = {
        vol.Required("host"): str,
        vol.Required("port", default=10001): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Required("appid"): str,
        vol.Required("passphrase"): password,
        vol.Required("user_code"): password,
        vol.Required(CONF_POLLING_INTERVAL, default=interval): vol.All(
            int, vol.Range(min=0, max=MAX_POLLING_INTERVAL)),
    }
    return vol.Schema(fields)


def connection_settings(user_input, current_options):
    """Separate panel credentials from validated connection options."""
    interval = user_input.get(CONF_POLLING_INTERVAL, polling_interval(current_options))
    if type(interval) is not int or not 0 <= interval <= MAX_POLLING_INTERVAL:
        raise ValueError("Polling interval must be an integer between 0 and 600 seconds")
    legacy = (CONF_PERSISTENT_CONNECTION, CONF_POLLING)
    data = {key: value for key, value in user_input.items()
            if key not in (*legacy, CONF_POLLING_INTERVAL)}
    options = {key: value for key, value in current_options.items() if key not in legacy}
    options[CONF_POLLING_INTERVAL] = interval
    return data, options


class TecnoalarmConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TecnoalarmOptionsFlow()

    async def async_step_user(self, user_input=None):
        return await self._async_step_connection("user", user_input)

    async def async_step_reconfigure(self, user_input=None):
        return await self._async_step_connection(
            "reconfigure", user_input, self._get_reconfigure_entry())

    async def _async_step_connection(self, step_id, user_input, entry=None):
        errors = {}
        interval = polling_interval(entry.options if entry else {})
        if user_input is not None:
            try:
                data, options = connection_settings(user_input, entry.options if entry else {})
                client = Client(**data)
                await self.async_set_unique_id(
                    f"{user_input['host'].lower()}:{user_input['port']}")
                if entry is None or self.unique_id != entry.unique_id:
                    self._abort_if_unique_id_configured()
                await authenticate_connection(self.hass, entry, client)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ValueError:
                errors["base"] = "invalid_config"
            except (OSError, EOFError):
                errors["base"] = "cannot_connect"
            else:
                if entry is not None:
                    return self.async_update_reload_and_abort(
                        entry, unique_id=self.unique_id,
                        title=f"Tecnoalarm {user_input['host']}",
                        data_updates=data, options=options, reason="reconfigure_successful")
                return self.async_create_entry(title=f"Tecnoalarm {user_input['host']}",
                                               data=data, options=options)
        values = user_input if user_input is not None else {
            **(entry.data if entry else {}), CONF_POLLING_INTERVAL: interval}
        return self.async_show_form(step_id=step_id, data_schema=self.add_suggested_values_to_schema(
            setup_schema(interval=interval), values), errors=errors)


class TecnoalarmOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        interval = polling_interval(entry.options)
        errors = {}
        if user_input is not None:
            try:
                data, options = connection_settings(user_input, entry.options)
                client = Client(**data)
                unique_id = f"{data['host'].lower()}:{data['port']}"
                other = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, unique_id)
                if other is not None and other.entry_id != entry.entry_id:
                    errors["base"] = "already_configured"
                else:
                    await authenticate_connection(self.hass, entry, client)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ValueError:
                errors["base"] = "invalid_config"
            except (OSError, EOFError):
                errors["base"] = "cannot_connect"
            if not errors:
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, **data}, options=options,
                    unique_id=unique_id, title=f"Tecnoalarm {data['host']}")
                # Connection data can change while options stay the same.
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_create_entry(title="", data=options)
        values = user_input if user_input is not None else {
            **entry.data, CONF_POLLING_INTERVAL: interval}
        return self.async_show_form(step_id="init", data_schema=self.add_suggested_values_to_schema(
            setup_schema(interval=interval), values), errors=errors)
