from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from .const import (DOMAIN, STATE_AUTH_REQUIRED, STATE_EMPTY, STATE_ERROR, STATE_HEALTHY,
                    STATE_RECOVERING)
from .entity import KataEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KataStatus(c), KataLastSuccess(c), KataCount(c)])


class KataStatus(KataEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATE_HEALTHY, STATE_EMPTY, STATE_RECOVERING,
                     STATE_AUTH_REQUIRED, STATE_ERROR]

    def __init__(self, c):
        super().__init__(c, "status")

    @property
    def native_value(self):
        return self.coordinator.state


class KataLastSuccess(KataEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Last successful check"

    def __init__(self, c):
        super().__init__(c, "last_success")

    @property
    def native_value(self):
        return self.coordinator.last_success


class KataCount(KataEntity, SensorEntity):
    _attr_name = "Photos today"

    def __init__(self, c):
        super().__init__(c, "today_count")

    @property
    def native_value(self):
        return self.coordinator.today_count
