from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KataCoordinator


class KataEntity(CoordinatorEntity[KataCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KataCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)}, name="Kata Friend",
            manufacturer="SwitchBot")
