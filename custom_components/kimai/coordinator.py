"""DataUpdateCoordinator for Kimai."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import KimaiApiClient, KimaiApiError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)



def _name_of(value: Any, lookup: list[dict[str, Any]] | None = None) -> str | None:
    """Kimai returns either a nested object or a bare ID depending on version."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("name")
    if lookup:
        for item in lookup:
            if item.get("id") == value:
                return item.get("name")
    return str(value)


def _id_of(timesheet: dict[str, Any] | None, key: str) -> int | None:
    """Extract a numeric ID whether Kimai returns an object or a bare ID."""
    if not timesheet:
        return None
    value = timesheet.get(key)
    if isinstance(value, dict):
        return value.get("id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _activity_project_id(activity: dict[str, Any]) -> int | None:
    """Global activities have no project; project-bound ones do."""
    value = activity.get("project")
    if isinstance(value, dict):
        return value.get("id")
    if isinstance(value, int):
        return value
    return None


def _resolve(value: Any, items: list[dict[str, Any]]) -> int | None:
    """Resolve an ID or a name (case-insensitive) to a numeric ID."""
    if value is None:
        return None
    # Already an ID?
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    # Exact match first, then case-insensitive.
    for item in items:
        if item.get("name") == text:
            return item.get("id")
    lowered = text.casefold()
    for item in items:
        name = item.get("name")
        if isinstance(name, str) and name.casefold() == lowered:
            return item.get("id")
    return None


@dataclass
class KimaiData:
    """Snapshot of Kimai state used by all entities."""

    active_timesheets: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    recent_timesheets: list[dict[str, Any]] = field(default_factory=list)
    activities: list[dict[str, Any]] = field(default_factory=list)

    @property
    def active_timesheet(self) -> dict[str, Any] | None:
        return self.active_timesheets[0] if self.active_timesheets else None

    @property
    def is_running(self) -> bool:
        return bool(self.active_timesheets)

    @property
    def active_project_name(self) -> str | None:
        ts = self.active_timesheet
        if not ts:
            return None
        return _name_of(ts.get("project"), self.projects)

    @property
    def active_activity_name(self) -> str | None:
        ts = self.active_timesheet
        if not ts:
            return None
        return _name_of(ts.get("activity"), self.activities)

    @property
    def active_project_id(self) -> int | None:
        return _id_of(self.active_timesheet, "project")

    @property
    def active_activity_id(self) -> int | None:
        return _id_of(self.active_timesheet, "activity")

    @property
    def active_begin(self) -> datetime | None:
        """Start time of the running record, as an aware datetime."""
        ts = self.active_timesheet
        if not ts or not ts.get("begin"):
            return None
        parsed = dt_util.parse_datetime(ts["begin"])
        if parsed is None:
            return None
        # Kimai returns ISO 8601 with offset, but be defensive.
        return dt_util.as_utc(parsed) if parsed.tzinfo else dt_util.as_utc(
            parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        )

    @property
    def active_elapsed_minutes(self) -> float | None:
        begin = self.active_begin
        if begin is None:
            return None
        delta = dt_util.utcnow() - begin
        return round(delta.total_seconds() / 60, 1)

    def resolve_project(self, value: str | int) -> int | None:
        """Accept a project ID or a project name and return the ID."""
        return _resolve(value, self.projects)

    def resolve_activity(
        self, value: str | int, project_id: int | None = None
    ) -> int | None:
        """Accept an activity ID or name and return the ID.

        When project_id is given, activities belonging to that project win over
        identically named ones elsewhere (activity names are not unique in
        Kimai - several projects often have an activity called e.g. "Möte").
        """
        if project_id is not None:
            scoped = [
                a
                for a in self.activities
                if _activity_project_id(a) in (project_id, None)
            ]
            found = _resolve(value, scoped)
            if found is not None:
                return found
        return _resolve(value, self.activities)

    def resolve_project_name(self, project_id: int) -> str | None:
        """Reverse lookup: ID -> project name."""
        for project in self.projects:
            if project.get("id") == project_id:
                return project.get("name")
        return None

    @property
    def last_timesheet(self) -> dict[str, Any] | None:
        """Most recent stopped record - what 'Starta senaste' will restart."""
        return self.recent_timesheets[0] if self.recent_timesheets else None

    @property
    def last_label(self) -> str | None:
        ts = self.last_timesheet
        if not ts:
            return None
        project = _name_of(ts.get("project"), self.projects)
        activity = _name_of(ts.get("activity"), self.activities)
        if project and activity:
            return f"{project} / {activity}"
        return project or activity


class KimaiCoordinator(DataUpdateCoordinator[KimaiData]):
    """Polls Kimai for active timesheet, recent records and project list."""

    def __init__(self, hass: HomeAssistant, client: KimaiApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self._projects: list[dict[str, Any]] = []
        self._activities: list[dict[str, Any]] = []
        self._static_fetched_at: datetime | None = None

    async def _async_update_data(self) -> KimaiData:
        # Projekt och aktiviteter hämtas bara en gång - vid inladdning av
        # integrationen (uppstart, omstart, reload) eller när användaren
        # aktivt begär det via kugghjulet. De ändras sällan nog att det inte
        # är värt återkommande anrop.
        first_load = self._static_fetched_at is None

        try:
            if first_load:
                active, recent, projects, activities = await asyncio.gather(
                    self.client.async_get_active_timesheets(),
                    self.client.async_get_recent_timesheets(size=5),
                    self.client.async_get_projects(),
                    self.client.async_get_activities(),
                )
                self._projects = projects
                self._activities = activities
                self._static_fetched_at = dt_util.utcnow()
            else:
                active, recent = await asyncio.gather(
                    self.client.async_get_active_timesheets(),
                    self.client.async_get_recent_timesheets(size=5),
                )
        except KimaiApiError as err:
            raise UpdateFailed(f"Fel vid hämtning från Kimai: {err}") from err

        return KimaiData(
            active_timesheets=active,
            projects=self._projects,
            recent_timesheets=recent,
            activities=self._activities,
        )

    @property
    def static_fetched_at(self) -> datetime | None:
        """When projects/activities were last loaded from Kimai."""
        return self._static_fetched_at

    async def async_refresh_static(self) -> None:
        """Refetch projects and activities from Kimai.

        Called from the options flow when the user picks "Ladda om projekt".
        Needed after adding or renaming projects in Kimai, since the lists are
        otherwise only loaded when the integration starts.
        """
        self._static_fetched_at = None
        await self.async_refresh()
