"""Polling coordinator and a small view on the raw app device data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import GardenaAppClient, GardenaAuthError, GardenaError
from .const import CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES, DOMAIN

_LOGGER = logging.getLogger(__name__)


def parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    return dt_util.parse_datetime(value)


@dataclass
class GardenaDevice:
    """One device as the app sees it."""

    raw: dict
    props: dict[str, dict[str, Any]] = field(default_factory=dict)
    settings: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict) -> GardenaDevice:
        props: dict[str, dict[str, Any]] = {}
        for ability in raw.get("abilities", []):
            props[ability.get("type") or ability.get("name")] = {
                p["name"]: p.get("value") for p in ability.get("properties", [])
            }
        settings = {s["name"]: s for s in raw.get("settings", [])}
        return cls(raw, props, settings)

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def name(self) -> str:
        return self.raw.get("name") or self.category

    @property
    def category(self) -> str:
        return self.raw.get("category", "")

    def prop(self, ability: str, name: str) -> Any:
        return self.props.get(ability, {}).get(name)

    def setting(self, name: str) -> Any:
        s = self.settings.get(name)
        return s.get("value") if s else None

    @property
    def events(self) -> list[dict]:
        return self.raw.get("scheduled_events") or []

    # Irrigation Control (ic24) ------------------------------------------
    @property
    def has_valves(self) -> bool:
        return bool(self.valve_ids)

    @property
    def valve_ids(self) -> list[int]:
        connected = self.prop("valve", "valves_connected")
        if connected:
            return list(connected)
        # single-outlet devices (water control) only know watering_timer_1
        return [1] if "watering_timer_1" in self.props.get("watering", {}) else []

    def pause_setting(self, valve_id: int) -> dict | None:
        return self.settings.get(f"schedules_paused_until_{valve_id}") or self.settings.get("schedules_paused_until")

    def valve_name(self, valve_id: int) -> str:
        for v in self.setting("valve_names") or []:
            if v.get("id") == valve_id and (v.get("name") or "").strip():
                return v["name"].strip()
        return f"Ventil {valve_id}"

    def paused_until(self, valve_id: int) -> datetime | None:
        setting = self.pause_setting(valve_id)
        until = parse_time(setting.get("value")) if setting else None
        return until if until and until > dt_util.utcnow() else None

    def timer(self, valve_id: int) -> dict:
        return self.prop("watering", f"watering_timer_{valve_id}") or {}

    def valve_events(self, valve_id: int) -> list[dict]:
        return sorted(
            (e for e in self.events if e.get("valve_id", 1) == valve_id),
            key=lambda e: e.get("start_at", ""),
        )


class GardenaCoordinator(DataUpdateCoordinator[dict[str, GardenaDevice]]):
    """Polls all devices of the location."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: GardenaAppClient, location: str) -> None:
        minutes = entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self.location = location

    async def _async_update_data(self) -> dict[str, GardenaDevice]:
        try:
            raw = await self.client.async_devices()
        except GardenaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GardenaError as err:
            raise UpdateFailed(str(err)) from err
        return {d["id"]: GardenaDevice.from_raw(d) for d in raw}

    def valve_devices(self) -> list[GardenaDevice]:
        return [d for d in (self.data or {}).values() if d.has_valves]

    async def async_write(self, coro) -> None:
        """Run a write call, then refresh so the entities follow."""
        try:
            await coro
        except GardenaError as err:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError(str(err)) from err
        # immediate re-read (request_refresh is debounced and showed stale schedules)
        await self.async_refresh()
