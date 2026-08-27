"""Sensor platform for Kimai."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STATE_IDLE
from .coordinator import KimaiCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KimaiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            KimaiStatusSensor(coordinator, entry),
            KimaiElapsedSensor(coordinator, entry),
            KimaiStartedSensor(coordinator, entry),
            KimaiLastSensor(coordinator, entry),
        ]
    )


class _KimaiSensorBase(CoordinatorEntity[KimaiCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Kimai",
            manufacturer="Kimai",
            entry_type="service",
        )


class KimaiStatusSensor(_KimaiSensorBase):
    """Currently active Kimai project, or idle."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        return (data.active_project_name if data else None) or STATE_IDLE

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        ts = data.active_timesheet if data else None
        if not ts:
            return {"pagaende": False}
        return {
            "pagaende": True,
            "timesheet_id": ts.get("id"),
            "project": data.active_project_id,
            "activity": data.active_activity_id,
            "aktivitet": data.active_activity_name,
            "begin": ts.get("begin"),
            "starttid": ts.get("begin"),
            "description": ts.get("description"),
            "beskrivning": ts.get("description"),
        }


class KimaiElapsedSensor(_KimaiSensorBase):
    """Minutes elapsed in the running timesheet.

    Updates on each coordinator poll (30s). For a smooth second-by-second
    display in Lovelace, use sensor.kimai_startad with a relative-time card
    instead - that renders client-side without polling.
    """

    _attr_translation_key = "elapsed"
    _attr_icon = "mdi:timer-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_elapsed"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not data or not data.is_running:
            return 0
        return data.active_elapsed_minutes


class KimaiStartedSensor(_KimaiSensorBase):
    """Start timestamp of the running record - lets the frontend count up live."""

    _attr_translation_key = "started"
    _attr_icon = "mdi:play-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_started"

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        return data.active_begin if data else None


class KimaiLastSensor(_KimaiSensorBase):
    """What 'Starta senaste' would restart."""

    _attr_translation_key = "last"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        return (data.last_label if data else None) or "Okänt"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        ts = data.last_timesheet if data else None
        if not ts:
            return {}
        return {
            "timesheet_id": ts.get("id"),
            "projekt": data.last_label,
            "slutade": ts.get("end"),
        }
