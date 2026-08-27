"""Binary sensor platform for Kimai."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KimaiCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KimaiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KimaiActiveBinarySensor(coordinator, entry)])


class KimaiActiveBinarySensor(CoordinatorEntity[KimaiCoordinator], BinarySensorEntity):
    """Whether a timesheet is currently running.

    Replaces the template binary sensor that derived this from a raw REST
    project-ID sensor.
    """

    _attr_has_entity_name = True
    _attr_name = "Aktivt"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_active"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        return bool(data and data.is_running)

    @property
    def icon(self) -> str:
        return "mdi:clock-check" if self.is_on else "mdi:clock-off"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data or not data.is_running:
            return {}
        return {
            "project": data.active_project_id,
            "activity": data.active_activity_id,
            "projekt_namn": data.active_project_name,
            "aktivitet_namn": data.active_activity_name,
        }
