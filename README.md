# Kimai for Home Assistant

*[Svenska](README.sv.md)*

A custom integration that connects [Kimai](https://www.kimai.org/) time
tracking to Home Assistant. See what you are currently tracking, start and
stop timesheets, and drive it all from scripts, dashboards or voice.

> **Status: early.** Works against Kimai 2.x, but has had limited testing
> across Kimai versions. Bug reports welcome.

## Disclaimer

This is "vibe coded". I previously had REST and shell commands, together with
templated sensors, selectors, scripts and automations that handled my Kimai
instance. Now, I had Claude put them together with a nice config flow.

Use as is.

## Requirements

- Kimai 2.x with API access enabled
- Home Assistant 2026.3 or newer (only for the local brand images — remove
  `brand/` and it runs on older versions)
- No external Python packages: `requirements` is empty

## Installation

### Short way

Add repo to HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=danielholm&repository=ha-kimai&category=integration)

After restart add the integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=kimai)

### HACS

1. HACS → three-dot menu → **Custom repositories**
2. Paste this repository's URL, category **Integration**
3. Install, then restart Home Assistant
4. **Settings → Devices & services → Add integration → Kimai**

### Manual

Copy `custom_components/kimai` into `<config>/custom_components/kimai` on your
Home Assistant instance and restart.

## Setup

You need your Kimai URL and an API token. Create the token in Kimai under your
user profile → API access.

It is worth verifying both before adding the integration:

```bash
curl -sS -H "Authorization: Bearer YOUR_TOKEN" https://kimai.example.com/api/version
curl -sS -H "Authorization: Bearer YOUR_TOKEN" https://kimai.example.com/api/timesheets/active
```

If those return JSON rather than 401/403, the config flow will work.

## Entities

Entity names are translated (English and Swedish included). Entity IDs are
generated when the entities are first created, based on the name in your Home
Assistant language — the IDs below are what an English instance gets.

**Binary sensor**

| Entity | Description |
| --- | --- |
| `binary_sensor.kimai_active` | Whether a timesheet is running (`device_class: running`) |

**Sensors**

| Entity | Description |
| --- | --- |
| `sensor.kimai_status` | Active project name, or "Idle" when nothing is running |
| `sensor.kimai_elapsed` | Minutes elapsed in the running timesheet |
| `sensor.kimai_started` | Start time as a timestamp — use this for a live counter |
| `sensor.kimai_last` | Last **completed** record — what "Start last" would resume |

`sensor.kimai_status` exposes `project`, `activity`, `begin` and `description`
as attributes, so you can template against the raw values.

Note that `sensor.kimai_last` shows the last *finished* record. While something
is running, that is the entry before it — not the one currently being tracked.

**Buttons**

| Entity | Description |
| --- | --- |
| `button.kimai_start` | Start whatever is selected in the select entity |
| `button.kimai_start_last` | Resume the last stopped record, same project and activity |
| `button.kimai_stop` | Stop the running timesheet |

**Select**

| Entity | Description |
| --- | --- |
| `select.kimai_project` | What the start button will launch |

## Actions

| Action | Fields |
| --- | --- |
| `kimai.start_by_name` | `project`, `activity` (optional), `description` (optional) |
| `kimai.start_timesheet` | `project_id`, `activity_id`, `description` (optional) |
| `kimai.stop_timesheet` | — |
| `kimai.restart_last` | — |

`start_by_name` is usually what you want. It accepts either names or numeric
IDs, so nothing needs hardcoding:

```yaml
script:
  start_kimai:
    fields:
      task:
        selector:
          text:
    sequence:
      - action: kimai.start_by_name
        data:
          project: "{{ task }}"
          description: "{{ task }}"
```

Drive it from an `input_text`, an `input_select`, a dashboard button or a voice
assistant — anything that can pass a string.

Names are matched exactly, case-insensitively. If the name does not exist in
Kimai you get a clear error rather than the wrong project being started.

Kimai does offer a `term` parameter for free-text search, but it returns
partial matches and possibly several results. Starting the wrong project is
worse than an error message, so the integration matches against the project and
activity lists it has already fetched. This also costs no extra API calls.

Activity names are not unique in Kimai — several projects often have an
activity called "Meeting". When a project is known, activities belonging to it
are preferred, with global activities as a fallback.

## Project and activity mappings

Kimai timesheets need both a project **and** an activity. Without a mapping,
the start button picks the first activity it finds for the chosen project,
which is often not the one you want.

Under **Settings → Devices & services → Kimai → Configure** you can pin a
project to a specific activity and give the pair your own label:

- **Add mapping** — pick project, pick activity, name it
- **Edit mapping** — change the activity or the label
- **Remove mapping**
- **Import several** — paste a whole table as JSON
- **Reload projects and activities** — refetch the lists from Kimai

