"""Direct connection configuration, authenticated before saving."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .client import Client
from .client.auth import AuthenticationError
from .const import CONF_PERSISTENT_CONNECTION, DOMAIN


def setup_schema(*, persistent_connection=None):
    password = selector.TextSelector(selector.TextSelectorConfig(
        type=selector.TextSelectorType.PASSWORD))
    fields = {
        vol.Required("host"): str,
        vol.Required("port", default=10001): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Required("appid"): str,
        vol.Required("passphrase"): password,
        vol.Required("user_code"): password,
    }
    if persistent_connection is not None:
        fields[vol.Required(CONF_PERSISTENT_CONNECTION, default=persistent_connection)] = bool
    return vol.Schema(fields)


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
        if user_input is not None:
            try:
                client = Client(**user_input)
                await self.async_set_unique_id(
                    f"{user_input['host'].lower()}:{user_input['port']}")
                if entry is None or self.unique_id != entry.unique_id:
                    self._abort_if_unique_id_configured()
                await self.hass.async_add_executor_job(client.authenticate)
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
                        data_updates=user_input, reason="reconfigure_successful")
                return self.async_create_entry(title=f"Tecnoalarm {user_input['host']}",
                                               data=user_input)
        values = user_input if user_input is not None else (entry.data if entry else {})
        return self.async_show_form(step_id=step_id, data_schema=self.add_suggested_values_to_schema(
            setup_schema(), values), errors=errors)


class TecnoalarmOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        persistent = entry.options.get(CONF_PERSISTENT_CONNECTION, True)
        errors = {}
        if user_input is not None:
            data = {key: value for key, value in user_input.items()
                    if key != CONF_PERSISTENT_CONNECTION}
            try:
                client = Client(**data)
                unique_id = f"{data['host'].lower()}:{data['port']}"
                other = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, unique_id)
                if other is not None and other.entry_id != entry.entry_id:
                    errors["base"] = "already_configured"
                else:
                    await self.hass.async_add_executor_job(client.authenticate)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ValueError:
                errors["base"] = "invalid_config"
            except (OSError, EOFError):
                errors["base"] = "cannot_connect"
            if not errors:
                options = {**entry.options, CONF_PERSISTENT_CONNECTION:
                           user_input[CONF_PERSISTENT_CONNECTION]}
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, **data}, options=options,
                    unique_id=unique_id, title=f"Tecnoalarm {data['host']}")
                # Connection data can change while options stay the same.
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_create_entry(title="", data=options)
        values = user_input if user_input is not None else {
            **entry.data, CONF_PERSISTENT_CONNECTION: persistent}
        return self.async_show_form(step_id="init", data_schema=self.add_suggested_values_to_schema(
            setup_schema(persistent_connection=persistent), values), errors=errors)
