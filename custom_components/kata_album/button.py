from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .entity import KataEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CheckButton(c), ReopenButton(c)])


class CheckButton(KataEntity, ButtonEntity):
    def __init__(self, c):
        super().__init__(c, "check")

    async def async_press(self) -> None:
        await self.coordinator.async_manual_check()


class ReopenButton(KataEntity, ButtonEntity):
    def __init__(self, c):
        super().__init__(c, "reopen")

    async def async_press(self) -> None:
        await self.coordinator.async_manual_recover()
