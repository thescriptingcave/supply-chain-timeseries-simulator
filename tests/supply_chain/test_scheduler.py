from datetime import datetime, timezone
from random import Random

import pytest

from generators.supply_chain.models import (
    CargoProfile,
    Priority,
    RouteProfile,
    VehicleAvailability,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.scheduler import (
    choose_route_weighted,
    choose_vehicle,
    eligible_vehicles,
    priority_planning_buffer_minutes,
    scheduled_arrival_from_route,
    validate_shipment_compatibility,
)


def make_vehicle(
    vehicle_id: int,
    *,
    warehouse_id: int = 1,
    reefer: bool = False,
    fuel: float = 80.0,
    reliability: float = 1.0,
    condition: float = 1.0,
    efficiency: float = 1.0,
    maintenance_risk: float = 1.0,
) -> VehicleState:
    profile = VehicleProfile(
        vehicle_id=vehicle_id,
        vehicle_reg=f"TEST-{vehicle_id}",
        vehicle_type="REEFER" if reefer else "DRY_VAN",
        max_payload_kg=10000,
        fuel_type="DIESEL",
        fleet_operator="TEST",
        year_manufactured=2022,
        fuel_efficiency_factor=efficiency,
        reliability_factor=reliability,
        condition_factor=condition,
        cruise_speed_factor=1.0,
        maintenance_risk_factor=maintenance_risk,
        reefer_capable=reefer,
    )

    return VehicleState(
        profile=profile,
        current_warehouse_id=warehouse_id,
        lat=0.0,
        lon=0.0,
        fuel_level_pct=fuel,
    )


def make_cargo(*, reefer: bool = False) -> CargoProfile:
    return CargoProfile(
        cargo_type="FROZEN_FOOD" if reefer else "GENERAL_FREIGHT",
        requires_reefer=reefer,
        target_temp_c=-18.0 if reefer else None,
        min_temp_c=-22.0 if reefer else None,
        max_temp_c=-15.0 if reefer else None,
        target_humidity_pct=65.0 if reefer else None,
        handling_sensitivity=1.0,
        loading_time_factor=1.0,
    )


def make_warehouse(
    warehouse_id: int,
    *,
    cold_storage: bool = True,
) -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=warehouse_id,
            warehouse_name=f"Warehouse {warehouse_id}",
            lat=0.0,
            lon=0.0,
            timezone="UTC",
            loading_capacity=5,
            unloading_capacity=5,
            baseline_loading_min=20.0,
            baseline_unloading_min=20.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=cold_storage,
        )
    )


def make_route(
    route_id: int,
    *,
    origin: int = 1,
    dest: int = 2,
    weight: float = 1.0,
) -> RouteProfile:
    return RouteProfile(
        route_id=route_id,
        origin_wh_id=origin,
        dest_wh_id=dest,
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
        demand_weight=weight,
        disruption_probability=0.01,
    )


def test_reefer_cargo_requires_reefer_vehicle() -> None:
    vehicles = [
        make_vehicle(1, reefer=False),
        make_vehicle(2, reefer=True),
    ]

    selected = choose_vehicle(
        vehicles,
        cargo=make_cargo(reefer=True),
        origin_warehouse_id=1,
        reserve_threshold_pct=15.0,
    )

    assert selected is not None
    assert selected.profile.vehicle_id == 2


def test_vehicle_must_be_at_origin() -> None:
    vehicles = [
        make_vehicle(1, warehouse_id=2),
        make_vehicle(2, warehouse_id=1),
    ]

    selected = choose_vehicle(
        vehicles,
        cargo=make_cargo(),
        origin_warehouse_id=1,
        reserve_threshold_pct=15.0,
    )

    assert selected is not None
    assert selected.profile.vehicle_id == 2


def test_low_fuel_vehicle_is_not_eligible() -> None:
    vehicles = [
        make_vehicle(1, fuel=15.0),
        make_vehicle(2, fuel=50.0),
    ]

    candidates = eligible_vehicles(
        vehicles,
        cargo=make_cargo(),
        origin_warehouse_id=1,
        reserve_threshold_pct=15.0,
    )

    assert [candidate.vehicle_id for candidate in candidates] == [2]


def test_reserved_vehicle_is_not_eligible() -> None:
    reserved = make_vehicle(1)
    reserved.availability = VehicleAvailability.RESERVED
    reserved.active_shipment_id = 99

    selected = choose_vehicle(
        [reserved],
        cargo=make_cargo(),
        origin_warehouse_id=1,
        reserve_threshold_pct=15.0,
    )

    assert selected is None


def test_best_persistent_vehicle_profile_wins() -> None:
    vehicles = [
        make_vehicle(
            1,
            reliability=0.95,
            condition=0.95,
            efficiency=0.98,
            maintenance_risk=1.10,
        ),
        make_vehicle(
            2,
            reliability=1.05,
            condition=1.02,
            efficiency=1.03,
            maintenance_risk=0.90,
        ),
    ]

    selected = choose_vehicle(
        vehicles,
        cargo=make_cargo(),
        origin_warehouse_id=1,
        reserve_threshold_pct=15.0,
    )

    assert selected is not None
    assert selected.profile.vehicle_id == 2


def test_cold_chain_requires_compatible_destination() -> None:
    vehicle = make_vehicle(1, reefer=True)
    origin = make_warehouse(1, cold_storage=True)
    destination = make_warehouse(2, cold_storage=False)

    with pytest.raises(ValueError):
        validate_shipment_compatibility(
            vehicle=vehicle,
            cargo=make_cargo(reefer=True),
            origin_warehouse=origin,
            destination_warehouse=destination,
            reserve_threshold_pct=15.0,
        )


def test_weighted_route_choice_is_deterministic_with_seed() -> None:
    routes = [
        make_route(1, dest=2, weight=1.0),
        make_route(2, dest=3, weight=4.0),
    ]

    a = choose_route_weighted(
        routes,
        origin_warehouse_id=1,
        rng=Random(42),
    )
    b = choose_route_weighted(
        routes,
        origin_warehouse_id=1,
        rng=Random(42),
    )

    assert a.route_id == b.route_id


def test_scheduled_arrival_uses_baseline_plus_buffer() -> None:
    departure = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    arrival = scheduled_arrival_from_route(
        scheduled_departure=departure,
        route=make_route(1),
        planning_buffer_minutes=30.0,
    )

    assert (arrival - departure).total_seconds() / 60 == pytest.approx(480.0)


def test_priority_buffers_are_intentionally_different() -> None:
    assert priority_planning_buffer_minutes(
        Priority.CRITICAL
    ) < priority_planning_buffer_minutes(Priority.EXPEDITED)

    assert priority_planning_buffer_minutes(
        Priority.EXPEDITED
    ) < priority_planning_buffer_minutes(Priority.STANDARD)
