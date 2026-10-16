"""Fixed environment endpoints and expose-by-choice options."""

DOMAIN = "toolforest"
VERSION = "0.1.0"
ENVIRONMENTS = {
    "dev": ("https://bridge-api-dev.toolforest.io", "wss://bridge-dev.toolforest.io"),
    "test": (
        "https://bridge-api-test.toolforest.io",
        "wss://bridge-test.toolforest.io",
    ),
    "prod": ("https://bridge-api.toolforest.io", "wss://bridge.toolforest.io"),
}
EXPOSURE_KEYS = (
    "read_entities",
    "turn_on_entities",
    "turn_off_entities",
    "brightness_entities",
)
STATUS_SIGNAL = "toolforest_status"
