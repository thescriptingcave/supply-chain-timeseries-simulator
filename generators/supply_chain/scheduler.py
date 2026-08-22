"""Vehicle assignment and shipment scheduling for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random
from typing import Iterable

from .models import (
    CargoProfile,
    Priority,
    RouteProfile,
    VehicleAvailability,
    VehicleState,
    WarehouseState,
)
from .vehicles import needs_refuel
from .warehouses import can_handle_cargo


@dataclass(slots=True, frozen=True)
class AssignmentCandidate:
    """An eligible vehicle plus the score used for assignment."""

    vehicle_id: int
    score: float


def vehicle_is_compatible(
    vehicle: VehicleState,
    *,
    cargo: CargoProfile,
    origin_warehouse_id: int,
    reserve_threshold_pct: float,
) -> bool:
    """Return whether a vehicle may be assigned to a planned shipment."""
    if vehicle.availability != VehicleAvailability.AVAILABLE:
        return False

    if vehicle.active_shipment_id is not None:
        return False

    if vehicle.current_warehouse_id != origin_warehouse_id:
        return False

    if cargo.requires_reefer and not vehicle.profile.reefer_capable:
        return False

    if needs_refuel(
        vehicle,
        reserve_threshold_pct=reserve_threshold_pct,
    ):
        return False

    return True


def score_vehicle(vehicle: VehicleState) -> float:
    """Score a compatible vehicle using persistent v3 profile attributes.

    Higher is better. Reliability and condition are favored, while
    maintenance risk is penalized.
    """
    p = vehicle.profile

    if p.maintenance_risk_factor <= 0:
        raise ValueError("maintenance_risk_factor must be positive")

    return (
        p.reliability_factor
        * p.condition_factor
        * p.fuel_efficiency_factor
    ) / p.maintenance_risk_factor


def eligible_vehicles(
    vehicles: Iterable[VehicleState],
    *,
    cargo: CargoProfile,
    origin_warehouse_id: int,
    reserve_threshold_pct: float,
) -> list[AssignmentCandidate]:
    """Return compatible vehicles sorted by assignment preference."""
    candidates = [
        AssignmentCandidate(
            vehicle_id=v.profile.vehicle_id,
            score=score_vehicle(v),
        )
        for v in vehicles
        if vehicle_is_compatible(
            v,
            cargo=cargo,
            origin_warehouse_id=origin_warehouse_id,
            reserve_threshold_pct=reserve_threshold_pct,
        )
    ]

    return sorted(
        candidates,
        key=lambda candidate: (-candidate.score, candidate.vehicle_id),
    )


def choose_vehicle(
    vehicles: Iterable[VehicleState],
    *,
    cargo: CargoProfile,
    origin_warehouse_id: int,
    reserve_threshold_pct: float,
) -> VehicleState | None:
    """Choose the highest-scoring eligible vehicle."""
    vehicle_list = list(vehicles)

    candidates = eligible_vehicles(
        vehicle_list,
        cargo=cargo,
        origin_warehouse_id=origin_warehouse_id,
        reserve_threshold_pct=reserve_threshold_pct,
    )

    if not candidates:
        return None

    selected_id = candidates[0].vehicle_id
    return next(
        v for v in vehicle_list
        if v.profile.vehicle_id == selected_id
    )


def validate_shipment_compatibility(
    *,
    vehicle: VehicleState,
    cargo: CargoProfile,
    origin_warehouse: WarehouseState,
    destination_warehouse: WarehouseState,
    reserve_threshold_pct: float,
) -> None:
    """Raise when a planned shipment violates assignment constraints."""
    if not can_handle_cargo(
        warehouse_state=origin_warehouse,
        cargo_profile=cargo,
    ):
        raise ValueError("origin warehouse cannot handle cargo")

    if not can_handle_cargo(
        warehouse_state=destination_warehouse,
        cargo_profile=cargo,
    ):
        raise ValueError("destination warehouse cannot handle cargo")

    if not vehicle_is_compatible(
        vehicle,
        cargo=cargo,
        origin_warehouse_id=origin_warehouse.profile.warehouse_id,
        reserve_threshold_pct=reserve_threshold_pct,
    ):
        raise ValueError("vehicle is not compatible with shipment")


def choose_route_weighted(
    routes: Iterable[RouteProfile],
    *,
    origin_warehouse_id: int,
    rng: Random,
) -> RouteProfile:
    """Choose an active origin route using configured demand weights."""
    candidates = [
        route
        for route in routes
        if route.origin_wh_id == origin_warehouse_id
    ]

    if not candidates:
        raise ValueError(
            f"no routes found for origin warehouse {origin_warehouse_id}"
        )

    weights = [route.demand_weight for route in candidates]

    if any(weight <= 0 for weight in weights):
        raise ValueError("all route demand weights must be positive")

    return rng.choices(candidates, weights=weights, k=1)[0]


def scheduled_arrival_from_route(
    *,
    scheduled_departure: datetime,
    route: RouteProfile,
    planning_buffer_minutes: float = 0.0,
) -> datetime:
    """Build the original service commitment from route baseline travel time."""
    if planning_buffer_minutes < 0:
        raise ValueError("planning_buffer_minutes cannot be negative")

    if route.baseline_travel_min <= 0:
        raise ValueError("route baseline_travel_min must be positive")

    return scheduled_departure + timedelta(
        minutes=route.baseline_travel_min + planning_buffer_minutes
    )


def priority_planning_buffer_minutes(priority: Priority) -> float:
    """Return initial service-planning buffer by priority.

    These are planning buffers, not operational delay. Once execution starts,
    scheduled_arrival remains fixed.
    """
    return {
        Priority.STANDARD: 45.0,
        Priority.EXPEDITED: 30.0,
        Priority.CRITICAL: 20.0,
    }[priority]
