from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.eta import (
    calculate_eta,
    calculate_eta_with_temporary_traffic,
)
from generators.supply_chain.models import (
    Priority,
    RouteProfile,
    RouteState,
    Shipment,
    VehicleProfile,
)


def route_state(*, traffic_factor: float) -> RouteState:
    return RouteState(
        profile=RouteProfile(
            route_id=1,
            origin_wh_id=1,
            dest_wh_id=2,
            distance_km=120.0,
            nominal_speed_kmh=60.0,
            minimum_speed_kmh=20.0,
            maximum_speed_kmh=100.0,
            baseline_travel_min=120.0,
            congestion_sensitivity=1.0,
            weather_sensitivity=1.0,
            morning_peak_factor=1.0,
            evening_peak_factor=1.0,
            overnight_factor=1.0,
            demand_weight=1.0,
            disruption_probability=0.0,
        ),
        traffic_factor=traffic_factor,
    )


def vehicle() -> VehicleProfile:
    return VehicleProfile(
        vehicle_id=1,
        vehicle_reg="V1",
        vehicle_type="DRY_VAN",
        max_payload_kg=10000,
        fuel_type="DIESEL",
        fleet_operator="TEST",
        year_manufactured=2022,
        fuel_efficiency_factor=1.0,
        reliability_factor=1.0,
        condition_factor=1.0,
        cruise_speed_factor=1.0,
        maintenance_risk_factor=1.0,
        reefer_capable=False,
    )


def shipment(now: datetime) -> Shipment:
    return Shipment(
        shipment_id=1,
        run_id=1,
        vehicle_id=1,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=now,
        scheduled_arrival=now + timedelta(hours=3),
        estimated_arrival=now + timedelta(hours=3),
        route_progress_pct=0.0,
    )


def test_temporary_traffic_only_affects_disruption_window() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    s = shipment(now)

    temporary = calculate_eta_with_temporary_traffic(
        now=now,
        shipment=s,
        route_state=route_state(traffic_factor=0.5),
        vehicle_profile=vehicle(),
        disruption_end=now + timedelta(hours=1),
        normal_traffic_factor=1.0,
    )

    # 30 km during one hour at 30 km/h, then 90 km at 60 km/h:
    # total expected travel = 150 minutes.
    assert temporary.remaining_travel_minutes == pytest.approx(150.0)
    assert temporary.estimated_arrival == now + timedelta(minutes=150)


def test_temporary_traffic_eta_is_less_extreme_than_permanent_projection() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    s = shipment(now)
    disrupted_state = route_state(traffic_factor=0.5)

    permanent = calculate_eta(
        now=now,
        shipment=s,
        route_state=disrupted_state,
        vehicle_profile=vehicle(),
    )
    temporary = calculate_eta_with_temporary_traffic(
        now=now,
        shipment=s,
        route_state=disrupted_state,
        vehicle_profile=vehicle(),
        disruption_end=now + timedelta(hours=1),
        normal_traffic_factor=1.0,
    )

    assert temporary.estimated_arrival < permanent.estimated_arrival
    assert temporary.remaining_travel_minutes == pytest.approx(150.0)
    assert permanent.remaining_travel_minutes == pytest.approx(240.0)


def test_route_finishing_inside_disruption_uses_only_disrupted_speed() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    s = shipment(now)
    s.route_progress_pct = 87.5  # 15 km remaining.

    result = calculate_eta_with_temporary_traffic(
        now=now,
        shipment=s,
        route_state=route_state(traffic_factor=0.5),
        vehicle_profile=vehicle(),
        disruption_end=now + timedelta(hours=1),
        normal_traffic_factor=1.0,
    )

    assert result.remaining_travel_minutes == pytest.approx(30.0)


def test_expired_disruption_window_uses_normal_speed() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    s = shipment(now)

    result = calculate_eta_with_temporary_traffic(
        now=now,
        shipment=s,
        route_state=route_state(traffic_factor=0.5),
        vehicle_profile=vehicle(),
        disruption_end=now,
        normal_traffic_factor=1.0,
    )

    assert result.remaining_travel_minutes == pytest.approx(120.0)
