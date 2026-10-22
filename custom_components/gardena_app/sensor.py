"""Sensors: schedules per valve, device health, gateway and GARDENA smart sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import LIGHT_LUX, PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GardenaCoordinator, GardenaDevice, parse_time
from .entity import GardenaEntity


@dataclass(frozen=True, kw_only=True)
class GardenaSensorDescription(SensorEntityDescription):
    """Sensor read from one ability property."""

    ability: str
    prop: str
    value: Callable[[Any], Any] = lambda v: v


DEVICE_SENSORS: tuple[GardenaSensorDescription, ...] = (
    GardenaSensorDescription(
        key="connection", ability="device_info", prop="connection_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    GardenaSensorDescription(
        key="last_online", ability="device_info", prop="last_time_online",
        device_class=SensorDeviceClass.TIMESTAMP, entity_category=EntityCategory.DIAGNOSTIC, value=parse_time,
    ),
    GardenaSensorDescription(
        key="firmware_status", ability="firmware", prop="firmware_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    GardenaSensorDescription(
        key="radio_quality", ability="radio_link", prop="quality",
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    GardenaSensorDescription(
        key="ip_address", ability="gateway", prop="ip_address", entity_category=EntityCategory.DIAGNOSTIC,
    ),
    GardenaSensorDescription(
        key="wlan_ssid", ability="gateway", prop="wlan_configured_ssid", entity_category=EntityCategory.DIAGNOSTIC,
    ),
    GardenaSensorDescription(
        key="wifi_status", ability="device_info", prop="wifi_status", entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda v: (v or {}).get("signal_strength") if isinstance(v, dict) else v,
    ),
    # GARDENA smart Sensor and friends
    GardenaSensorDescription(
        key="soil_humidity", ability="humidity", prop="humidity",
        device_class=SensorDeviceClass.MOISTURE, native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    GardenaSensorDescription(
        key="soil_temperature", ability="soil_temperature", prop="temperature",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    GardenaSensorDescription(
        key="ambient_temperature", ability="ambient_temperature", prop="temperature",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    GardenaSensorDescription(
        key="light", ability="light", prop="light",
        device_class=SensorDeviceClass.ILLUMINANCE, native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    GardenaSensorDescription(
        key="battery", ability="battery", prop="level",
        device_class=SensorDeviceClass.BATTERY, native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GardenaCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for dev in coordinator.data.values():
        for desc in DEVICE_SENSORS:
            if desc.prop in dev.props.get(desc.ability, {}):
                entities.append(GardenaPropertySensor(coordinator, dev.id, desc))
        if dev.has_valves:
            entities.append(GardenaNextStartSensor(coordinator, dev.id, None))
            for vid in dev.valve_ids:
                entities.append(GardenaNextStartSensor(coordinator, dev.id, vid))
                entities.append(GardenaPausedUntilSensor(coordinator, dev.id, vid))
                entities.append(GardenaValveErrorSensor(coordinator, dev.id, vid))
    async_add_entities(entities)


class GardenaPropertySensor(GardenaEntity, SensorEntity):
    entity_description: GardenaSensorDescription

    def __init__(self, coordinator, device_id: str, description: GardenaSensorDescription) -> None:
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        d = self.entity_description
        return d.value(self.device.prop(d.ability, d.prop))


class GardenaNextStartSensor(GardenaEntity, SensorEntity):
    """Next scheduled start, with the full schedule as attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, device_id: str, valve_id: int | None) -> None:
        super().__init__(coordinator, device_id, "next_start", valve_id)
        if valve_id is not None:
            self._attr_translation_key = None
            self._attr_name = f"{self.valve_name} nächster Start"

    @property
    def native_value(self):
        suffix = f"_{self._valve_id}" if self._valve_id is not None else ""
        return parse_time(self.device.prop("scheduling", f"scheduled_watering_next_start{suffix}"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dev: GardenaDevice = self.device
        if self._valve_id is None:
            return {"zeitplaene_gesamt": len(dev.events)}
        return {
            "ventil_id": self._valve_id,
            "zeitplan": [
                {
                    "id": e["id"],
                    "start": e.get("start_at"),
                    "ende": e.get("end_at"),
                    "tage": (e.get("recurrence") or {}).get("weekdays"),
                }
                for e in dev.valve_events(self._valve_id)
            ],
        }


class GardenaPausedUntilSensor(GardenaEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, device_id: str, valve_id: int) -> None:
        super().__init__(coordinator, device_id, "paused_until", valve_id)
        self._attr_translation_key = None
        self._attr_name = f"{self.valve_name} pausiert bis"

    @property
    def native_value(self):
        return self.device.paused_until(self._valve_id)


class GardenaValveErrorSensor(GardenaEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str, valve_id: int) -> None:
        super().__init__(coordinator, device_id, "valve_error", valve_id)
        self._attr_translation_key = None
        self._attr_name = f"{self.valve_name} Fehler"

    @property
    def native_value(self):
        v = self.device.prop("error", f"valve_error_{self._valve_id}")
        if isinstance(v, dict):
            v = v.get("value") or v.get("error")
        return v or "kein Fehler"
