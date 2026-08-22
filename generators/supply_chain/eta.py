"""ETA calculation for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import RouteState, Shipment, ShipmentPerformance, VehicleProfile
from .routing import calculate_target_speed, remaining_distance_km


@dataclass(slots=True, frozen=True)
class EtaResult:
    """Calculated ETA plus supporting values used for analytics/events."""

    estimated_arrival: datetime
    remaining_distance_km: float
    effective_speed_kmh: float
    remaining_travel_minutes: float
    operational_delay_minutes: float
    expected_destination_dwell_minutes: float
    recovered_minutes: float


def calculate_eta(
    *,
    now: datetime,
    shipment: Shipment,
    route_state: RouteState,
    vehicle_profile: VehicleProfile,
    operational_delay_minutes: float = 0.0,
    expected_destination_dwell_minutes: float = 0.0,
    recovered_minutes: float = 0.0,
) -> EtaResult:
    """Calculate ETA from current route progress and operational state.

    Recovery may reduce accumulated operational delay, but never below zero.
    """
    if operational_delay_minutes < 0:
        raise ValueError("operational_delay_minutes cannot be negative")
    if expected_destination_dwell_minutes < 0:
        raise ValueError("expected_destination_dwell_minutes cannot be negative")
    if recovered_minutes < 0:
        raise ValueError("recovered_minutes cannot be negative")

    remaining_km = remaining_distance_km(
        route_state.profile,
        shipment.route_progress_pct,
    )

    speed = calculate_target_speed(
        route_state,
        vehicle_profile,
    ).target_kmh

    if remaining_km > 0 and speed <= 0:
        raise ValueError(
            "effective speed must be positive while route distance remains"
        )

    travel_minutes = 0.0
    if remaining_km > 0:
        travel_minutes = (remaining_km / speed) * 60.0

    net_operational_delay = max(
        0.0,
        operational_delay_minutes - recovered_minutes,
    )

    eta = now + timedelta(
        minutes=(
            travel_minutes
            + net_operational_delay
            + expected_destination_dwell_minutes
        )
    )

    return EtaResult(
        estimated_arrival=eta,
        remaining_distance_km=remaining_km,
        effective_speed_kmh=speed,
        remaining_travel_minutes=travel_minutes,
        operational_delay_minutes=net_operational_delay,
        expected_destination_dwell_minutes=expected_destination_dwell_minutes,
        recovered_minutes=min(recovered_minutes, operational_delay_minutes),
    )


def apply_eta(shipment: Shipment, result: EtaResult) -> None:
    """Update the shipment's current ETA from a calculated result."""
    shipment.estimated_arrival = result.estimated_arrival


def classify_performance(
    shipment: Shipment,
    *,
    at_risk_threshold_min: float,
) -> ShipmentPerformance:
    """Derive delivery-performance state from authoritative timestamps."""
    if at_risk_threshold_min < 0:
        raise ValueError("at_risk_threshold_min cannot be negative")

    if shipment.lifecycle_status.value in ("ARRIVED", "DELIVERED"):
        if shipment.actual_arrival is None:
            raise ValueError(
                "arrived/delivered shipment requires actual_arrival"
            )

        if shipment.actual_arrival > shipment.scheduled_arrival:
            return ShipmentPerformance.LATE

        return ShipmentPerformance.ON_TIME

    if shipment.estimated_arrival > shipment.scheduled_arrival:
        return ShipmentPerformance.LATE

    slack = shipment.scheduled_arrival - shipment.estimated_arrival

    if slack <= timedelta(minutes=at_risk_threshold_min):
        return ShipmentPerformance.AT_RISK

    return ShipmentPerformance.ON_TIME


def eta_change_minutes(
    previous_eta: datetime,
    new_eta: datetime,
) -> float:
    """Return signed ETA movement in minutes.

    Positive means ETA moved later; negative means ETA improved.
    """
    return (new_eta - previous_eta).total_seconds() / 60.0


def is_material_eta_change(
    previous_eta: datetime,
    new_eta: datetime,
    *,
    threshold_minutes: float,
) -> bool:
    """Return True when ETA movement meets the event threshold."""
    if threshold_minutes <= 0:
        raise ValueError("threshold_minutes must be positive")

    return abs(eta_change_minutes(previous_eta, new_eta)) >= threshold_minutes


