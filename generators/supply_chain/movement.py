"""Incremental vehicle movement for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass

from .models import RouteState, VehicleAvailability, VehicleState
from .routing import calculate_target_speed
from .vehicles import apply_movement


@dataclass(slots=True, frozen=True)
class MovementTickResult:
    """Result of one incremental movement tick."""

    elapsed_seconds: float
    speed_kmh: float
    distance_km: float
    fuel_used_pct: float
    route_progress_pct: float
    remaining_distance_km: float


def interpolate_position(
    *,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    progress_pct: float,
) -> tuple[float, float]:
    """Linearly interpolate route position for progress in the range 0..100."""
    if not 0.0 <= progress_pct <= 100.0:
        raise ValueError("progress_pct must be between 0 and 100")

    fraction = progress_pct / 100.0

    lat = origin_lat + (destination_lat - origin_lat) * fraction
    lon = origin_lon + (destination_lon - origin_lon) * fraction

    return lat, lon


def movement_tick(
    *,
    vehicle: VehicleState,
    route_state: RouteState,
    elapsed_seconds: float,
    current_progress_pct: float,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    base_consumption_pct_per_100km: float,
    load_factor: float = 1.0,
    fuel_traffic_factor: float = 1.0,
) -> MovementTickResult:
    """Advance one vehicle along its route for up to a fixed simulation interval.

    The final tick consumes only the time physically required to reach the
    destination. This prevents a partial final movement from incorrectly
    advancing the simulation clock by the entire configured tick interval.
    """
    if vehicle.availability != VehicleAvailability.IN_TRANSIT:
        raise ValueError("vehicle must be IN_TRANSIT for movement")

    if elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds must be positive")

    if not 0.0 <= current_progress_pct <= 100.0:
        raise ValueError("current_progress_pct must be between 0 and 100")

    route = route_state.profile

    speed = calculate_target_speed(
        route_state,
        vehicle.profile,
    ).target_kmh

    remaining_before = route.distance_km * (
        1.0 - current_progress_pct / 100.0
    )

    if remaining_before <= 0:
        vehicle.speed_kmh = 0.0
        vehicle.lat = destination_lat
        vehicle.lon = destination_lon

        return MovementTickResult(
            elapsed_seconds=0.0,
            speed_kmh=0.0,
            distance_km=0.0,
            fuel_used_pct=0.0,
            route_progress_pct=100.0,
            remaining_distance_km=0.0,
        )

    if speed <= 0:
        raise ValueError("effective speed must be positive while distance remains")

    requested_distance = speed * elapsed_seconds / 3600.0
    distance = min(requested_distance, remaining_before)

    actual_elapsed_seconds = elapsed_seconds
    if distance < requested_distance:
        actual_elapsed_seconds = distance / speed * 3600.0

    movement = apply_movement(
        vehicle,
        distance_km=distance,
        base_consumption_pct_per_100km=base_consumption_pct_per_100km,
        load_factor=load_factor,
        traffic_factor=fuel_traffic_factor,
    )

    progress_increment = (distance / route.distance_km) * 100.0
    new_progress = min(100.0, current_progress_pct + progress_increment)

    vehicle.lat, vehicle.lon = interpolate_position(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        destination_lat=destination_lat,
        destination_lon=destination_lon,
        progress_pct=new_progress,
    )

    vehicle.speed_kmh = 0.0 if new_progress >= 100.0 else speed

    remaining_after = max(
        0.0,
        route.distance_km * (1.0 - new_progress / 100.0),
    )

    return MovementTickResult(
        elapsed_seconds=actual_elapsed_seconds,
        speed_kmh=vehicle.speed_kmh,
        distance_km=movement.distance_km,
        fuel_used_pct=movement.fuel_used_pct,
        route_progress_pct=new_progress,
        remaining_distance_km=remaining_after,
    )
