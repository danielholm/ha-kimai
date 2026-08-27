"""Button platform for Kimai - start/stop timesheet."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import KimaiApiError
from .const import DOMAIN
from .coordinator import KimaiCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KimaiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            KimaiStartButton(coordinator, entry),
            KimaiRestartLastButton(coordinator, entry),
            KimaiStopButton(coordinator, entry),
        ]
    )


class _KimaiButtonBase(CoordinatorEntity[KimaiCoordinator], ButtonEntity):
    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._attr_has_entity_name = True


class KimaiStartButton(_KimaiButtonBase):
    """Starts a timesheet for whatever project is chosen in select.kimai_project."""

    _attr_name = "Starta"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_start_button"

    async def async_press(self) -> None:
        select_entity = self.hass.data[DOMAIN].get(
            f"{self._entry.entry_id}_project_select_entity"
        )
        if select_entity is None:
            raise HomeAssistantError("select.kimai_valj_projekt hittades inte")

        resolved = select_entity.selected_project_activity
        if resolved is None:
            raise HomeAssistantError("Inget projekt valt i select.kimai_valj_projekt")

        project_id, activity_id, description = resolved
        client = self.coordinator.client

        try:
            if activity_id is None:
                # Ingen manuell koppling konfigurerad via kugghjulet - använd
                # första aktiviteten Kimai returnerar för projektet.
                activities = await client.async_get_activities(project_id=project_id)
                if not activities:
                    raise HomeAssistantError(
                        "Projektet har ingen aktivitet kopplad i Kimai"
                    )
                activity_id = activities[0]["id"]
            await client.async_start_timesheet(
                project_id, activity_id, description=description
            )
        except KimaiApiError as err:
            raise HomeAssistantError(f"Kunde inte starta tidrapport: {err}") from err

        await self.coordinator.async_request_refresh()


class KimaiRestartLastButton(_KimaiButtonBase):
    """Restarts the most recent stopped record (same project + activity).

    Uses Kimai's own restart endpoint, so it picks up exactly what you last
    worked on without needing a mapping configured.
    """

    _attr_name = "Starta senaste"
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_restart_last_button"

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return super().available and bool(data and data.last_timesheet)

    async def async_press(self) -> None:
        data = self.coordinator.data
        last = data.last_timesheet if data else None
        if not last:
            raise HomeAssistantError("Ingen tidigare tidrapport hittades i Kimai")

        try:
            await self.coordinator.client.async_restart_timesheet(last["id"])
        except KimaiApiError as err:
            raise HomeAssistantError(
                f"Kunde inte starta senaste tidrapport: {err}"
            ) from err

        await self.coordinator.async_request_refresh()


class KimaiStopButton(_KimaiButtonBase):
    """Stops the currently active timesheet, if any."""

    _attr_name = "Stoppa"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_stop_button"

    async def async_press(self) -> None:
        active = self.coordinator.data.active_timesheet if self.coordinator.data else None
        if not active:
            _LOGGER.debug("Ingen aktiv tidrapport att stoppa")
            return
        try:
            await self.coordinator.client.async_stop_timesheet(active["id"])
        except KimaiApiError as err:
            raise HomeAssistantError(f"Kunde inte stoppa tidrapport: {err}") from err
        await self.coordinator.async_request_refresh()
