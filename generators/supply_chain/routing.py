"""Route behavior for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass

from .models import RouteProfile, RouteState, VehicleProfile


@dataclass(slots=True, frozen=True)
class SpeedCalculation:
    """Result of a route target-speed calculation."""

    unclamped_kmh: float
    target_kmh: float


def calculate_target_speed(
    route_state: RouteState,
    vehicle_profile: VehicleProfile,
) -> SpeedCalculation:
    """Calculate physically bounded target speed from route and vehicle state."""
    p = route_state.profile

    raw = (
        p.nominal_speed_kmh
        * vehicle_profile.cruise_speed_factor
        * route_state.traffic_factor
        * route_state.weather_factor
        * route_state.temporary_speed_factor
    )

    lower = max(0.0, p.minimum_speed_kmh)
    upper = max(lower, p.maximum_speed_kmh)

    bounded = min(max(raw, lower), upper)

    return SpeedCalculation(
        unclamped_kmh=raw,
        target_kmh=bounded,
    )


def remaining_distance_km(
    route_profile: RouteProfile,
    progress_pct: float,
) -> float:
    """Return remaining route distance for progress in the inclusive range 0..100."""
    if not 0.0 <= progress_pct <= 100.0:
        raise ValueError("progress_pct must be between 0 and 100")

    remaining_fraction = 1.0 - (progress_pct / 100.0)
    return route_profile.distance_km * remaining_fraction


def validate_route_profile(route: RouteProfile) -> None:
    """Validate core directional-route invariants."""
    if route.origin_wh_id == route.dest_wh_id:
        raise ValueError("route origin and destination must differ")

    if route.distance_km <= 0:
        raise ValueError("route distance_km must be positive")

    if route.nominal_speed_kmh <= 0:
        raise ValueError("nominal_speed_kmh must be positive")

    if route.minimum_speed_kmh < 0:
        raise ValueError("minimum_speed_kmh cannot be negative")

    if route.maximum_speed_kmh < route.minimum_speed_kmh:
        raise ValueError(
            "maximum_speed_kmh must be greater than or equal to minimum_speed_kmh"
        )

    if route.demand_weight <= 0:
        raise ValueError("demand_weight must be positive")

    if not 0.0 <= route.disruption_probability <= 1.0:
        raise ValueError(
            "disruption_probability must be between 0 and 1"
        )


def apply_route_factors(
    route_state: RouteState,
    *,
    traffic_factor: float | None = None,
    weather_factor: float | None = None,
    temporary_speed_factor: float | None = None,
) -> None:
    """Update persistent route-state factors with basic validation."""
    updates = {
        "traffic_factor": traffic_factor,
        "weather_factor": weather_factor,
        "temporary_speed_factor": temporary_speed_factor,
    }

    for name, value in updates.items():
        if value is None:
            continue
        if value < 0:
            raise ValueError(f"{name} cannot be negative")
        setattr(route_state, name, value)
