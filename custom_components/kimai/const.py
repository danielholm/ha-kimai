"""Constants for the Kimai integration."""
from datetime import timedelta

DOMAIN = "kimai"

CONF_HOST = "host"
CONF_API_TOKEN = "api_token"
CONF_VERIFY_SSL = "verify_ssl"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_TIMEOUT = 10

ATTR_PROJECT_ID = "project_id"
ATTR_ACTIVITY_ID = "activity_id"
ATTR_DESCRIPTION = "description"
ATTR_PROJECT = "project"
ATTR_ACTIVITY = "activity"

CONF_MAPPINGS = "mappings"
CONF_PROJECT_ID = "project_id"
CONF_ACTIVITY_ID = "activity_id"
CONF_LABEL = "label"
CONF_DESCRIPTION = "description"

SERVICE_START_TIMESHEET = "start_timesheet"
SERVICE_STOP_TIMESHEET = "stop_timesheet"
SERVICE_RESTART_LAST = "restart_last"
SERVICE_IMPORT_MAPPINGS = "import_mappings"
SERVICE_START_BY_NAME = "start_by_name"

STATE_IDLE = "Ledig"
