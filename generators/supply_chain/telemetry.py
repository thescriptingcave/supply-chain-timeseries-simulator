"""Fleet telemetry derivation for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import Shipment, VehicleState


@dataclass(slots=True, frozen=True)
class FleetTelemetryRow:
    """One fleet telemetry sample derived from current simulation state."""

    vehicle_id: int
    shipment_id: int | None
    lat: float
    lon: float
    speed_kmh: float
    heading_deg: float
    engine_rpm: int
    fuel_level_pct: float
    cargo_temp_c: float | None
    cargo_humidity_pct: float | None
    door_open: bool
    harsh_braking: bool
    harsh_acceleration: bool
    idle_time_sec: int
    odometer_km: float
    geofence_zone: str


@dataclass(slots=True, frozen=True)
class TimedFleetTelemetrySample:
    """A fleet telemetry row paired with its authoritative simulation time."""

    time: datetime
    row: FleetTelemetryRow


def derive_geofence_zone(
    *,
    at_origin: bool,
    at_destination: bool,
    speed_kmh: float,
    at_fuel_stop: bool = False,
) -> str:
    if at_fuel_stop:
        return "FUEL_STOP"
    if at_origin:
        return "ORIGIN_WAREHOUSE"
    if at_destination:
        return "DESTINATION_WAREHOUSE"
    if speed_kmh >= 50:
        return "HIGHWAY"
    return "URBAN"


def derive_engine_rpm(speed_kmh: float) -> int:
    if speed_kmh < 0:
        raise ValueError("speed_kmh cannot be negative")
    if speed_kmh == 0:
        return 700
    return int(900 + min(speed_kmh, 120.0) * 18)


def make_fleet_telemetry_row(
    *,
    vehicle: VehicleState,
    shipment: Shipment | None,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    cargo_temp_c: float | None = None,
    cargo_humidity_pct: float | None = None,
    door_open: bool = False,
    harsh_braking: bool = False,
    harsh_acceleration: bool = False,
    at_fuel_stop: bool = False,
    warehouse_tolerance: float = 1e-6,
) -> FleetTelemetryRow:
    if vehicle.speed_kmh < 0:
        raise ValueError("vehicle speed cannot be negative")

    if vehicle.fuel_level_pct < 0 or vehicle.fuel_level_pct > 100:
        raise ValueError("vehicle fuel level must be between 0 and 100")

    if harsh_braking and vehicle.speed_kmh == 0:
        raise ValueError("harsh braking cannot occur while stationary")

    if harsh_acceleration and vehicle.speed_kmh == 0:
        raise ValueError("harsh acceleration cannot occur while stationary")

    at_origin = (
        abs(vehicle.lat - origin_lat) <= warehouse_tolerance
        and abs(vehicle.lon - origin_lon) <= warehouse_tolerance
    )
    at_destination = (
        abs(vehicle.lat - destination_lat) <= warehouse_tolerance
        and abs(vehicle.lon - destination_lon) <= warehouse_tolerance
    )

    geofence = derive_geofence_zone(
        at_origin=at_origin,
        at_destination=at_destination,
        speed_kmh=vehicle.speed_kmh,
        at_fuel_stop=at_fuel_stop,
    )

    return FleetTelemetryRow(
        vehicle_id=vehicle.profile.vehicle_id,
        shipment_id=shipment.shipment_id if shipment is not None else None,
        lat=vehicle.lat,
        lon=vehicle.lon,
        speed_kmh=vehicle.speed_kmh,
        heading_deg=vehicle.heading_deg,
        engine_rpm=derive_engine_rpm(vehicle.speed_kmh),
        fuel_level_pct=vehicle.fuel_level_pct,
        cargo_temp_c=cargo_temp_c,
        cargo_humidity_pct=cargo_humidity_pct,
        door_open=door_open,
        harsh_braking=harsh_braking,
        harsh_acceleration=harsh_acceleration,
        idle_time_sec=vehicle.idle_time_sec,
        odometer_km=vehicle.odometer_km,
        geofence_zone=geofence,
    )
