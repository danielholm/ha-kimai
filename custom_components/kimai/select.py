"""Select platform for Kimai - choose which project/mapping to start next."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ACTIVITY_ID,
    CONF_DESCRIPTION,
    CONF_LABEL,
    CONF_MAPPINGS,
    CONF_PROJECT_ID,
    DOMAIN,
)
from .coordinator import KimaiCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KimaiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KimaiProjectSelect(coordinator, entry)])


class KimaiProjectSelect(CoordinatorEntity[KimaiCoordinator], SelectEntity):
    """Lets the user pick what button.kimai_starta should launch.

    If manual project->activity mappings are configured via options (kugghjulet),
    the dropdown shows those custom labels and starting resolves to the exact
    project+activity pair. Otherwise it falls back to raw Kimai project names,
    and the start button picks the first activity Kimai returns for that project.
    """

    _attr_has_entity_name = True
    _attr_name = "Välj projekt"
    _attr_icon = "mdi:briefcase-outline"

    def __init__(self, coordinator: KimaiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_project_select"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._current: str | None = None
        self.hass_data_key = f"{entry.entry_id}_project_select_entity"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Let button.py find us without needing the entity registry.
        self.hass.data[DOMAIN][self.hass_data_key] = self

    @property
    def _mappings(self) -> dict[str, dict]:
        return self._entry.options.get(CONF_MAPPINGS, {})

    @property
    def options(self) -> list[str]:
        mappings = self._mappings
        if mappings:
            return [m[CONF_LABEL] for m in mappings.values()]
        if not self.coordinator.data:
            return []
        return [p["name"] for p in self.coordinator.data.projects]

    @property
    def current_option(self) -> str | None:
        options = self.options
        if self._current in options:
            return self._current
        return options[0] if options else None

    async def async_select_option(self, option: str) -> None:
        self._current = option
        self.async_write_ha_state()

    @property
    def selected_project_activity(self) -> tuple[int, int | None, str | None] | None:
        """Return (project_id, activity_id, description) for the current selection.

        activity_id is None when no manual mapping is configured - the caller
        (button.py) then falls back to the first activity Kimai returns.
        The description defaults to the label, matching the old YAML automation
        which passed the uppdrag name as the timesheet description.
        """
        mappings = self._mappings
        label = self.current_option
        if label is None:
            return None

        if mappings:
            for mapping in mappings.values():
                if mapping[CONF_LABEL] == label:
                    description = mapping.get(CONF_DESCRIPTION) or label
                    return (
                        int(mapping[CONF_PROJECT_ID]),
                        mapping[CONF_ACTIVITY_ID],
                        description,
                    )
            return None

        if not self.coordinator.data:
            return None
        for project in self.coordinator.data.projects:
            if project["name"] == label:
                return project["id"], None, None
        return None