The select entity shows **your mappings first, then every project from Kimai**.
A mapping is a shortcut to a specific project+activity pair — it does not hide
the rest of your projects. Pick a plain project name and the first activity is
used, as before. If a mapping shares its name with a project, it appears once
and the mapping wins.

Each change is saved immediately, so leaving the dialog halfway cannot lose
anything.

The import format:

```json
{
  "Client work": { "project": 3, "activity": 7 },
  "Internal meetings": { "project": 3, "activity": 12 },
  "Admin": { "project": 9, "activity": 4, "description": "Administration" }
}
```

Mappings are keyed by label, so the same project can appear more than once with
different activities. `description` is optional and defaults to the label.

Mappings live in `.storage/core.config_entries` alongside the host and token —
a plain JSON file, not the recorder database. They are included in Home
Assistant backups and unaffected by recorder purges. The token is stored in
clear text there, as it is for every other Home Assistant integration.

## Voice control

The integration registers three intents:

| Intent | Purpose |
| --- | --- |
| `KimaiStartTimesheet` | Start a project (slots: `project`, `activity`, `description`) |
| `KimaiStopTimesheet` | Stop the running timesheet |
| `KimaiCurrentTimesheet` | Report what is running and for how long |

**With an LLM conversation agent** (Ollama, OpenAI and friends) this works
immediately — just select **Assist** as the API in the agent's options. Home
Assistant builds its LLM API from registered intents, so the model gets these
as callable tools. Project names are passed as free text and resolved against
Kimai, so nothing needs configuring up front.

> "I'm working on the research project now"
> → *Started tracking time for Research project.*

**With the built-in sentence matcher**, sentences cannot ship inside a custom
integration — Home Assistant only loads them from
`config/custom_sentences/<language>/`. Copy the example file:

```
custom_sentences_examples/en/kimai.yaml  →  config/custom_sentences/en/kimai.yaml
```

and fill in your own project names under `lists: project:`. The built-in
matcher cannot fetch the list from Kimai; it needs to know valid words in
advance. Restart Home Assistant afterwards.

## Dashboard tip: a live counter

The elapsed sensor updates every 30 seconds. For a counter that ticks every
second, use the started sensor instead — Home Assistant renders timestamp
sensors as relative time client-side, with no extra polling. A plain entity
card works, or a mushroom-template-card with `relative_time()`.

## When lists are refreshed

Projects and activities are fetched **when the integration loads**: on Home
Assistant restart, on integration reload, and whenever you change something in
the options (which triggers a reload). They are not polled in between, since
they rarely change.

Add a project in Kimai and it will not appear automatically. Pick **Reload
projects and activities** in the options to fetch the lists without a restart.
The options forms always query the API directly, so they show current data even
when the coordinator's copy is stale.

## Impact on your Home Assistant instance

- **No synchronous I/O.** All API calls go through `aiohttp` on the event loop,
  so a slow or unreachable Kimai cannot block other integrations.
- **No external packages.** Nothing gets pip-installed, no version conflicts.
- **Light polling.** Two parallel API calls every 30 seconds. Raise
  `DEFAULT_SCAN_INTERVAL` in `const.py` if you want less; 60–120 seconds is
  fine unless you care about the live counter.
- **Cleans up after itself.** Unloading removes actions, `hass.data` keys and
  entity references, so repeated reloads do not leak.
- **Nine entities total.**

## A note on Kimai's data format

Depending on version and endpoint, Kimai returns `project` and `activity`
either as nested objects or as bare numeric IDs. The integration handles both:
when only IDs come back, names are resolved against the project and activity
lists.

If the status sensor shows a number instead of a name, or stays idle while
Kimai is clearly running something, that is the place to look. The entity's
attributes in Developer Tools will show what actually came back.

## Known limitations

- The select entity's choice is local to Home Assistant and resets on restart,
  falling back to the first option. `RestoreEntity` would fix it.
- Kimai 1.x is not supported — it used a different auth scheme
  (`X-AUTH-USER`/`X-AUTH-TOKEN`).
- Only the first active timesheet is shown if Kimai is configured to allow
  several at once.
- Upgrading from a version before entity translations were added: existing
  entities keep their original IDs, since the entity registry matches on
  `unique_id`. Only the displayed names change.

## Development

Run Home Assistant in a devcontainer and symlink this folder into
`config/custom_components/`, so you can iterate without touching a production
instance. Home Assistant's official template:
https://github.com/home-assistant/integration_blueprint

Note that testing writes real timesheets to whatever Kimai instance you point
it at. A throwaway Kimai in Docker is worth the five minutes:

```bash
docker run --rm -p 8001:8001 \
  -e ADMINMAIL=admin@example.com \
  -e ADMINPASS=some-password \
  kimai/kimai2:apache
```

## License

MIT
