"""Manual watering duration per valve (used when the valve entity is opened)."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

DEFAULT_MINUTES = 10


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GardenaCoordinator = entry.runtime_data
    async_add_entities(
        GardenaDuration(coordinator, dev.id, vid)
        for dev in coordinator.valve_devices()
        for vid in dev.valve_ids
    )


class GardenaDuration(GardenaEntity, RestoreNumber):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 90
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, device_id: str, valve_id: int) -> None:
        super().__init__(coordinator, device_id, "duration", valve_id)
        self._attr_native_value = DEFAULT_MINUTES

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self._attr_native_value = last.native_value

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
