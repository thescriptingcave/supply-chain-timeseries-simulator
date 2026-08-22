from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.disruptions import (
    DisruptionType,
    apply_weather_disruption,
    clear_weather_disruption,
    make_disruption_event,
    weather_disruption,
)
from generators.supply_chain.models import (
    Priority,
    RouteProfile,
    RouteState,
    Shipment,
    VehicleProfile,
    VehicleState,
)


def make_route_state() -> RouteState:
    return RouteState(
        profile=RouteProfile(
            route_id=10,
            origin_wh_id=1,
            dest_wh_id=2,
            distance_km=100.0,
            nominal_speed_kmh=80.0,
            minimum_speed_kmh=30.0,
            maximum_speed_kmh=100.0,
            baseline_travel_min=75.0,
            congestion_sensitivity=1.0,
            weather_sensitivity=1.0,
            morning_peak_factor=1.0,
            evening_peak_factor=1.0,
            overnight_factor=1.0,
            demand_weight=1.0,
            disruption_probability=0.01,
        )
    )


def make_vehicle() -> VehicleState:
    return VehicleState(
        profile=VehicleProfile(
            vehicle_id=1,
            vehicle_reg="TEST-1",
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
        ),
        current_warehouse_id=None,
        lat=35.0,
        lon=-112.0,
        fuel_level_pct=80.0,
    )


def make_shipment(start: datetime) -> Shipment:
    return Shipment(
        shipment_id=7,
        run_id=3,
        vehicle_id=1,
        route_id=10,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=start,
        scheduled_arrival=start + timedelta(hours=2),
        estimated_arrival=start + timedelta(hours=2),
    )


def test_weather_disruption_is_active_inside_window() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    disruption = weather_disruption(
        disruption_id="W1",
        start_time=start,
        duration_minutes=45,
        weather_factor=0.7,
        route_id=10,
    )

    assert disruption.disruption_type == DisruptionType.WEATHER
    assert disruption.is_active(start + timedelta(minutes=15))
    assert not disruption.is_active(start + timedelta(minutes=45))


def test_active_weather_reduces_weather_factor() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    route_state = make_route_state()

    disruption = weather_disruption(
        disruption_id="W1",
        start_time=start,
        duration_minutes=45,
        weather_factor=0.7,
        route_id=10,
    )

    result = apply_weather_disruption(
        disruption=disruption,
        now=start + timedelta(minutes=5),
        route_state=route_state,
        vehicle=make_vehicle(),
    )

    assert result.active
    assert result.previous_traffic_factor == pytest.approx(1.0)
    assert route_state.weather_factor == pytest.approx(0.7)


def test_wrong_route_is_not_affected_by_weather() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    route_state = make_route_state()

    disruption = weather_disruption(
        disruption_id="W1",
        start_time=start,
        duration_minutes=45,
        weather_factor=0.7,
        route_id=99,
    )

    result = apply_weather_disruption(
        disruption=disruption,
        now=start + timedelta(minutes=5),
        route_state=route_state,
        vehicle=make_vehicle(),
    )

    assert not result.active
    assert route_state.weather_factor == pytest.approx(1.0)


def test_clear_weather_restores_previous_factor() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    route_state = make_route_state()
    route_state.weather_factor = 0.9

    disruption = weather_disruption(
        disruption_id="W1",
        start_time=start,
        duration_minutes=45,
        weather_factor=0.7,
        route_id=10,
    )

    applied = apply_weather_disruption(
        disruption=disruption,
        now=start + timedelta(minutes=5),
        route_state=route_state,
        vehicle=make_vehicle(),
    )
    clear_weather_disruption(
        applied=applied,
        route_state=route_state,
    )

    assert route_state.weather_factor == pytest.approx(0.9)


def test_weather_event_contains_heavy_rain_cause_code() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    disruption = weather_disruption(
        disruption_id="W1",
        start_time=start,
        duration_minutes=45,
        weather_factor=0.7,
        route_id=10,
    )

    event = make_disruption_event(
        time=start,
        disruption=disruption,
        shipment=make_shipment(start),
        vehicle=make_vehicle(),
    )

    assert event.event_type == "DISRUPTION_STARTED"
    assert event.cause_code == "HEAVY_RAIN"
    assert event.detail["disruption_type"] == "WEATHER"
    assert event.detail["speed_factor"] == pytest.approx(0.7)


def test_invalid_weather_factor_is_rejected() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        weather_disruption(
            disruption_id="W1",
            start_time=start,
            duration_minutes=45,
            weather_factor=1.2,
            route_id=10,
        )
