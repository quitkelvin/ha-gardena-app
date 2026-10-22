"""Valves: open for the manual duration, close at once."""

from __future__ import annotations

from typing import Any

from homeassistant.components.valve import ValveDeviceClass, ValveEntity, ValveEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity
from .number import DEFAULT_MINUTES


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GardenaCoordinator = entry.runtime_data
    async_add_entities(
        GardenaValve(coordinator, dev.id, vid)
        for dev in coordinator.valve_devices()
        for vid in dev.valve_ids
    )


class GardenaValve(GardenaEntity, ValveEntity):
    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False

    def __init__(self, coordinator, device_id: str, valve_id: int) -> None:
        super().__init__(coordinator, device_id, "valve", valve_id)

    @property
    def is_closed(self) -> bool:
        return (self.device.timer(self._valve_id).get("state") or "idle") == "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = self.device.timer(self._valve_id)
        return {"ventil_id": self._valve_id, "zustand": t.get("state"), "dauer_s": t.get("duration")}

    def _minutes(self) -> int:
        reg = er.async_get(self.hass)
        uid = f"{self._device_id}_{self._valve_id}_duration"
        eid = reg.async_get_entity_id("number", DOMAIN, uid)
        state = self.hass.states.get(eid) if eid else None
        try:
            return int(float(state.state))
        except (AttributeError, TypeError, ValueError):
            return DEFAULT_MINUTES

    async def _timer(self, state: str, seconds: int) -> None:
        value = {"state": state, "duration": seconds, "valve_id": self._valve_id}
        await self.coordinator.async_write(
            self.coordinator.client.async_put_property(
                self._device_id, "watering", f"watering_timer_{self._valve_id}", value
            )
        )

    async def async_open_valve(self, **kwargs: Any) -> None:
        await self._timer("manual", self._minutes() * 60)

    async def async_close_valve(self, **kwargs: Any) -> None:
        await self._timer("idle", 0)
