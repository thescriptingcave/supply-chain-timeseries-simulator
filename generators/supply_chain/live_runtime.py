"""Wall-clock live runtime for Supply Chain Generator v3.

This runtime reuses the validated V3 shipment engines and vehicle-availability
scheduler. It does not reimplement movement/fuel/ETA logic.

Design:
- Wall clock decides when a new live shipment may start.
- A shipment is executed by the existing V3 engine.
- Persisted telemetry timestamps remain actual UTC timestamps.
- Vehicle availability is honored before assignment.
- The initial live slice runs normal shipments only. Additional V3 event
  families can be enabled incrementally after this base runtime is validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import random

from .concurrent_disruptions import (
    DisruptedShipmentPlan,
    run_disruption_aware_fleet,
)
from .context import SimulationContext
from .models import (
    CargoProfile,
    RouteProfile,
    VehicleProfile,
    VehicleState,
    WarehouseState,
)
from .vehicle_scheduler import (
    choose_available_vehicle,
    mark_vehicle_available,
)


@dataclass(slots=True, frozen=True)
class LiveSupplyChainConfig:
    shipment_interval_seconds: int = 300
    movement_interval_seconds: float = 60.0
    base_consumption_pct_per_100km: float = 1.0
    seed: int = 42

    def validate(self) -> None:
        if self.shipment_interval_seconds <= 0:
            raise ValueError("shipment_interval_seconds must be positive")
        if self.movement_interval_seconds <= 0:
            raise ValueError("movement_interval_seconds must be positive")
        if self.base_consumption_pct_per_100km <= 0:
            raise ValueError(
                "base_consumption_pct_per_100km must be positive"
            )


@dataclass(slots=True)
class LiveRuntimeState:
    rng: random.Random
    next_shipment_at: datetime
    shipment_sequence: int = 0


def should_start_shipment(
    *,
    now: datetime,
    state: LiveRuntimeState,
) -> bool:
    return now >= state.next_shipment_at


def advance_next_shipment_time(
    *,
    state: LiveRuntimeState,
    config: LiveSupplyChainConfig,
) -> None:
    state.next_shipment_at = (
        state.next_shipment_at
        + timedelta(seconds=config.shipment_interval_seconds)
    )


def fresh_vehicle_state(
    *,
    profile: VehicleProfile,
    origin: WarehouseState,
    fuel_level_pct: float = 95.0,
    odometer_km: float = 100000.0,
) -> VehicleState:
    return VehicleState(
        profile=profile,
        current_warehouse_id=origin.profile.warehouse_id,
        lat=origin.profile.lat,
        lon=origin.profile.lon,
        fuel_level_pct=fuel_level_pct,
        odometer_km=odometer_km,
    )


def execute_live_normal_shipment(
    *,
    run_id: int,
    shipment_id: int,
    wall_clock_start: datetime,
    route: RouteProfile,
    cargo: CargoProfile,
    vehicle_profile: VehicleProfile,
    origin: WarehouseState,
    destination: WarehouseState,
    config: LiveSupplyChainConfig,
):
    """Execute one wall-clock anchored shipment using the validated V3 engine."""
    config.validate()

    vehicle = fresh_vehicle_state(
        profile=vehicle_profile,
        origin=origin,
    )

    # Give the shipment ample simulated completion room while anchoring all
    # timestamps to the real current UTC start.
    context = SimulationContext(
        simulation_start=wall_clock_start,
        simulation_end=wall_clock_start + timedelta(days=3),
        seed=config.seed + shipment_id,
        run_id=run_id,
    )

    result = run_disruption_aware_fleet(
        context=context,
        plans=[
            DisruptedShipmentPlan(
                shipment_id=shipment_id,
                vehicle_id=vehicle_profile.vehicle_id,
                route=route,
                cargo=cargo,
            )
        ],
        vehicles=[vehicle],
        warehouses={
            origin.profile.warehouse_id: origin,
            destination.profile.warehouse_id: destination,
        },
        disruptions=[],
        movement_interval_seconds=config.movement_interval_seconds,
        base_consumption_pct_per_100km=(
            config.base_consumption_pct_per_100km
        ),
        eta_event_threshold_min=1.0,
    )

    return result.shipments[0]
