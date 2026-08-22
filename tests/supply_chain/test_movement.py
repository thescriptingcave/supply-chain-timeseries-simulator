import pytest

from generators.supply_chain.models import (
    RouteProfile,
    RouteState,
    VehicleAvailability,
    VehicleProfile,
    VehicleState,
)
from generators.supply_chain.movement import (
    interpolate_position,
    movement_tick,
)


def make_route(distance_km: float = 100.0) -> RouteProfile:
    return RouteProfile(
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        distance_km=distance_km,
        nominal_speed_kmh=60.0,
        minimum_speed_kmh=20.0,
        maximum_speed_kmh=100.0,
        baseline_travel_min=100.0,
        congestion_sensitivity=1.0,
        weather_sensitivity=1.0,
        morning_peak_factor=1.0,
        evening_peak_factor=1.0,
        overnight_factor=1.0,
        demand_weight=1.0,
        disruption_probability=0.01,
    )


def make_vehicle() -> VehicleState:
    profile = VehicleProfile(
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

    return VehicleState(
        profile=profile,
        current_warehouse_id=None,
        lat=0.0,
        lon=0.0,
        fuel_level_pct=100.0,
        odometer_km=1000.0,
        availability=VehicleAvailability.IN_TRANSIT,
        active_shipment_id=1,
    )


def test_interpolates_midpoint() -> None:
    lat, lon = interpolate_position(
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=20.0,
        progress_pct=50.0,
    )

    assert lat == pytest.approx(5.0)
    assert lon == pytest.approx(10.0)


def test_tick_advances_distance_progress_fuel_and_odometer() -> None:
    vehicle = make_vehicle()
    route_state = RouteState(profile=make_route(distance_km=100.0))

    result = movement_tick(
        vehicle=vehicle,
        route_state=route_state,
        elapsed_seconds=600.0,
        current_progress_pct=0.0,
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=20.0,
        base_consumption_pct_per_100km=5.0,
    )

    assert result.distance_km == pytest.approx(10.0)
    assert result.elapsed_seconds == pytest.approx(600.0)
    assert result.route_progress_pct == pytest.approx(10.0)
    assert result.remaining_distance_km == pytest.approx(90.0)
    assert vehicle.odometer_km == pytest.approx(1010.0)
    assert vehicle.fuel_level_pct == pytest.approx(99.5)


def test_final_tick_uses_only_time_needed_to_reach_destination() -> None:
    vehicle = make_vehicle()
    route_state = RouteState(profile=make_route(distance_km=100.0))

    result = movement_tick(
        vehicle=vehicle,
        route_state=route_state,
        elapsed_seconds=3600.0,
        current_progress_pct=80.0,
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=20.0,
        base_consumption_pct_per_100km=5.0,
    )

    # 20 km remaining at 60 km/h = 20 minutes = 1200 seconds.
    assert result.distance_km == pytest.approx(20.0)
    assert result.elapsed_seconds == pytest.approx(1200.0)
    assert result.route_progress_pct == pytest.approx(100.0)
    assert result.remaining_distance_km == pytest.approx(0.0)
    assert vehicle.speed_kmh == pytest.approx(0.0)


def test_completed_route_tick_consumes_no_time() -> None:
    vehicle = make_vehicle()
    route_state = RouteState(profile=make_route(distance_km=100.0))

    result = movement_tick(
        vehicle=vehicle,
        route_state=route_state,
        elapsed_seconds=10.0,
        current_progress_pct=100.0,
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=20.0,
        base_consumption_pct_per_100km=5.0,
    )

    assert result.elapsed_seconds == 0.0
    assert result.distance_km == 0.0
    assert result.route_progress_pct == 100.0


def test_tick_requires_in_transit_vehicle() -> None:
    vehicle = make_vehicle()
    vehicle.availability = VehicleAvailability.AVAILABLE

    with pytest.raises(ValueError):
        movement_tick(
            vehicle=vehicle,
            route_state=RouteState(profile=make_route()),
            elapsed_seconds=10.0,
            current_progress_pct=0.0,
            origin_lat=0.0,
            origin_lon=0.0,
            destination_lat=10.0,
            destination_lon=20.0,
            base_consumption_pct_per_100km=5.0,
        )
