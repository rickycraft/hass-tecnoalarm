"""Small HA API doubles for offline scaffold tests; these do not validate HA itself."""

from enum import StrEnum
from types import ModuleType
from unittest.mock import MagicMock


class HomeAssistantError(Exception):
    pass


class UpdateFailed(Exception):
    pass


class AlarmControlPanelState(StrEnum):
    DISARMED = "disarmed"
    ARMED_AWAY = "armed_away"
    ARMED_CUSTOM_BYPASS = "armed_custom_bypass"
    ARMING = "arming"


class ConfigFlow:
    def __init_subclass__(cls, **kwargs):
        pass

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def add_suggested_values_to_schema(self, schema, suggested_values):
        return schema

    def _get_reconfigure_entry(self):
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    def async_update_reload_and_abort(self, entry, **kwargs):
        self.hass.config_entries.async_update_entry(entry, **{
            key: value for key, value in kwargs.items() if key in ("unique_id", "title")
        }, data={**entry.data, **kwargs.get("data_updates", {})})
        self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return {"type": "abort", "reason": kwargs["reason"]}


class DataUpdateCoordinator:
    def __init__(self, hass, logger, **kwargs):
        self.hass = hass
        self.data = None
        self.last_update_success = True
        self.update_interval = kwargs["update_interval"]
        self.listeners = []

    def async_add_listener(self, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


def modules():
    def module(name, **attrs):
        value = ModuleType(name)
        value.__dict__.update(attrs)
        return value

    config_entries = module("homeassistant.config_entries", ConfigFlow=ConfigFlow,
                            OptionsFlow=type("OptionsFlow", (ConfigFlow,), {}),
                            OptionsFlowWithReload=type("OptionsFlowWithReload", (ConfigFlow,), {}))
    return {
        "homeassistant": module("homeassistant", config_entries=config_entries),
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": module("homeassistant.core", callback=lambda func: func),
        "homeassistant.components": module("homeassistant.components"),
        "homeassistant.components.alarm_control_panel": module(
            "homeassistant.components.alarm_control_panel", AlarmControlPanelEntity=type("Alarm", (), {}),
            AlarmControlPanelState=AlarmControlPanelState),
        "homeassistant.components.binary_sensor": module(
            "homeassistant.components.binary_sensor", BinarySensorEntity=type("Sensor", (), {}),
            BinarySensorDeviceClass=type("DeviceClass", (), {"PROBLEM": "problem"})),
        "homeassistant.exceptions": module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError),
        "homeassistant.helpers": module("homeassistant.helpers"),
        "homeassistant.helpers.event": module(
            "homeassistant.helpers.event", async_track_time_interval=MagicMock()),
        "homeassistant.helpers.update_coordinator": module(
            "homeassistant.helpers.update_coordinator", DataUpdateCoordinator=DataUpdateCoordinator,
            UpdateFailed=UpdateFailed, CoordinatorEntity=CoordinatorEntity),
        "homeassistant.helpers.selector": module(
            "homeassistant.helpers.selector", TextSelector=lambda config: config,
            TextSelectorConfig=dict, TextSelectorType=type("TextType", (), {"PASSWORD": "password"})),
        "voluptuous": module("voluptuous", Schema=lambda fields: fields,
                             Required=lambda key, **kw: key, All=lambda *args: args,
                             Coerce=lambda kind: kind, Range=lambda **kw: kw),
    }
