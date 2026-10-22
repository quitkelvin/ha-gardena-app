"""Constants of the Gardena App integration."""

from homeassistant.const import Platform

DOMAIN = "gardena_app"
MANUFACTURER = "GARDENA"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_SCAN_MINUTES = "scan_minutes"
DEFAULT_SCAN_MINUTES = 10

AUTH_URL = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/token"
APP_URL = "https://smart.gardena.com/v1"

# Value the GARDENA app itself writes for "paused until further notice".
PAUSED_FOREVER = "2038-01-18T00:00:00.000Z"

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.VALVE,
]
