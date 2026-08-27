"""Intent handlers for Kimai.

Registering intents covers both worlds at once: the built-in Assist sentence
matcher and LLM-backed conversation agents. The LLM Assist API is built from
registered intents, so an Ollama/OpenAI agent gets these as callable tools
without any extra work - it just needs the "Assist" API enabled in its options.

Sentences for the built-in matcher cannot ship inside a custom integration;
they belong in config/custom_sentences/<lang>/. See custom_sentences_exempel/
in this repo for ready-made Swedish and English files.
"""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, intent

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

INTENT_START = "KimaiStartTimesheet"
INTENT_STOP = "KimaiStopTimesheet"
INTENT_CURRENT = "KimaiCurrentTimesheet"


def _first_coordinator(hass: HomeAssistant):
    """Intents are global, config entries are not.

    With a single Kimai instance (the normal case) we just take the first
    coordinator. Multi-instance setups would need a slot to disambiguate.
    """
    for key, value in hass.data.get(DOMAIN, {}).items():
        # Skip the helper entries we stash alongside coordinators.
        if not isinstance(key, str) or not key.endswith("_project_select_entity"):
            if hasattr(value, "async_request_refresh"):
                return value
    return None


class KimaiStartIntent(intent.IntentHandler):
    """Start tracking time on a project, by name."""

    intent_type = INTENT_START
    description = (
        "Starts tracking time in Kimai for a given project. Use when the user "
        "says they are starting work on something, e.g. 'I'm working on X now'. "
        "The project must match a project name in Kimai."
    )
    slot_schema = {
        vol.Required("project"): cv.string,
        vol.Optional("activity"): cv.string,
        vol.Optional("description"): cv.string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        project = slots["project"]["value"]
        activity = slots.get("activity", {}).get("value")
        description = slots.get("description", {}).get("value") or project

        response = intent_obj.create_response()

        coordinator = _first_coordinator(hass)
        if coordinator is None or coordinator.data is None:
            response.async_set_speech("Kimai är inte tillgängligt just nu.")
            return response

        project_id = coordinator.resolve_project(project)
        if project_id is None:
            response.async_set_speech(
                f"Jag hittade inget projekt som heter {project} i Kimai."
            )
            return response

        data = {"project": project_id, "description": description}
        if activity:
            activity_id = coordinator.resolve_activity(activity, project_id)
            if activity_id is None:
                response.async_set_speech(
                    f"Jag hittade ingen aktivitet som heter {activity}."
                )
                return response
            data["activity"] = activity_id

        await hass.services.async_call(
            DOMAIN, "start_by_name", data, blocking=True
        )

        project_name = coordinator.resolve_project_name(project_id) or project
        response.async_set_speech(f"Startade tidtagning för {project_name}.")
        return response


class KimaiStopIntent(intent.IntentHandler):
    """Stop the running timesheet."""

    intent_type = INTENT_STOP
    description = (
        "Stops the currently running time tracking in Kimai. Use when the user "
        "says they are done working, taking a break, or stopping."
    )
    slot_schema: dict = {}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        response = intent_obj.create_response()

        coordinator = _first_coordinator(hass)
        if coordinator is None or coordinator.data is None:
            response.async_set_speech("Kimai är inte tillgängligt just nu.")
            return response

        if not coordinator.data.is_running:
            response.async_set_speech("Ingen tidtagning pågår just nu.")
            return response

        project_name = coordinator.data.active_project_name
        elapsed = coordinator.data.active_elapsed_minutes

        await hass.services.async_call(DOMAIN, "stop_timesheet", {}, blocking=True)

        if project_name and elapsed is not None:
            response.async_set_speech(
                f"Stoppade {project_name} efter {round(elapsed)} minuter."
            )
        else:
            response.async_set_speech("Stoppade tidtagningen.")
        return response


class KimaiCurrentIntent(intent.IntentHandler):
    """Query what is currently being tracked."""

    intent_type = INTENT_CURRENT
    description = (
        "Reports what the user is currently tracking time on in Kimai, and for "
        "how long. Use for questions like 'what am I working on'."
    )
    slot_schema: dict = {}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()

        coordinator = _first_coordinator(intent_obj.hass)
        if coordinator is None or coordinator.data is None:
            response.async_set_speech("Kimai är inte tillgängligt just nu.")
            return response

        data = coordinator.data
        if not data.is_running:
            response.async_set_speech("Ingen tidtagning pågår just nu.")
            return response

        project = data.active_project_name or "okänt projekt"
        elapsed = data.active_elapsed_minutes
        if elapsed is None:
            response.async_set_speech(f"Du arbetar med {project}.")
        elif elapsed < 60:
            response.async_set_speech(
                f"Du arbetar med {project} sedan {round(elapsed)} minuter."
            )
        else:
            hours = int(elapsed // 60)
            minutes = round(elapsed % 60)
            response.async_set_speech(
                f"Du arbetar med {project} sedan {hours} timmar och "
                f"{minutes} minuter."
            )
        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register all Kimai intents. Safe to call once per config entry."""
    intent.async_register(hass, KimaiStartIntent())
    intent.async_register(hass, KimaiStopIntent())
    intent.async_register(hass, KimaiCurrentIntent())
