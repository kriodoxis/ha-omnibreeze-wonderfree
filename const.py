"""Constants for OmniBreeze Wonderfree."""

from datetime import timedelta

DOMAIN = "omnibreeze_wonderfree"
MANUFACTURER = "OmniBreeze"
MODEL = "DC2313R"

CONF_AUTH_KEY = "auth_key"
CONF_DEVICE_KEY = "device_key"
CONF_PRODUCT_KEY = "product_key"
CONF_PORT = "port"
CONF_REGION = "region"
CONF_BROADCAST_ADDRESSES = "broadcast_addresses"
CONF_DEVICE_ADDRESSES = "device_addresses"

DEFAULT_PORT = 6607
DISCOVERY_PORT = 6606
UPDATE_INTERVAL = timedelta(seconds=15)
SUPPORTED_PRODUCT_KEY = "p11vAZ"
SUPPORTED_PRODUCT_KEYS = {
    "p11vkW",
    "p11vAZ",
}

REGION_CHINA = "china"
REGION_EUROPE = "europe"
REGION_NORTH_AMERICA = "north_america"
DEFAULT_REGION = REGION_EUROPE
REGION_OPTIONS = {
    REGION_EUROPE: "Europe / Latin America",
    REGION_NORTH_AMERICA: "North America",
    REGION_CHINA: "China",
}

PLATFORMS = ("fan", "sensor", "switch", "select")

DP_POWER = 1
DP_MODE = 2
DP_SPEED = 3
DP_OSCILLATION = 5
DP_SOUND = 13
DP_DISPLAY = 15
DP_TEMPERATURE = 21
DP_COUNTDOWN = 22
ALL_DPS = (
    DP_POWER,
    DP_MODE,
    DP_SPEED,
    DP_OSCILLATION,
    DP_SOUND,
    DP_DISPLAY,
    DP_TEMPERATURE,
    DP_COUNTDOWN,
)

PRESET_TO_VALUE = {"normal": 0, "natural": 1, "sleep": 2, "auto": 3}
VALUE_TO_PRESET = {value: key for key, value in PRESET_TO_VALUE.items()}
