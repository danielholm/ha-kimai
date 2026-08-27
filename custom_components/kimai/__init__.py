"""The Kimai integration."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KimaiApiClient, KimaiApiError
from .const import (
    ATTR_ACTIVITY,
    ATTR_ACTIVITY_ID,
    ATTR_DESCRIPTION,
    ATTR_PROJECT,
    ATTR_PROJECT_ID,
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_VERIFY_SSL,
    DOMAIN,
    SERVICE_RESTART_LAST,
    SERVICE_START_BY_NAME,
    SERVICE_START_TIMESHEET,
    SERVICE_STOP_TIMESHEET,
)
from .coordinator import KimaiCoordinator
from .intent import async_setup_intents

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]

START_TIMESHEET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROJECT_ID): cv.positive_int,
        vol.Required(ATTR_ACTIVITY_ID): cv.positive_int,
        vol.Optional(ATTR_DESCRIPTION): cv.string,
    }
)

STOP_TIMESHEET_SCHEMA = vol.Schema({})

START_BY_NAME_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROJECT): vol.Any(cv.string, cv.positive_int),
        vol.Optional(ATTR_ACTIVITY): vol.Any(cv.string, cv.positive_int),
        vol.Optional(ATTR_DESCRIPTION): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kimai from a config entry."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = KimaiApiClient(
        session, entry.data[CONF_HOST], entry.data[CONF_API_TOKEN], verify_ssl
    )

    coordinator = KimaiCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    def _active_coordinator() -> KimaiCoordinator:
        """Resolve the live coordinator at call time.

        Services are registered globally and survive config entry reloads
        (which happen on every options change). Closing over the coordinator
        from setup would leave the services pointing at a dead object after
        the first reload.
        """
        for key, value in hass.data.get(DOMAIN, {}).items():
            if isinstance(key, str) and key.endswith("_project_select_entity"):
                continue
            if isinstance(value, KimaiCoordinator):
                return value
        raise HomeAssistantError("Kimai är inte konfigurerat")

    async def _handle_start_timesheet(call: ServiceCall) -> None:
        coord = _active_coordinator()
        try:
            await coord.client.async_start_timesheet(
                call.data[ATTR_PROJECT_ID],
                call.data[ATTR_ACTIVITY_ID],
                description=call.data.get(ATTR_DESCRIPTION),
            )
        except KimaiApiError as err:
            raise HomeAssistantError(f"Kunde inte starta tidrapport: {err}") from err
        await coord.async_request_refresh()

    async def _handle_stop_timesheet(call: ServiceCall) -> None:
        coord = _active_coordinator()
        active = coord.data.active_timesheet if coord.data else None
        if not active:
            _LOGGER.debug("Ingen aktiv tidrapport att stoppa")
            return
        try:
            await coord.client.async_stop_timesheet(active["id"])
        except KimaiApiError as err:
            raise HomeAssistantError(f"Kunde inte stoppa tidrapport: {err}") from err
        await coord.async_request_refresh()

    async def _handle_restart_last(call: ServiceCall) -> None:
        coord = _active_coordinator()
        last = coord.data.last_timesheet if coord.data else None
        if not last:
            raise HomeAssistantError("Ingen tidigare tidrapport hittades i Kimai")
        try:
            await coord.client.async_restart_timesheet(last["id"])
        except KimaiApiError as err:
            raise HomeAssistantError(
                f"Kunde inte starta senaste tidrapport: {err}"
            ) from err
        await coord.async_request_refresh()

    async def _handle_start_by_name(call: ServiceCall) -> None:
        """Start a timesheet using project/activity names (or IDs).

        Lets anyone drive the integration from a script, input_text, voice
        assistant or dashboard without hardcoding numeric IDs.
        """
        coord = _active_coordinator()
        if coord.data is None:
            raise HomeAssistantError("Kimai-data är inte inläst ännu")

        raw_project = call.data[ATTR_PROJECT]
        project_id = coord.resolve_project(raw_project)
        if project_id is None:
            raise HomeAssistantError(
                f"Hittade inget projekt som matchar '{raw_project}' i Kimai"
            )

        raw_activity = call.data.get(ATTR_ACTIVITY)
        if raw_activity is not None:
            activity_id = coord.resolve_activity(raw_activity, project_id)
            if activity_id is None:
                raise HomeAssistantError(
                    f"Hittade ingen aktivitet som matchar '{raw_activity}' i Kimai"
                )
        else:
            # Ingen aktivitet angiven - ta första för projektet.
            try:
                activities = await coord.client.async_get_activities(
                    project_id=project_id
                )
            except KimaiApiError as err:
                raise HomeAssistantError(
                    f"Kunde inte hämta aktiviteter: {err}"
                ) from err
            if not activities:
                raise HomeAssistantError(
                    "Projektet har ingen aktivitet kopplad i Kimai"
                )
            activity_id = activities[0]["id"]

        try:
            await coord.client.async_start_timesheet(
                project_id, activity_id, description=call.data.get(ATTR_DESCRIPTION)
            )
        except KimaiApiError as err:
            raise HomeAssistantError(f"Kunde inte starta tidrapport: {err}") from err
        await coord.async_request_refresh()

    # Registrera bara en gång, oavsett antal config entries.
    if not hass.services.has_service(DOMAIN, SERVICE_START_TIMESHEET):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_TIMESHEET,
            _handle_start_timesheet,
            schema=START_TIMESHEET_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_STOP_TIMESHEET,
            _handle_stop_timesheet,
            schema=STOP_TIMESHEET_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESTART_LAST,
            _handle_restart_last,
            schema=STOP_TIMESHEET_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_BY_NAME,
            _handle_start_by_name,
            schema=START_BY_NAME_SCHEMA,
        )

        # Intents registreras globalt, precis som services. De ger både den
        # inbyggda Assist-matchningen och LLM-agenter (via Assist-API:t)
        # tillgång till samma funktionalitet.
        await async_setup_intents(hass)

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (kugghjulet) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.get(DOMAIN, {})
    domain_data.pop(entry.entry_id, None)
    # Select-plattformen lägger en referens till sin entitet här - annars
    # ligger den kvar och håller entiteten vid liv efter varje reload.
    domain_data.pop(f"{entry.entry_id}_project_select_entity", None)

    # Är detta den sista entryn? Ta bort de globalt registrerade servicerna,
    # annars ligger de kvar och pekar på ingenting.
    if not any(isinstance(v, KimaiCoordinator) for v in domain_data.values()):
        for service in (
            SERVICE_START_TIMESHEET,
            SERVICE_STOP_TIMESHEET,
            SERVICE_RESTART_LAST,
            SERVICE_START_BY_NAME,
        ):
            hass.services.async_remove(DOMAIN, service)

    return True
