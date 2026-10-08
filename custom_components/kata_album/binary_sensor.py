from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .const import DOMAIN, STATE_EMPTY, STATE_HEALTHY
from .entity import KataEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([KataHealthy(hass.data[DOMAIN][entry.entry_id])])


class KataHealthy(KataEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, c):
        super().__init__(c, "healthy")

    @property
    def is_on(self):
        return self.coordinator.state in (STATE_HEALTHY, STATE_EMPTY)