def calculate_eta_with_temporary_traffic(
    *,
    now: datetime,
    shipment: Shipment,
    route_state: RouteState,
    vehicle_profile: VehicleProfile,
    disruption_end: datetime,
    normal_traffic_factor: float,
    operational_delay_minutes: float = 0.0,
    expected_destination_dwell_minutes: float = 0.0,
    recovered_minutes: float = 0.0,
) -> EtaResult:
    """Forecast ETA for a temporary traffic disruption.

    The current RouteState may contain a reduced traffic factor. This function
    applies that reduced speed only until ``disruption_end``. Any remaining
    route distance is then forecast using ``normal_traffic_factor``.

    This prevents a short-lived traffic event from being projected across the
    entire remaining route.
    """
    if disruption_end < now:
        raise ValueError("disruption_end cannot precede now")
    if normal_traffic_factor <= 0:
        raise ValueError("normal_traffic_factor must be positive")
    if operational_delay_minutes < 0:
        raise ValueError("operational_delay_minutes cannot be negative")
    if expected_destination_dwell_minutes < 0:
        raise ValueError("expected_destination_dwell_minutes cannot be negative")
    if recovered_minutes < 0:
        raise ValueError("recovered_minutes cannot be negative")

    remaining_km = remaining_distance_km(
        route_state.profile,
        shipment.route_progress_pct,
    )

    disrupted_speed = calculate_target_speed(
        route_state,
        vehicle_profile,
    ).target_kmh

    normal_state = RouteState(
        profile=route_state.profile,
        traffic_factor=normal_traffic_factor,
        weather_factor=route_state.weather_factor,
        temporary_speed_factor=route_state.temporary_speed_factor,
    )
    normal_speed = calculate_target_speed(
        normal_state,
        vehicle_profile,
    ).target_kmh

    if remaining_km > 0 and disrupted_speed <= 0:
        raise ValueError(
            "disrupted speed must be positive while route distance remains"
        )
    if remaining_km > 0 and normal_speed <= 0:
        raise ValueError(
            "normal speed must be positive while route distance remains"
        )

    disruption_minutes_remaining = max(
        0.0,
        (disruption_end - now).total_seconds() / 60.0,
    )
    disrupted_distance_capacity = (
        disrupted_speed * (disruption_minutes_remaining / 60.0)
    )

    if remaining_km <= disrupted_distance_capacity:
        travel_minutes = (
            (remaining_km / disrupted_speed) * 60.0
            if remaining_km > 0
            else 0.0
        )
    else:
        remaining_after_disruption = max(
            0.0,
            remaining_km - disrupted_distance_capacity,
        )
        normal_minutes = (
            (remaining_after_disruption / normal_speed) * 60.0
            if remaining_after_disruption > 0
            else 0.0
        )
        travel_minutes = disruption_minutes_remaining + normal_minutes

    net_operational_delay = max(
        0.0,
        operational_delay_minutes - recovered_minutes,
    )

    eta = now + timedelta(
        minutes=(
            travel_minutes
            + net_operational_delay
            + expected_destination_dwell_minutes
        )
    )

    effective_speed = 0.0
    if travel_minutes > 0 and remaining_km > 0:
        effective_speed = remaining_km / (travel_minutes / 60.0)

    return EtaResult(
        estimated_arrival=eta,
        remaining_distance_km=remaining_km,
        effective_speed_kmh=effective_speed,
        remaining_travel_minutes=travel_minutes,
        operational_delay_minutes=net_operational_delay,
        expected_destination_dwell_minutes=expected_destination_dwell_minutes,
        recovered_minutes=min(recovered_minutes, operational_delay_minutes),
    )


def calculate_eta_with_temporary_weather(
    *,
    now: datetime,
    shipment: Shipment,
    route_state: RouteState,
    vehicle_profile: VehicleProfile,
    disruption_end: datetime,
    normal_weather_factor: float,
    operational_delay_minutes: float = 0.0,
    expected_destination_dwell_minutes: float = 0.0,
    recovered_minutes: float = 0.0,
) -> EtaResult:
    """Forecast ETA for a temporary weather disruption.

    The reduced ``weather_factor`` applies only until ``disruption_end``.
    Remaining route distance is then forecast using ``normal_weather_factor``.
    """
    if disruption_end < now:
        raise ValueError("disruption_end cannot precede now")
    if normal_weather_factor <= 0:
        raise ValueError("normal_weather_factor must be positive")
    if operational_delay_minutes < 0:
        raise ValueError("operational_delay_minutes cannot be negative")
    if expected_destination_dwell_minutes < 0:
        raise ValueError("expected_destination_dwell_minutes cannot be negative")
    if recovered_minutes < 0:
        raise ValueError("recovered_minutes cannot be negative")

    remaining_km = remaining_distance_km(
        route_state.profile,
        shipment.route_progress_pct,
    )

    disrupted_speed = calculate_target_speed(
        route_state,
        vehicle_profile,
    ).target_kmh

    normal_state = RouteState(
        profile=route_state.profile,
        traffic_factor=route_state.traffic_factor,
        weather_factor=normal_weather_factor,
        temporary_speed_factor=route_state.temporary_speed_factor,
    )
    normal_speed = calculate_target_speed(
        normal_state,
        vehicle_profile,
    ).target_kmh

    if remaining_km > 0 and disrupted_speed <= 0:
        raise ValueError(
            "disrupted speed must be positive while route distance remains"
        )
    if remaining_km > 0 and normal_speed <= 0:
        raise ValueError(
            "normal speed must be positive while route distance remains"
        )

    disruption_minutes_remaining = max(
        0.0,
        (disruption_end - now).total_seconds() / 60.0,
    )
    disrupted_distance_capacity = (
        disrupted_speed * (disruption_minutes_remaining / 60.0)
    )

    if remaining_km <= disrupted_distance_capacity:
        travel_minutes = (
            (remaining_km / disrupted_speed) * 60.0
            if remaining_km > 0
            else 0.0
        )
    else:
        remaining_after_disruption = max(
            0.0,
            remaining_km - disrupted_distance_capacity,
        )
        normal_minutes = (
            (remaining_after_disruption / normal_speed) * 60.0
            if remaining_after_disruption > 0
            else 0.0
        )
        travel_minutes = disruption_minutes_remaining + normal_minutes

    net_operational_delay = max(
        0.0,
        operational_delay_minutes - recovered_minutes,
    )

    eta = now + timedelta(
        minutes=(
            travel_minutes
            + net_operational_delay
            + expected_destination_dwell_minutes
        )
    )

    effective_speed = 0.0
    if travel_minutes > 0 and remaining_km > 0:
        effective_speed = remaining_km / (travel_minutes / 60.0)

    return EtaResult(
        estimated_arrival=eta,
        remaining_distance_km=remaining_km,
        effective_speed_kmh=effective_speed,
        remaining_travel_minutes=travel_minutes,
        operational_delay_minutes=net_operational_delay,
        expected_destination_dwell_minutes=expected_destination_dwell_minutes,
        recovered_minutes=min(recovered_minutes, operational_delay_minutes),
    )
