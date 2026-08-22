"""Core domain models for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ShipmentLifecycle(StrEnum):
    PLANNED = "PLANNED"
    READY = "READY"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"


class ShipmentPerformance(StrEnum):
    ON_TIME = "ON_TIME"
    AT_RISK = "AT_RISK"
    LATE = "LATE"


class Priority(StrEnum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"
    CRITICAL = "CRITICAL"


class WarehouseOperatingState(StrEnum):
    NORMAL = "NORMAL"
    BUSY = "BUSY"
    CONGESTED = "CONGESTED"


class VehicleAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    LOADING = "LOADING"
    IN_TRANSIT = "IN_TRANSIT"
    UNLOADING = "UNLOADING"
    TURNAROUND = "TURNAROUND"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


@dataclass(slots=True, frozen=True)
class WarehouseProfile:
    warehouse_id: int
    warehouse_name: str
    lat: float
    lon: float
    timezone: str
    loading_capacity: int
    unloading_capacity: int
    baseline_loading_min: float
    baseline_unloading_min: float
    congestion_sensitivity: float
    cold_storage_capable: bool


@dataclass(slots=True)
class WarehouseState:
    profile: WarehouseProfile
    operating_state: WarehouseOperatingState = WarehouseOperatingState.NORMAL
    active_loading_count: int = 0
    active_unloading_count: int = 0
    queue_depth: int = 0
    congestion_factor: float = 1.0


@dataclass(slots=True, frozen=True)
class RouteProfile:
    route_id: int
    origin_wh_id: int
    dest_wh_id: int
    distance_km: float
    nominal_speed_kmh: float
    minimum_speed_kmh: float
    maximum_speed_kmh: float
    baseline_travel_min: float
    congestion_sensitivity: float
    weather_sensitivity: float
    morning_peak_factor: float
    evening_peak_factor: float
    overnight_factor: float
    demand_weight: float
    disruption_probability: float


@dataclass(slots=True)
class RouteState:
    profile: RouteProfile
    traffic_factor: float = 1.0
    weather_factor: float = 1.0
    temporary_speed_factor: float = 1.0


@dataclass(slots=True, frozen=True)
class VehicleProfile:
    vehicle_id: int
    vehicle_reg: str
    vehicle_type: str
    max_payload_kg: float | None
    fuel_type: str | None
    fleet_operator: str | None
    year_manufactured: int | None
    fuel_efficiency_factor: float
    reliability_factor: float
    condition_factor: float
    cruise_speed_factor: float
    maintenance_risk_factor: float
    reefer_capable: bool


@dataclass(slots=True)
class VehicleState:
    profile: VehicleProfile
    current_warehouse_id: int | None
    lat: float
    lon: float
    heading_deg: float = 0.0
    speed_kmh: float = 0.0
    fuel_level_pct: float = 100.0
    odometer_km: float = 0.0
    engine_rpm: int = 0
    idle_time_sec: int = 0
    availability: VehicleAvailability = VehicleAvailability.AVAILABLE
    active_shipment_id: int | None = None

    def validate(self) -> None:
        if not 0 <= self.fuel_level_pct <= 100:
            raise ValueError("fuel_level_pct must be between 0 and 100")
        if self.speed_kmh < 0:
            raise ValueError("speed_kmh cannot be negative")
        if self.odometer_km < 0:
            raise ValueError("odometer_km cannot be negative")


@dataclass(slots=True, frozen=True)
class CargoProfile:
    cargo_type: str
    requires_reefer: bool
    target_temp_c: float | None
    min_temp_c: float | None
    max_temp_c: float | None
    target_humidity_pct: float | None
    handling_sensitivity: float
    loading_time_factor: float


@dataclass(slots=True)
class Shipment:
    shipment_id: int | None
    run_id: int | None
    vehicle_id: int
    route_id: int
    origin_wh_id: int
    dest_wh_id: int
    cargo_type: str
    priority: Priority
    scheduled_departure: datetime
    scheduled_arrival: datetime
    estimated_arrival: datetime
    lifecycle_status: ShipmentLifecycle = ShipmentLifecycle.PLANNED
    actual_departure: datetime | None = None
    actual_arrival: datetime | None = None
    delivery_completed_at: datetime | None = None
    route_progress_pct: float = 0.0
    accumulated_delay_minutes: float = 0.0
    recoverable_buffer_minutes: float = 0.0

    def validate_temporal_integrity(self) -> None:
        if self.scheduled_arrival <= self.scheduled_departure:
            raise ValueError(
                "scheduled_arrival must be after scheduled_departure"
            )

        if (
            self.actual_departure is not None
            and self.actual_arrival is not None
            and self.actual_arrival <= self.actual_departure
        ):
            raise ValueError(
                "actual_arrival must be after actual_departure"
            )

        if (
            self.delivery_completed_at is not None
            and self.actual_arrival is None
        ):
            raise ValueError(
                "delivery_completed_at requires actual_arrival"
            )

        if (
            self.delivery_completed_at is not None
            and self.delivery_completed_at < self.actual_arrival
        ):
            raise ValueError(
                "delivery_completed_at cannot precede actual_arrival"
            )


@dataclass(slots=True)
class OperationalEvent:
    event_id: str
    time: datetime
    event_type: str
    shipment_id: int | None = None
    vehicle_id: int | None = None
    warehouse_id: int | None = None
    route_id: int | None = None
    run_id: int | None = None
    severity: str = "INFO"
    cause_code: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
