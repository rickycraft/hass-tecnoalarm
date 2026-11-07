"""Panel-wide indicators, independent of program arming states."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import TecnoalarmEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([TecnoalarmPanelSensor(entry.runtime_data, key)
                        for key in ("alarm", "fault")])


class TecnoalarmPanelSensor(TecnoalarmEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self.key = key
        self._attr_name = f"Panel {key}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_panel_{key}"

    @property
    def is_on(self):
        return self.coordinator.data["panel"][self.key]

    @property
    def extra_state_attributes(self):
        return {"raw_status": self.coordinator.data["panel"]["raw_status"],
                "provisional": True}
