"""Diagnostics: state only, never credentials or local service info."""
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict:
    c = hass.data[DOMAIN][entry.entry_id]
    return {
        "state": c.state,
        "failures": c.failures,
        "last_success": c.last_success.isoformat() if c.last_success else None,
        "last_recovery": c.last_recovery.isoformat() if c.last_recovery else None,
        "has_callback": bool(entry.data.get("notify")),
    }
