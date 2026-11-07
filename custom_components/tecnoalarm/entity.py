"""Shared device information for coordinator entities."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class TecnoalarmEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self.coordinator.entry.entry_id)},
                "name": f"Tecnoalarm {self.coordinator.entry.data['host']}",
                "manufacturer": "Tecnoalarm",
                "model": self.coordinator.data["panel"]["model"]}
