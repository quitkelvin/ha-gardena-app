"""Buttons: close all valves, trigger a measurement on GARDENA smart sensors."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

MEASURE = {
    "humidity": "measure_soil_humidity",
    "soil_temperature": "measure_soil_temperature",
    "ambient_temperature": "measure_ambient_temperature",
    "light": "measure_light",
}


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GardenaCoordinator = entry.runtime_data
    entities: list[ButtonEntity] = []
    for dev in coordinator.data.values():
        if len(dev.valve_ids) > 1:
            entities.append(GardenaCloseAll(coordinator, dev.id))
        abilities = [a for a in MEASURE if a in dev.props]
        if abilities:
            entities.append(GardenaMeasure(coordinator, dev.id, abilities))
    async_add_entities(entities)


class GardenaCloseAll(GardenaEntity, ButtonEntity):
    _attr_icon = "mdi:water-off"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "close_all")

    async def async_press(self) -> None:
        await self.coordinator.async_write(
            self.coordinator.client.async_command(self._device_id, "watering", "close_all_valves")
        )


class GardenaMeasure(GardenaEntity, ButtonEntity):
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator, device_id: str, abilities: list[str]) -> None:
        super().__init__(coordinator, device_id, "measure")
        self._abilities = abilities

    async def async_press(self) -> None:
        client = self.coordinator.client

        async def run() -> None:
            for ability in self._abilities:
                await client.async_command(self._device_id, ability, MEASURE[ability])

        await self.coordinator.async_write(run())
