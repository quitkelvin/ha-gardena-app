"""Schedule switches per valve, a winter pause for all valves, power sockets."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import PAUSED_FOREVER, WEEKDAYS
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

_TIME = vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$")
_DAYS = vol.All(cv.ensure_list, [vol.In(WEEKDAYS)])


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GardenaCoordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    for dev in coordinator.data.values():
        if dev.has_valves:
            entities.append(GardenaWinterPause(coordinator, dev.id))
            entities += [GardenaScheduleSwitch(coordinator, dev.id, vid) for vid in dev.valve_ids]
        if "power_timer" in dev.props.get("power", {}):
            entities.append(GardenaPowerSocket(coordinator, dev.id))
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "pause_schedule",
        {vol.Optional("until"): cv.datetime, vol.Optional("hours"): vol.Coerce(float)},
        "async_pause",
    )
    platform.async_register_entity_service("resume_schedule", {}, "async_resume")
    platform.async_register_entity_service(
        "add_schedule",
        {vol.Required("start"): _TIME, vol.Required("end"): _TIME, vol.Optional("weekdays", default=WEEKDAYS): _DAYS},
        "async_add_schedule",
    )
    platform.async_register_entity_service(
        "update_schedule",
        {
            vol.Required("event_id"): cv.string,
            vol.Optional("start"): _TIME,
            vol.Optional("end"): _TIME,
            vol.Optional("weekdays"): _DAYS,
        },
        "async_update_schedule",
    )
    platform.async_register_entity_service(
        "delete_schedule", {vol.Required("event_id"): cv.string}, "async_delete_schedule"
    )


def _iso(when: datetime) -> str:
    return dt_util.as_utc(when).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class GardenaScheduleSwitch(GardenaEntity, SwitchEntity):
    """On = the app schedule of this valve runs, off = paused until further notice."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, device_id: str, valve_id: int) -> None:
        super().__init__(coordinator, device_id, "schedule", valve_id)

    @property
    def is_on(self) -> bool:
        return self.device.paused_until(self._valve_id) is None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        until = self.device.paused_until(self._valve_id)
        return {
            "ventil_id": self._valve_id,
            "pausiert_bis": until.isoformat() if until else None,
            "zeitplan": [
                {"id": e["id"], "start": e.get("start_at"), "ende": e.get("end_at"),
                 "tage": (e.get("recurrence") or {}).get("weekdays")}
                for e in self.device.valve_events(self._valve_id)
            ],
        }

    async def _write_pause(self, value: str) -> None:
        setting = self.device.pause_setting(self._valve_id)
        if setting is None:
            raise ServiceValidationError("This device has no schedule pause setting")
        await self.coordinator.async_write(
            self.coordinator.client.async_put_setting(self._device_id, setting, value)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write_pause("")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write_pause(PAUSED_FOREVER)

    async def async_pause(self, until: datetime | None = None, hours: float | None = None) -> None:
        if hours is not None:
            until = dt_util.utcnow() + timedelta(hours=hours)
        elif until is not None and until.tzinfo is None:
            until = until.replace(tzinfo=dt_util.get_default_time_zone())
        await self._write_pause(_iso(until) if until else PAUSED_FOREVER)

    async def async_resume(self) -> None:
        await self._write_pause("")

    async def async_add_schedule(self, start: str, end: str, weekdays: list[str]) -> None:
        event = {"start_at": start, "end_at": end, "valve_id": self._valve_id,
                 "recurrence": {"type": "weekly", "weekdays": weekdays}}
        await self.coordinator.async_write(self.coordinator.client.async_add_event(self._device_id, event))

    def _event(self, event_id: str) -> dict:
        for e in self.device.valve_events(self._valve_id):
            if e["id"] == event_id:
                return e
        raise ServiceValidationError(f"Schedule entry {event_id} does not belong to {self.valve_name}")

    async def async_update_schedule(self, event_id: str, start: str | None = None,
                                    end: str | None = None, weekdays: list[str] | None = None) -> None:
        old = self._event(event_id)
        event = {
            "start_at": start or old["start_at"],
            "end_at": end or old["end_at"],
            "valve_id": self._valve_id,
            "recurrence": {"type": "weekly", "weekdays": weekdays or (old.get("recurrence") or {}).get("weekdays", WEEKDAYS)},
        }
        await self.coordinator.async_write(
            self.coordinator.client.async_update_event(self._device_id, event_id, event)
        )

    async def async_delete_schedule(self, event_id: str) -> None:
        self._event(event_id)
        await self.coordinator.async_write(self.coordinator.client.async_delete_event(self._device_id, event_id))


class GardenaWinterPause(GardenaEntity, SwitchEntity):
    """On = every valve schedule paused until further notice."""

    _attr_icon = "mdi:snowflake"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "winter_pause")

    @property
    def is_on(self) -> bool:
        dev = self.device
        return all(dev.paused_until(v) is not None for v in dev.valve_ids)

    async def _all(self, value: str) -> None:
        dev = self.device
        client = self.coordinator.client

        async def run() -> None:
            for vid in dev.valve_ids:
                setting = dev.pause_setting(vid)
                if setting is not None:
                    await client.async_put_setting(dev.id, setting, value)

        await self.coordinator.async_write(run())

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._all(PAUSED_FOREVER)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._all("")

    async def async_pause(self, until: datetime | None = None, hours: float | None = None) -> None:
        if hours is not None:
            until = dt_util.utcnow() + timedelta(hours=hours)
        await self._all(_iso(until) if until else PAUSED_FOREVER)

    async def async_resume(self) -> None:
        await self._all("")

    async def async_add_schedule(self, **kwargs: Any) -> None:
        raise ServiceValidationError("Use the schedule switch of a valve for this action")

    async_update_schedule = async_delete_schedule = async_add_schedule


class GardenaPowerSocket(GardenaEntity, SwitchEntity):
    """GARDENA smart Power socket."""

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "power")

    @property
    def is_on(self) -> bool:
        v = self.device.prop("power", "power_timer")
        return v not in (None, "off", 0, "0")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(
            self.coordinator.client.async_put_property(self._device_id, "power", "power_timer", "on"))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(
            self.coordinator.client.async_put_property(self._device_id, "power", "power_timer", "off"))

    async def async_pause(self, **kwargs: Any) -> None:
        raise ServiceValidationError("Only available for valves")

    async_resume = async_add_schedule = async_update_schedule = async_delete_schedule = async_pause
