"""Fixed production endpoints and expose-by-choice options."""

DOMAIN = "toolforest"
VERSION = "0.1.1"
ENVIRONMENTS = {
    "prod": ("https://bridge-api.toolforest.io", "wss://bridge.toolforest.io"),
}
EXPOSURE_KEYS = (
    "read_entities",
    "turn_on_entities",
    "turn_off_entities",
    "brightness_entities",
)
STATUS_SIGNAL = "toolforest_status"
