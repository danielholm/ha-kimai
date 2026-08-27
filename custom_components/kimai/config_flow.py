"""Config flow for Kimai."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KimaiApiClient, KimaiApiError, KimaiAuthError
from .const import (
    CONF_ACTIVITY_ID,
    CONF_DESCRIPTION,
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_LABEL,
    CONF_MAPPINGS,
    CONF_PROJECT_ID,
    CONF_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_TOKEN): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Try to reach Kimai and confirm the token works. Raises on failure."""
    session = async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL])
    client = KimaiApiClient(
        session, data[CONF_HOST], data[CONF_API_TOKEN], data[CONF_VERIFY_SSL]
    )
    await client.async_get_version()


class KimaiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kimai."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].rstrip("/")

            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()

            try:
                await _validate_input(self.hass, user_input)
            except KimaiAuthError:
                errors["base"] = "invalid_auth"
            except KimaiApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Oväntat fel vid validering av Kimai-anslutning")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_HOST], data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "KimaiOptionsFlowHandler":
        return KimaiOptionsFlowHandler()


class KimaiOptionsFlowHandler(config_entries.OptionsFlow):
    """Kugghjulet: hantera manuella kopplingar projekt -> aktivitet.

    Varje koppling har ett eget namn (label) som visas i select.kimai_valj_projekt
    istället för det råa Kimai-projektnamnet, och pekar ut exakt vilken aktivitet
    som ska användas när tidrapporten startas.
    """

    def __init__(self) -> None:
        self._mappings: dict[str, dict] | None = None
        self._pending_project_id: int | None = None
        self._pending_project_name: str | None = None
        self._editing_key: str | None = None

    async def _get_client(self) -> KimaiApiClient:
        data = self.config_entry.data
        verify_ssl = data.get(CONF_VERIFY_SSL, True)
        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        return KimaiApiClient(session, data[CONF_HOST], data[CONF_API_TOKEN], verify_ssl)

    def _ensure_mappings_loaded(self) -> None:
        """Always read from the config entry, never from stale memory.

        Earlier versions accumulated changes in memory and wrote everything at
        once when the user pressed "Klar". That meant a single write could
        overwrite the whole table with an incomplete copy. Each mutation is now
        persisted immediately instead.
        """
        self._mappings = dict(self.config_entry.options.get(CONF_MAPPINGS, {}))

    def _save_mappings(self, mappings: dict[str, dict]) -> None:
        """Persist immediately, merging into whatever else is in options."""
        options = dict(self.config_entry.options)
        options[CONF_MAPPINGS] = mappings
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=options
        )
        self._mappings = mappings
        _LOGGER.debug("Sparade %d Kimai-kopplingar", len(mappings))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        self._ensure_mappings_loaded()
        self._editing_key = None

        if self._mappings:
            current = "\n".join(
                f"• {m[CONF_LABEL]}  (projekt {m[CONF_PROJECT_ID]} / "
                f"aktivitet {m[CONF_ACTIVITY_ID]})"
                for m in self._mappings.values()
            )
            menu = [
                "add_mapping",
                "edit_mapping",
                "remove_mapping",
                "import_mappings",
                "refresh_data",
                "done",
            ]
        else:
            current = (
                "(inga kopplingar konfigurerade ännu - "
                "använder första aktiviteten per projekt)"
            )
            menu = ["add_mapping", "import_mappings", "refresh_data", "done"]

        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if coordinator is not None and coordinator.data is not None:
            antal_p = len(coordinator.data.projects)
            antal_a = len(coordinator.data.activities)
            hamtad = coordinator.static_fetched_at
            tid = (
                dt_util.as_local(hamtad).strftime("%Y-%m-%d %H:%M")
                if hamtad
                else "okänt"
            )
            status = (
                f"\n\n{antal_p} projekt och {antal_a} aktiviteter, "
                f"hämtade {tid}."
            )
        else:
            status = ""

        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
            description_placeholders={"current_mappings": current + status},
        )

    async def async_step_edit_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pick which existing mapping to edit."""
        self._ensure_mappings_loaded()

        if not self._mappings:
            return await self.async_step_init()

        if user_input is None:
            choices = {k: v[CONF_LABEL] for k, v in self._mappings.items()}
            schema = vol.Schema({vol.Required("mapping"): vol.In(choices)})
            return self.async_show_form(step_id="edit_mapping", data_schema=schema)

        self._editing_key = user_input["mapping"]
        self._pending_project_id = int(
            self._mappings[self._editing_key][CONF_PROJECT_ID]
        )

        # Look up the project name for a nicer form title.
        try:
            projects = await self._get_client_projects()
        except KimaiApiError as err:
            _LOGGER.debug("Kunde inte hämta projekt vid redigering: %s", err)
            return self.async_abort(reason="cannot_connect")
        self._pending_project_name = next(
            (p["name"] for p in projects if p["id"] == self._pending_project_id),
            self._mappings[self._editing_key][CONF_LABEL],
        )
        return await self.async_step_add_activity()

    async def _get_client_projects(self) -> list[dict[str, Any]]:
        client = await self._get_client()
        return await client.async_get_projects()

    async def async_step_add_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        self._ensure_mappings_loaded()
        client = await self._get_client()

        try:
            projects = await client.async_get_projects()
        except KimaiApiError as err:
            _LOGGER.debug("Kunde inte hämta projektlistan: %s", err)
            return self.async_abort(reason="cannot_connect")

        if not projects:
            return self.async_abort(reason="no_projects")

        if user_input is None:
            choices = {str(p["id"]): p["name"] for p in projects}
            schema = vol.Schema({vol.Required(CONF_PROJECT_ID): vol.In(choices)})
            return self.async_show_form(step_id="add_mapping", data_schema=schema)

        self._pending_project_id = int(user_input[CONF_PROJECT_ID])
        self._pending_project_name = next(
            (p["name"] for p in projects if p["id"] == self._pending_project_id),
            str(self._pending_project_id),
        )
        return await self.async_step_add_activity()

    async def async_step_add_activity(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        # Måste läsas in här: det här steget skriver mappningarna, och utan
        # inläsning skrevs hela tabellen över med enbart den nya posten.
        self._ensure_mappings_loaded()
        client = await self._get_client()

        try:
            activities = await client.async_get_activities(
                project_id=self._pending_project_id
            )
        except KimaiApiError as err:
            _LOGGER.debug(
                "Kunde inte hämta aktiviteter för projekt %s: %s",
                self._pending_project_id,
                err,
            )
            return self.async_abort(reason="cannot_connect")

        if not activities:
            return self.async_abort(reason="no_activities")

        if user_input is None:
            choices = {str(a["id"]): a["name"] for a in activities}

            # När vi redigerar: förifyll med det som redan är sparat.
            existing = (
                self._mappings.get(self._editing_key, {})
                if self._editing_key
                else {}
            )
            default_activity = (
                str(existing[CONF_ACTIVITY_ID])
                if existing.get(CONF_ACTIVITY_ID) is not None
                and str(existing[CONF_ACTIVITY_ID]) in choices
                else vol.UNDEFINED
            )
            default_label = existing.get(CONF_LABEL, self._pending_project_name)

            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_ACTIVITY_ID, default=default_activity
                    ): vol.In(choices),
                    vol.Optional(CONF_LABEL, default=default_label): str,
                    vol.Optional(
                        CONF_DESCRIPTION,
                        default=existing.get(CONF_DESCRIPTION, ""),
                    ): str,
                }
            )
            return self.async_show_form(
                step_id="add_activity",
                data_schema=schema,
                description_placeholders={"project": self._pending_project_name},
            )

        label = user_input.get(CONF_LABEL) or self._pending_project_name
        entry = {
            CONF_PROJECT_ID: int(self._pending_project_id),
            CONF_ACTIVITY_ID: int(user_input[CONF_ACTIVITY_ID]),
            CONF_LABEL: label,
        }
        if user_input.get(CONF_DESCRIPTION):
            entry[CONF_DESCRIPTION] = user_input[CONF_DESCRIPTION]

        # Om namnet ändrades vid redigering: ta bort den gamla nyckeln.
        mappings = dict(self._mappings)
        if self._editing_key and self._editing_key != label:
            mappings.pop(self._editing_key, None)
        mappings[label] = entry
        self._save_mappings(mappings)
        return await self.async_step_init()

    async def async_step_remove_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        self._ensure_mappings_loaded()

        if not self._mappings:
            return await self.async_step_init()

        if user_input is None:
            choices = {k: v[CONF_LABEL] for k, v in self._mappings.items()}
            schema = vol.Schema({vol.Required("mapping"): vol.In(choices)})
            return self.async_show_form(step_id="remove_mapping", data_schema=schema)

        mappings = dict(self._mappings)
        mappings.pop(user_input["mapping"], None)
        self._save_mappings(mappings)
        return await self.async_step_init()

    async def async_step_import_mappings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Paste a whole mapping table at once.

        Accepts the same shape as the old YAML automation map:
            {"Studierektor": {"project": 1, "activity": 2}, ...}
        Optionally with "description" per entry.
        """
        self._ensure_mappings_loaded()
        errors: dict[str, str] = {}

        if user_input is not None:
            raw = user_input["json"].strip()
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("förväntade ett objekt")

                imported: dict[str, dict] = {}
                for label, spec in parsed.items():
                    if not isinstance(spec, dict):
                        raise ValueError(f"'{label}' saknar project/activity")
                    project = spec.get("project", spec.get(CONF_PROJECT_ID))
                    activity = spec.get("activity", spec.get(CONF_ACTIVITY_ID))
                    if project is None or activity is None:
                        raise ValueError(f"'{label}' saknar project eller activity")
                    entry = {
                        CONF_PROJECT_ID: int(project),
                        CONF_ACTIVITY_ID: int(activity),
                        CONF_LABEL: str(label),
                    }
                    if spec.get(CONF_DESCRIPTION):
                        entry[CONF_DESCRIPTION] = str(spec[CONF_DESCRIPTION])
                    imported[str(label)] = entry
            except (ValueError, TypeError, json.JSONDecodeError) as err:
                _LOGGER.debug("Import av Kimai-kopplingar misslyckades: %s", err)
                errors["base"] = "invalid_json"
            else:
                if user_input.get("replace"):
                    mappings = imported
                else:
                    mappings = dict(self._mappings)
                    mappings.update(imported)
                self._save_mappings(mappings)
                return await self.async_step_init()

        schema = vol.Schema(
            {
                vol.Required("json"): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Optional("replace", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="import_mappings", data_schema=schema, errors=errors
        )

    async def async_step_refresh_data(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reload projects and activities from Kimai.

        The lists are otherwise only fetched when the integration loads, so
        this is how you pick up projects added or renamed in Kimai without
        restarting Home Assistant.
        """
        self._ensure_mappings_loaded()

        coordinator = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id
        )
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        try:
            await coordinator.async_refresh_static()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Kunde inte ladda om projekt och aktiviteter")
            return self.async_abort(reason="cannot_connect")

        return await self.async_step_init()

    async def async_step_done(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        # Allt är redan sparat av _save_mappings. Skriv tillbaka befintliga
        # options oförändrade så att flödet avslutas utan att röra datan.
        return self.async_create_entry(title="", data=dict(self.config_entry.options))
