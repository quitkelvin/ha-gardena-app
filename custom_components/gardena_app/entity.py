"""Base entity of the Gardena App integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import GardenaCoordinator, GardenaDevice


class GardenaEntity(CoordinatorEntity[GardenaCoordinator]):
    """Entity bound to one app device (and optionally one valve)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GardenaCoordinator, device_id: str, key: str, valve_id: int | None = None) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._valve_id = valve_id
        dev = self.device
        suffix = f"_{valve_id}" if valve_id is not None else ""
        self._attr_unique_id = f"{device_id}{suffix}_{key}"
        self._attr_translation_key = key
        if valve_id is not None:
            self._attr_translation_placeholders = {"valve": dev.valve_name(valve_id)}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=f"{dev.name} (App)",
            manufacturer=MANUFACTURER,
            model=dev.prop("device_info", "product") or dev.category,
            sw_version=dev.prop("device_info", "version"),
        )

    @property
    def device(self) -> GardenaDevice:
        return self.coordinator.data[self._device_id]

    @property
    def available(self) -> bool:
        return super().available and self._device_id in (self.coordinator.data or {})

    @property
    def valve_name(self) -> str:
        return self.device.valve_name(self._valve_id) if self._valve_id is not None else ""
