"""Constants for Kata Album."""
from datetime import timedelta

DOMAIN = "kata_album"

CONF_ACCOUNT = "account"
CONF_DEVICE_ID = "device_id"
CONF_NOTIFY = "notify"
CONF_LOCAL = "local"  # startup cache only; always re-verified before use

# Cloud endpoints and request bodies confirmed against App logs and live calls.
ACCOUNT_BASE = "https://account.api.switchbot.net"
DEVICE_BASE = "https://wonderlabs.ap.api.switchbot.net"
COMMAND_BASE = "https://wonderlabs.ap.api.switchbot.net"
REFRESH_PATH = "/account/api/v1/user/token/refresh"
SHADOW_PATH = "/device/device/v1/shadow/getByIDs"
INVOKE_PATH = "/command/cmd/api/v1/func/invoke"
APP_VERSION = "10.3"

PROP_LOCAL_INFO = 9230
FUNC_OPEN_LOCAL = 1021
FUNC_LIST_PHOTOS = 9217
FUNC_DELETE_PHOTOS = 9218
FUNC_LIST_PEOPLE = 9225
FUNC_PERSON_PHOTOS = 9226
FUNC_PERSON_STATS = 9227

SCAN_INTERVAL = timedelta(minutes=5)
THUMB_PROBE_INTERVAL = timedelta(minutes=15)
FAILURES_BEFORE_RECOVERY = 3
RECOVERY_COOLDOWN = timedelta(minutes=30)
RECOVERY_POLL_SECONDS = 30
TOKEN_REFRESH_MARGIN = 300

MAX_THUMB_BYTES = 5 * 1024 * 1024
MAX_PREVIEW_BYTES = 10 * 1024 * 1024
MAX_ORIGINAL_BYTES = 25 * 1024 * 1024
LIST_CACHE_SECONDS = 600

STATE_HEALTHY = "healthy"
STATE_EMPTY = "empty"
STATE_RECOVERING = "recovering"
STATE_AUTH_REQUIRED = "auth_required"
STATE_ERROR = "error"
