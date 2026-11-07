"""Read-only alarm entities, one per accessible program."""

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity, AlarmControlPanelState,
)
from homeassistant.exceptions import HomeAssistantError

from .entity import TecnoalarmEntity

STATE_MAP = {
    "idle": AlarmControlPanelState.DISARMED,
    "armed": AlarmControlPanelState.ARMED_AWAY,
    "partial": AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
    "pre_exit": AlarmControlPanelState.ARMING,
    "exit": AlarmControlPanelState.ARMING,
    "partial_exit": AlarmControlPanelState.ARMING,
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    known = set()

    def add_programs():
        entities = []
        for program in coordinator.data["programs"]:
            index = program["index"]
            if index not in known:
                known.add(index)
                entities.append(TecnoalarmProgram(coordinator, index))
        if entities:
            async_add_entities(entities)

    add_programs()
    entry.async_on_unload(coordinator.async_add_listener(add_programs))


class TecnoalarmProgram(TecnoalarmEntity, AlarmControlPanelEntity):
    _attr_supported_features = 0
    _attr_code_arm_required = False
    _attr_code_format = None

    def __init__(self, coordinator, index):
        super().__init__(coordinator)
        self.index = index
        self._attr_unique_id = f"{coordinator.entry.entry_id}_program_{index}"

    @property
    def program(self):
        return next((p for p in self.coordinator.data["programs"]
                     if p["index"] == self.index), None)

    @property
    def name(self):
        return self.program["name"] if self.program else f"P{self.index + 1}"

    @property
    def available(self):
        return super().available and self.program is not None

    @property
    def alarm_state(self):
        return STATE_MAP.get(self.program["state"]) if self.program else None

    @property
    def extra_state_attributes(self):
        return {"protocol_state": self.program["state"],
                "raw_status": self.program["raw_status"],
                "program_number": self.index + 1, "provisional": True} if self.program else {}

    async def async_alarm_disarm(self, code=None):
        raise HomeAssistantError("Tecnoalarm is read-only; control actions are disabled")

    async_alarm_arm_away = async_alarm_disarm
    async_alarm_arm_home = async_alarm_disarm
    async_alarm_arm_night = async_alarm_disarm
    async_alarm_arm_vacation = async_alarm_disarm
    async_alarm_arm_custom_bypass = async_alarm_disarm
    async_alarm_trigger = async_alarm_disarm
