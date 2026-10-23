"""Bounded, best-effort revocation for removed entries and abandoned pairing."""

import logging

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import ENVIRONMENTS

_LOGGER = logging.getLogger(__name__)


async def async_revoke_device(hass, environment, access_token):
    """Revoke one credential without logging it or an upstream response body."""
    endpoint = ENVIRONMENTS.get(environment)
    if endpoint is None:
        _LOGGER.warning(
            "Home Assistant toolkit cannot revoke an unsupported pairing; "
            "remove the original device in its Toolforest account"
        )
        return
    try:
        async with async_get_clientsession(hass).post(
            f"{endpoint[0]}/device/revoke-self",
            headers={"Authorization": f"Bearer {access_token}"},
            json={},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            await response.read()
            # An invalid/already revoked credential no longer authorizes a device.
            if 200 <= response.status < 300 or response.status == 401:
                return
    except (aiohttp.ClientError, TimeoutError):
        pass
    _LOGGER.warning(
        "Home Assistant toolkit could not confirm device revocation; "
        "remove the offline device in Toolforest"
    )
