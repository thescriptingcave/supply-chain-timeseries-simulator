from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.engine import execute_single_shipment
from generators.supply_chain.models import (
    CargoProfile,
    Priority,
    RouteProfile,
    RouteState,
    ShipmentLifecycle,
    VehicleAvailability,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)


def make_context() -> SimulationContext:
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    return SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=2),
        seed=42,
        run_id=100,
    )


def make_warehouse(
    warehouse_id: int,
    *,
    loading_min: float = 20.0,
    unloading_min: float = 20.0,
    cold_storage: bool = True,
) -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=warehouse_id,
            warehouse_name=f"Warehouse {warehouse_id}",
            lat=float(warehouse_id - 1) * 10.0,
            lon=float(warehouse_id - 1) * 20.0,
            timezone="UTC",
            loading_capacity=5,
            unloading_capacity=5,
            baseline_loading_min=loading_min,
            baseline_unloading_min=unloading_min,
            congestion_sensitivity=1.0,
            cold_storage_capable=cold_storage,
        )
    )


def make_route() -> RouteProfile:
    return RouteProfile(
        route_id=10,
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


def make_vehicle(
    *,
    vehicle_id: int = 1,
    warehouse_id: int = 1,
    fuel: float = 80.0,
    reefer: bool = False,
) -> VehicleState:
    profile = VehicleProfile(
        vehicle_id=vehicle_id,
        vehicle_reg=f"TEST-{vehicle_id}",
        vehicle_type="REEFER" if reefer else "DRY_VAN",
        max_payload_kg=10000,
        fuel_type="DIESEL",
        fleet_operator="TEST",
        year_manufactured=2022,
        fuel_efficiency_factor=1.0,
        reliability_factor=1.0,
        condition_factor=1.0,
        cruise_speed_factor=1.0,
        maintenance_risk_factor=1.0,
        reefer_capable=reefer,
    )

    return VehicleState(
        profile=profile,
        current_warehouse_id=warehouse_id,
        lat=0.0,
        lon=0.0,
        fuel_level_pct=fuel,
        odometer_km=1000.0,
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


def test_executes_one_shipment_end_to_end() -> None:
    context = make_context()
    route = make_route()
    vehicle = make_vehicle()

    result = execute_single_shipment(
        context=context,
        route=route,
        route_state=RouteState(profile=route),
        vehicles=[vehicle],
        origin_warehouse=make_warehouse(1),
        destination_warehouse=make_warehouse(2),
        cargo=make_cargo(),
        priority=Priority.STANDARD,
        shipment_id=1,
    )

    shipment = result.shipment

    assert shipment.lifecycle_status == ShipmentLifecycle.DELIVERED
    assert shipment.actual_departure is not None
    assert shipment.actual_arrival is not None
    assert shipment.delivery_completed_at is not None
    assert shipment.actual_departure < shipment.actual_arrival
    assert shipment.actual_arrival <= shipment.delivery_completed_at
    assert result.movement_ticks > 1

    assert vehicle.availability == VehicleAvailability.AVAILABLE
    assert vehicle.active_shipment_id is None
    assert vehicle.current_warehouse_id == 2


def test_engine_emits_telemetry_per_movement_tick_plus_arrival() -> None:
    context = make_context()
    route = make_route()

    result = execute_single_shipment(
        context=context,
        route=route,
        route_state=RouteState(profile=route),
        vehicles=[make_vehicle()],
        origin_warehouse=make_warehouse(1),
        destination_warehouse=make_warehouse(2),
        cargo=make_cargo(),
        shipment_id=8,
    )

    assert len(result.telemetry_samples) == result.movement_ticks + 1
    assert all(sample.row.shipment_id == 8 for sample in result.telemetry_samples)


def test_engine_telemetry_progresses_to_destination() -> None:
    context = make_context()
    route = make_route()

    result = execute_single_shipment(
        context=context,
        route=route,
        route_state=RouteState(profile=route),
        vehicles=[make_vehicle()],
        origin_warehouse=make_warehouse(1),
        destination_warehouse=make_warehouse(2),
        cargo=make_cargo(),
        shipment_id=9,
    )

    first = result.telemetry_samples[0].row
    last = result.telemetry_samples[-1].row

    assert first.lat < last.lat
    assert first.lon < last.lon
    assert last.lat == pytest.approx(10.0)
    assert last.lon == pytest.approx(20.0)
    assert last.geofence_zone == "DESTINATION_WAREHOUSE"


def test_engine_telemetry_fuel_and_odometer_are_monotonic() -> None:
    context = make_context()
    route = make_route()

    result = execute_single_shipment(
        context=context,
        route=route,
        route_state=RouteState(profile=route),
        vehicles=[make_vehicle(fuel=80.0)],
        origin_warehouse=make_warehouse(1),
        destination_warehouse=make_warehouse(2),
        cargo=make_cargo(),
        shipment_id=10,
    )

    fuels = [sample.row.fuel_level_pct for sample in result.telemetry_samples]
    odometers = [sample.row.odometer_km for sample in result.telemetry_samples]

    assert fuels == sorted(fuels, reverse=True)
    assert odometers == sorted(odometers)


def test_execution_updates_odometer_and_fuel() -> None:
    context = make_context()
    vehicle = make_vehicle(fuel=80.0)
    route = make_route()

    result = execute_single_shipment(
        context=context,
        route=route,
        route_state=RouteState(profile=route),
        vehicles=[vehicle],
        origin_warehouse=make_warehouse(1),
        destination_warehouse=make_warehouse(2),
        cargo=make_cargo(),
        shipment_id=2,
    )

    assert result.distance_travelled_km == pytest.approx(600.0)
    assert result.final_odometer_km == pytest.approx(1600.0)
    assert result.fuel_used_pct == pytest.approx(24.0)
    assert vehicle.fuel_level_pct == pytest.approx(56.0)


def test_execution_preserves_original_schedule() -> None:
    context = make_context()
    route = make_route()

    result = execute_single_shipment(
        context=context,
        route=route,
        route_state=RouteState(profile=route, traffic_factor=0.75),
        vehicles=[make_vehicle()],
        origin_warehouse=make_warehouse(1),
        destination_warehouse=make_warehouse(2),
        cargo=make_cargo(),
        priority=Priority.STANDARD,
        shipment_id=3,
    )

    expected_schedule_minutes = 450.0 + 45.0
    assert (
        result.shipment.scheduled_arrival
        - result.shipment.scheduled_departure
    ).total_seconds() / 60 == pytest.approx(expected_schedule_minutes)


def test_execution_rejects_route_origin_mismatch() -> None:
    context = make_context()
    route = make_route()

    with pytest.raises(ValueError):
        execute_single_shipment(
            context=context,
            route=route,
            route_state=RouteState(profile=route),
            vehicles=[make_vehicle()],
            origin_warehouse=make_warehouse(3),
            destination_warehouse=make_warehouse(2),
            cargo=make_cargo(),
            shipment_id=4,
        )


def test_execution_rejects_incompatible_reefer_assignment() -> None:
    context = make_context()
    route = make_route()

    with pytest.raises(ValueError):
        execute_single_shipment(
            context=context,
            route=route,
            route_state=RouteState(profile=route),
            vehicles=[make_vehicle(reefer=False)],
            origin_warehouse=make_warehouse(1, cold_storage=True),
            destination_warehouse=make_warehouse(2, cold_storage=True),
            cargo=make_cargo(reefer=True),
            shipment_id=5,
        )


def test_congestion_extends_actual_arrival() -> None:
    normal_context = make_context()
    congested_context = make_context()
    route = make_route()

    normal = execute_single_shipment(
        context=normal_context,
        route=route,
        route_state=RouteState(profile=route, traffic_factor=1.0),
        vehicles=[make_vehicle(vehicle_id=1)],
        origin_warehouse=make_warehouse(1),
        destination_warehouse=make_warehouse(2),
        cargo=make_cargo(),
        shipment_id=6,
    )

    congested = execute_single_shipment(
        context=congested_context,
        route=route,
        route_state=RouteState(profile=route, traffic_factor=0.6),
        vehicles=[make_vehicle(vehicle_id=2)],
        origin_warehouse=make_warehouse(1),
        destination_warehouse=make_warehouse(2),
        cargo=make_cargo(),
        shipment_id=7,
    )

    assert congested.shipment.actual_arrival > normal.shipment.actual_arrival
