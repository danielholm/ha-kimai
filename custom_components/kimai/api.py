"""Thin async client for the Kimai REST API.

Kimai API docs: https://www.kimai.org/documentation/rest-api.html
Auth: Bearer token created under user profile -> API access.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout

from .const import DEFAULT_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class KimaiApiError(Exception):
    """Raised when the Kimai API returns an error."""


class KimaiAuthError(KimaiApiError):
    """Raised when authentication fails (401/403)."""


class KimaiApiClient:
    """Small wrapper around the Kimai REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        api_token: str,
        verify_ssl: bool = True,
    ) -> None:
        self._session = session
        self._host = host.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._verify_ssl = verify_ssl

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> Any:
        url = f"{self._host}{path}"
        try:
            async with async_timeout.timeout(DEFAULT_TIMEOUT):
                async with self._session.request(
                    method,
                    url,
                    headers=self._headers,
                    json=json,
                    ssl=self._verify_ssl,
                ) as resp:
                    if resp.status in (401, 403):
                        raise KimaiAuthError(
                            f"Kimai-autentisering misslyckades ({resp.status})"
                        )
                    if resp.status >= 400:
                        # Svarets body kan innehålla projekt-, kund- eller
                        # användardata. Den hör hemma i debugloggen - inte i
                        # felmeddelandet, som syns i UI:t och hamnar i loggar
                        # som folk klistrar in i buggrapporter.
                        body = await resp.text()
                        _LOGGER.debug(
                            "Kimai svarade %s på %s: %s", resp.status, path, body[:500]
                        )
                        raise KimaiApiError(
                            f"Kimai API-fel {resp.status} för {path}"
                        )
                    if resp.status == 204:
                        return None
                    return await resp.json()
        except aiohttp.ClientError as err:
            raise KimaiApiError(f"Kunde inte nå Kimai på {url}: {err}") from err

    async def async_get_version(self) -> dict[str, Any]:
        """Used by config_flow to validate host + token."""
        return await self._request("GET", "/api/version")

    async def async_get_active_timesheets(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "/api/timesheets/active")
        return result or []

    async def async_get_recent_timesheets(self, size: int = 5) -> list[dict[str, Any]]:
        """Recent (stopped) activities for the current user, newest first."""
        result = await self._request("GET", f"/api/timesheets/recent?size={size}")
        return result or []

    async def async_restart_timesheet(self, timesheet_id: int) -> dict[str, Any]:
        """Restart a previously stopped record (same customer/project/activity)."""
        return await self._request(
            "PATCH", f"/api/timesheets/{timesheet_id}/restart", json={}
        )

    async def async_get_projects(self) -> list[dict[str, Any]]:
        result = await self._request("GET", "/api/projects?visible=1")
        return result or []

    async def async_get_activities(self, project_id: int | None = None) -> list[dict[str, Any]]:
        path = "/api/activities?visible=1"
        if project_id is not None:
            path += f"&project={project_id}"
        result = await self._request("GET", path)
        return result or []

    async def async_start_timesheet(
        self,
        project_id: int,
        activity_id: int,
        description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"project": project_id, "activity": activity_id}
        if description:
            payload["description"] = description
        return await self._request("POST", "/api/timesheets", json=payload)

    async def async_stop_timesheet(self, timesheet_id: int) -> dict[str, Any]:
        return await self._request("PATCH", f"/api/timesheets/{timesheet_id}/stop")
