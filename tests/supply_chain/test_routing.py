import pytest

from generators.supply_chain.models import (
    RouteProfile,
    RouteState,
    VehicleProfile,
)
from generators.supply_chain.routing import (
    apply_route_factors,
    calculate_target_speed,
    remaining_distance_km,
    validate_route_profile,
)


def make_route(
    *,
    origin: int = 1,
    dest: int = 2,
    nominal: float = 80.0,
    minimum: float = 30.0,
    maximum: float = 100.0,
    distance: float = 600.0,
) -> RouteProfile:
    return RouteProfile(
        route_id=1,
        origin_wh_id=origin,
        dest_wh_id=dest,
        distance_km=distance,
        nominal_speed_kmh=nominal,
        minimum_speed_kmh=minimum,
        maximum_speed_kmh=maximum,
        baseline_travel_min=450.0,
        congestion_sensitivity=1.0,
        weather_sensitivity=1.0,
        morning_peak_factor=1.0,
        evening_peak_factor=1.0,
        overnight_factor=1.0,
        demand_weight=1.0,
        disruption_probability=0.01,
    )


def make_vehicle(cruise_factor: float = 1.0) -> VehicleProfile:
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
        cruise_speed_factor=cruise_factor,
        maintenance_risk_factor=1.0,
        reefer_capable=False,
    )


def test_directional_routes_are_distinct_profiles() -> None:
    a_to_b = make_route(origin=1, dest=2)
    b_to_a = make_route(origin=2, dest=1)

    assert (a_to_b.origin_wh_id, a_to_b.dest_wh_id) != (
        b_to_a.origin_wh_id,
        b_to_a.dest_wh_id,
    )


def test_target_speed_uses_route_and_vehicle_factors() -> None:
    state = RouteState(profile=make_route())
    state.traffic_factor = 0.8
    state.weather_factor = 0.9
    vehicle = make_vehicle(cruise_factor=1.05)

    result = calculate_target_speed(state, vehicle)

    assert result.unclamped_kmh == pytest.approx(80 * 0.8 * 0.9 * 1.05)
    assert result.target_kmh == pytest.approx(result.unclamped_kmh)


def test_target_speed_clamps_to_minimum() -> None:
    state = RouteState(profile=make_route(minimum=30.0))
    state.traffic_factor = 0.1

    result = calculate_target_speed(state, make_vehicle())

    assert result.unclamped_kmh == pytest.approx(8.0)
    assert result.target_kmh == pytest.approx(30.0)


def test_target_speed_clamps_to_maximum() -> None:
    state = RouteState(profile=make_route(maximum=90.0))
    state.traffic_factor = 1.2
    state.weather_factor = 1.1

    result = calculate_target_speed(state, make_vehicle(cruise_factor=1.1))

    assert result.unclamped_kmh > 90.0
    assert result.target_kmh == pytest.approx(90.0)


def test_remaining_distance() -> None:
    route = make_route(distance=600.0)

    assert remaining_distance_km(route, 0.0) == pytest.approx(600.0)
    assert remaining_distance_km(route, 25.0) == pytest.approx(450.0)
    assert remaining_distance_km(route, 100.0) == pytest.approx(0.0)


def test_remaining_distance_rejects_invalid_progress() -> None:
    route = make_route()

    with pytest.raises(ValueError):
        remaining_distance_km(route, -1.0)

    with pytest.raises(ValueError):
        remaining_distance_km(route, 101.0)


def test_route_profile_validation_rejects_same_origin_destination() -> None:
    with pytest.raises(ValueError):
        validate_route_profile(make_route(origin=1, dest=1))


def test_apply_route_factors_updates_state() -> None:
    state = RouteState(profile=make_route())

    apply_route_factors(
        state,
        traffic_factor=0.7,
        weather_factor=0.85,
        temporary_speed_factor=0.95,
    )

    assert state.traffic_factor == pytest.approx(0.7)
    assert state.weather_factor == pytest.approx(0.85)
    assert state.temporary_speed_factor == pytest.approx(0.95)


def test_apply_route_factors_rejects_negative_values() -> None:
    state = RouteState(profile=make_route())

    with pytest.raises(ValueError):
        apply_route_factors(state, traffic_factor=-0.1)
