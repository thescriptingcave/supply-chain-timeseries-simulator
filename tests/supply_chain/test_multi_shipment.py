from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.models import (
    CargoProfile,
    RouteProfile,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.multi_shipment import (
    choose_shortest_outbound_route,
    execute_sequential_shipments,
)


def make_route(
    route_id: int,
    origin: int,
    dest: int,
    distance: float,
) -> RouteProfile:
    return RouteProfile(
        route_id=route_id,
        origin_wh_id=origin,
        dest_wh_id=dest,
        distance_km=distance,
        nominal_speed_kmh=60.0,
        minimum_speed_kmh=20.0,
        maximum_speed_kmh=100.0,
        baseline_travel_min=distance,
        congestion_sensitivity=1.0,
        weather_sensitivity=1.0,
        morning_peak_factor=1.0,
        evening_peak_factor=1.0,
        overnight_factor=1.0,
        demand_weight=1.0,
        disruption_probability=0.0,
    )


def make_warehouse(warehouse_id: int) -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=warehouse_id,
            warehouse_name=f"W{warehouse_id}",
            lat=float(warehouse_id),
            lon=float(warehouse_id),
            timezone="UTC",
            loading_capacity=5,
            unloading_capacity=5,
            baseline_loading_min=0.0,
            baseline_unloading_min=0.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )


def make_vehicle() -> VehicleState:
    return VehicleState(
        profile=VehicleProfile(
            vehicle_id=1,
            vehicle_reg="TEST",
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
        current_warehouse_id=1,
        lat=1.0,
        lon=1.0,
        fuel_level_pct=95.0,
        odometer_km=1000.0,
    )


def make_cargo() -> CargoProfile:
    return CargoProfile(
        cargo_type="GENERAL_FREIGHT",
        requires_reefer=False,
        target_temp_c=None,
        min_temp_c=None,
        max_temp_c=None,
        target_humidity_pct=None,
        handling_sensitivity=1.0,
        loading_time_factor=1.0,
    )


def test_shortest_outbound_route_is_selected() -> None:
    routes = [
        make_route(1, 1, 2, 100.0),
        make_route(2, 1, 3, 50.0),
    ]

    selected = choose_shortest_outbound_route(
        current_warehouse_id=1,
        routes=routes,
    )

    assert selected.route_id == 2


def test_two_shipments_chain_vehicle_location() -> None:
    start = datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc)
    context = SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=2),
        seed=42,
        run_id=1,
    )

    routes = [
        make_route(1, 1, 2, 60.0),
        make_route(2, 2, 3, 60.0),
        make_route(3, 3, 1, 60.0),
    ]
    warehouses = {
        1: make_warehouse(1),
        2: make_warehouse(2),
        3: make_warehouse(3),
    }
    vehicle = make_vehicle()

    result = execute_sequential_shipments(
        context=context,
        routes=routes,
        warehouses=warehouses,
        vehicles=[vehicle],
        cargo=make_cargo(),
        shipment_ids=[1, 2],
        base_consumption_pct_per_100km=1.0,
    )

    assert len(result.shipments) == 2
    assert result.shipments[0].shipment.origin_wh_id == 1
    assert result.shipments[0].shipment.dest_wh_id == 2
    assert result.shipments[1].shipment.origin_wh_id == 2
    assert result.shipments[1].shipment.dest_wh_id == 3
    assert vehicle.current_warehouse_id == 3


def test_fuel_and_odometer_persist_across_shipments() -> None:
    start = datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc)
    context = SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=2),
        seed=42,
        run_id=1,
    )

    routes = [
        make_route(1, 1, 2, 100.0),
        make_route(2, 2, 1, 100.0),
    ]
    warehouses = {
        1: make_warehouse(1),
        2: make_warehouse(2),
    }
    vehicle = make_vehicle()

    result = execute_sequential_shipments(
        context=context,
        routes=routes,
        warehouses=warehouses,
        vehicles=[vehicle],
        cargo=make_cargo(),
        shipment_ids=[1, 2],
        base_consumption_pct_per_100km=2.0,
    )

    assert vehicle.odometer_km == pytest.approx(1200.0)
    assert vehicle.fuel_level_pct == pytest.approx(91.0)
    assert result.shipments[1].final_odometer_km > result.shipments[0].final_odometer_km


def test_shipments_do_not_overlap_in_sequential_mode() -> None:
    start = datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc)
    context = SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=2),
        seed=42,
        run_id=1,
    )

    routes = [
        make_route(1, 1, 2, 60.0),
        make_route(2, 2, 1, 60.0),
    ]
    warehouses = {
        1: make_warehouse(1),
        2: make_warehouse(2),
    }

    result = execute_sequential_shipments(
        context=context,
        routes=routes,
        warehouses=warehouses,
        vehicles=[make_vehicle()],
        cargo=make_cargo(),
        shipment_ids=[1, 2],
        base_consumption_pct_per_100km=1.0,
    )

    first = result.shipments[0].shipment
    second = result.shipments[1].shipment

    assert first.delivery_completed_at <= second.scheduled_departure


def test_multi_result_counts_telemetry_and_events() -> None:
    start = datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc)
    context = SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=2),
        seed=42,
        run_id=1,
    )

    routes = [
        make_route(1, 1, 2, 60.0),
        make_route(2, 2, 1, 60.0),
    ]
    warehouses = {
        1: make_warehouse(1),
        2: make_warehouse(2),
    }

    result = execute_sequential_shipments(
        context=context,
        routes=routes,
        warehouses=warehouses,
        vehicles=[make_vehicle()],
        cargo=make_cargo(),
        shipment_ids=[1, 2],
        base_consumption_pct_per_100km=1.0,
    )

    assert result.total_telemetry_rows > 0
    assert result.total_events >= 6
