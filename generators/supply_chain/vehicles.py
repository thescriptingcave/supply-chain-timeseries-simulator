"""Vehicle state rules for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass

from .models import VehicleAvailability, VehicleState


@dataclass(slots=True, frozen=True)
class MovementResult:
    """State changes produced by vehicle movement."""

    distance_km: float
    fuel_used_pct: float
    new_fuel_level_pct: float
    new_odometer_km: float


def reserve_vehicle(state: VehicleState, shipment_id: int) -> None:
    """Reserve an available vehicle for one shipment."""
    if shipment_id <= 0:
        raise ValueError("shipment_id must be positive")

    if state.availability != VehicleAvailability.AVAILABLE:
        raise ValueError(
            f"vehicle is not available: {state.availability.value}"
        )

    if state.active_shipment_id is not None:
        raise ValueError("vehicle already has an active shipment")

    state.active_shipment_id = shipment_id
    state.availability = VehicleAvailability.RESERVED


def begin_loading(state: VehicleState) -> None:
    """Transition RESERVED -> LOADING."""
    _require_availability(state, VehicleAvailability.RESERVED)
    state.availability = VehicleAvailability.LOADING


def begin_transit(state: VehicleState) -> None:
    """Transition LOADING -> IN_TRANSIT."""
    _require_availability(state, VehicleAvailability.LOADING)

    if state.active_shipment_id is None:
        raise ValueError("vehicle cannot depart without an active shipment")

    state.current_warehouse_id = None
    state.availability = VehicleAvailability.IN_TRANSIT


def begin_unloading(state: VehicleState, warehouse_id: int) -> None:
    """Transition IN_TRANSIT -> UNLOADING at destination."""
    _require_availability(state, VehicleAvailability.IN_TRANSIT)

    if warehouse_id <= 0:
        raise ValueError("warehouse_id must be positive")

    state.current_warehouse_id = warehouse_id
    state.speed_kmh = 0.0
    state.engine_rpm = 0
    state.availability = VehicleAvailability.UNLOADING


def begin_turnaround(state: VehicleState) -> None:
    """Transition UNLOADING -> TURNAROUND."""
    _require_availability(state, VehicleAvailability.UNLOADING)
    state.availability = VehicleAvailability.TURNAROUND


def release_vehicle(state: VehicleState) -> None:
    """Transition TURNAROUND -> AVAILABLE and clear shipment assignment."""
    _require_availability(state, VehicleAvailability.TURNAROUND)

    state.active_shipment_id = None
    state.speed_kmh = 0.0
    state.engine_rpm = 0
    state.availability = VehicleAvailability.AVAILABLE


def mark_out_of_service(state: VehicleState) -> None:
    """Mark a vehicle unavailable for assignment."""
    if state.availability == VehicleAvailability.IN_TRANSIT:
        raise ValueError(
            "in-transit breakdowns must be handled as operational events "
            "before vehicle availability changes"
        )

    state.speed_kmh = 0.0
    state.engine_rpm = 0
    state.availability = VehicleAvailability.OUT_OF_SERVICE


def restore_service(state: VehicleState) -> None:
    """Return an unassigned out-of-service vehicle to AVAILABLE."""
    _require_availability(state, VehicleAvailability.OUT_OF_SERVICE)

    if state.active_shipment_id is not None:
        raise ValueError(
            "cannot restore vehicle while an active shipment is assigned"
        )

    state.availability = VehicleAvailability.AVAILABLE


def calculate_fuel_use_pct(
    *,
    distance_km: float,
    base_consumption_pct_per_100km: float,
    fuel_efficiency_factor: float,
    load_factor: float = 1.0,
    traffic_factor: float = 1.0,
) -> float:
    """Calculate tank-percentage consumption for a movement interval.

    fuel_efficiency_factor follows the seeded v3 profile convention:
    values > 1.0 are more efficient and therefore consume less fuel.
    """
    if distance_km < 0:
        raise ValueError("distance_km cannot be negative")
    if base_consumption_pct_per_100km < 0:
        raise ValueError(
            "base_consumption_pct_per_100km cannot be negative"
        )
    if fuel_efficiency_factor <= 0:
        raise ValueError("fuel_efficiency_factor must be positive")
    if load_factor <= 0:
        raise ValueError("load_factor must be positive")
    if traffic_factor <= 0:
        raise ValueError("traffic_factor must be positive")

    base = (
        distance_km / 100.0
    ) * base_consumption_pct_per_100km

    return (
        base
        * load_factor
        * traffic_factor
        / fuel_efficiency_factor
    )


def apply_movement(
    state: VehicleState,
    *,
    distance_km: float,
    base_consumption_pct_per_100km: float,
    load_factor: float = 1.0,
    traffic_factor: float = 1.0,
) -> MovementResult:
    """Advance odometer and fuel state for an in-transit vehicle."""
    _require_availability(state, VehicleAvailability.IN_TRANSIT)

    fuel_used = calculate_fuel_use_pct(
        distance_km=distance_km,
        base_consumption_pct_per_100km=base_consumption_pct_per_100km,
        fuel_efficiency_factor=state.profile.fuel_efficiency_factor,
        load_factor=load_factor,
        traffic_factor=traffic_factor,
    )

    if fuel_used > state.fuel_level_pct:
        raise ValueError(
            "movement would consume more fuel than the vehicle has"
        )

    state.odometer_km += distance_km
    state.fuel_level_pct -= fuel_used
    state.validate()

    return MovementResult(
        distance_km=distance_km,
        fuel_used_pct=fuel_used,
        new_fuel_level_pct=state.fuel_level_pct,
        new_odometer_km=state.odometer_km,
    )


def refuel(
    state: VehicleState,
    *,
    target_fuel_pct: float,
) -> float:
    """Refuel to a target tank percentage and return percentage added."""
    if not 0 <= target_fuel_pct <= 100:
        raise ValueError("target_fuel_pct must be between 0 and 100")

    if target_fuel_pct < state.fuel_level_pct:
        raise ValueError(
            "target_fuel_pct cannot be below current fuel level"
        )

    added = target_fuel_pct - state.fuel_level_pct
    state.fuel_level_pct = target_fuel_pct
    state.validate()
    return added


def needs_refuel(
    state: VehicleState,
    *,
    reserve_threshold_pct: float,
) -> bool:
    """Return whether vehicle fuel is at or below reserve threshold."""
    if not 0 < reserve_threshold_pct < 100:
        raise ValueError(
            "reserve_threshold_pct must be between 0 and 100"
        )

    return state.fuel_level_pct <= reserve_threshold_pct


def _require_availability(
    state: VehicleState,
    expected: VehicleAvailability,
) -> None:
    if state.availability != expected:
        raise ValueError(
            f"expected vehicle state {expected.value}, "
            f"found {state.availability.value}"
        )
