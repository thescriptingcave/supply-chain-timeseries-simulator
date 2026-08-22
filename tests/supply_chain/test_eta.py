from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.eta import (
    apply_eta,
    calculate_eta,
    classify_performance,
    eta_change_minutes,
    is_material_eta_change,
)
from generators.supply_chain.models import (
    Priority,
    RouteProfile,
    RouteState,
    Shipment,
    ShipmentLifecycle,
    ShipmentPerformance,
    VehicleProfile,
)


def make_route() -> RouteProfile:
    return RouteProfile(
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        distance_km=600.0,
        nominal_speed_kmh=80.0,
        minimum_speed_kmh=30.0,
        maximum_speed_kmh=100.0,
        baseline_travel_min=450.0,
        congestion_sensitivity=1.0,
        weather_sensitivity=1.0,
        morning_peak_factor=1.0,
        evening_peak_factor=1.0,
        overnight_factor=1.0,
        demand_weight=1.0,
        disruption_probability=0.01,
    )


def make_vehicle() -> VehicleProfile:
    return VehicleProfile(
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
    )


def make_shipment() -> Shipment:
    departure = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    return Shipment(
        shipment_id=1,
        run_id=1,
        vehicle_id=1,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=departure,
        scheduled_arrival=departure + timedelta(hours=8),
        estimated_arrival=departure + timedelta(hours=8),
        lifecycle_status=ShipmentLifecycle.IN_TRANSIT,
        actual_departure=departure,
        route_progress_pct=50.0,
    )


def test_eta_uses_remaining_distance_and_speed() -> None:
    shipment = make_shipment()
    route_state = RouteState(profile=make_route())

    result = calculate_eta(
        now=shipment.actual_departure + timedelta(hours=2),
        shipment=shipment,
        route_state=route_state,
        vehicle_profile=make_vehicle(),
    )

    assert result.remaining_distance_km == pytest.approx(300.0)
    assert result.effective_speed_kmh == pytest.approx(80.0)
    assert result.remaining_travel_minutes == pytest.approx(225.0)


def test_traffic_disruption_moves_eta_later() -> None:
    shipment = make_shipment()
    normal = RouteState(profile=make_route())
    congested = RouteState(profile=make_route(), traffic_factor=0.5)
    now = shipment.actual_departure + timedelta(hours=2)

    normal_eta = calculate_eta(
        now=now,
        shipment=shipment,
        route_state=normal,
        vehicle_profile=make_vehicle(),
    )

    congested_eta = calculate_eta(
        now=now,
        shipment=shipment,
        route_state=congested,
        vehicle_profile=make_vehicle(),
    )

    assert congested_eta.estimated_arrival > normal_eta.estimated_arrival


def test_recovery_reduces_operational_delay() -> None:
    shipment = make_shipment()
    route_state = RouteState(profile=make_route())

    result = calculate_eta(
        now=shipment.actual_departure + timedelta(hours=2),
        shipment=shipment,
        route_state=route_state,
        vehicle_profile=make_vehicle(),
        operational_delay_minutes=30.0,
        recovered_minutes=12.0,
    )

    assert result.operational_delay_minutes == pytest.approx(18.0)
    assert result.recovered_minutes == pytest.approx(12.0)


def test_recovery_cannot_make_delay_negative() -> None:
    shipment = make_shipment()

    result = calculate_eta(
        now=shipment.actual_departure + timedelta(hours=2),
        shipment=shipment,
        route_state=RouteState(profile=make_route()),
        vehicle_profile=make_vehicle(),
        operational_delay_minutes=10.0,
        recovered_minutes=25.0,
    )

    assert result.operational_delay_minutes == pytest.approx(0.0)
    assert result.recovered_minutes == pytest.approx(10.0)


def test_apply_eta_updates_shipment() -> None:
    shipment = make_shipment()

    result = calculate_eta(
        now=shipment.actual_departure + timedelta(hours=2),
        shipment=shipment,
        route_state=RouteState(profile=make_route()),
        vehicle_profile=make_vehicle(),
    )

    apply_eta(shipment, result)

    assert shipment.estimated_arrival == result.estimated_arrival


def test_classifies_active_late_shipment() -> None:
    shipment = make_shipment()
    shipment.estimated_arrival = shipment.scheduled_arrival + timedelta(minutes=5)

    assert classify_performance(
        shipment,
        at_risk_threshold_min=15,
    ) == ShipmentPerformance.LATE


def test_classifies_active_at_risk_shipment() -> None:
    shipment = make_shipment()
    shipment.estimated_arrival = shipment.scheduled_arrival - timedelta(minutes=10)

    assert classify_performance(
        shipment,
        at_risk_threshold_min=15,
    ) == ShipmentPerformance.AT_RISK


def test_classifies_active_on_time_shipment() -> None:
    shipment = make_shipment()
    shipment.estimated_arrival = shipment.scheduled_arrival - timedelta(minutes=30)

    assert classify_performance(
        shipment,
        at_risk_threshold_min=15,
    ) == ShipmentPerformance.ON_TIME


def test_completed_performance_uses_actual_arrival() -> None:
    shipment = make_shipment()
    shipment.lifecycle_status = ShipmentLifecycle.DELIVERED
    shipment.actual_arrival = shipment.scheduled_arrival + timedelta(minutes=7)
    shipment.delivery_completed_at = shipment.actual_arrival + timedelta(minutes=20)

    assert classify_performance(
        shipment,
        at_risk_threshold_min=15,
    ) == ShipmentPerformance.LATE


def test_eta_change_minutes_is_signed() -> None:
    old = datetime(2026, 8, 16, 20, 0, tzinfo=timezone.utc)

    assert eta_change_minutes(
        old,
        old + timedelta(minutes=12),
    ) == pytest.approx(12.0)

    assert eta_change_minutes(
        old,
        old - timedelta(minutes=8),
    ) == pytest.approx(-8.0)


def test_material_eta_change_uses_absolute_threshold() -> None:
    old = datetime(2026, 8, 16, 20, 0, tzinfo=timezone.utc)

    assert is_material_eta_change(
        old,
        old + timedelta(minutes=5),
        threshold_minutes=5,
    )

    assert is_material_eta_change(
        old,
        old - timedelta(minutes=6),
        threshold_minutes=5,
    )

    assert not is_material_eta_change(
        old,
        old + timedelta(minutes=4, seconds=59),
        threshold_minutes=5,
    )
