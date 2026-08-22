from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.concurrent_contention import (
    ContendedShipmentPlan,
    run_concurrent_fleet_with_contention,
)
from generators.supply_chain.context import SimulationContext
from generators.supply_chain.models import (
    CargoProfile,
    RouteProfile,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)


def warehouse(
    warehouse_id: int,
    *,
    loading_capacity: int = 1,
    unloading_capacity: int = 1,
) -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=warehouse_id,
            warehouse_name=f"W{warehouse_id}",
            lat=float(warehouse_id),
            lon=float(warehouse_id * 2),
            timezone="UTC",
            loading_capacity=loading_capacity,
            unloading_capacity=unloading_capacity,
            baseline_loading_min=10.0,
            baseline_unloading_min=10.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )


def vehicle(vehicle_id: int, warehouse_id: int) -> VehicleState:
    return VehicleState(
        profile=VehicleProfile(
            vehicle_id=vehicle_id,
            vehicle_reg=f"V{vehicle_id}",
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
        current_warehouse_id=warehouse_id,
        lat=float(warehouse_id),
        lon=float(warehouse_id * 2),
        fuel_level_pct=95.0,
        odometer_km=1000.0,
    )


def route(route_id: int, origin: int, dest: int, km: float) -> RouteProfile:
    return RouteProfile(
        route_id=route_id,
        origin_wh_id=origin,
        dest_wh_id=dest,
        distance_km=km,
        nominal_speed_kmh=60.0,
        minimum_speed_kmh=20.0,
        maximum_speed_kmh=100.0,
        baseline_travel_min=km,
        congestion_sensitivity=1.0,
        weather_sensitivity=1.0,
        morning_peak_factor=1.0,
        evening_peak_factor=1.0,
        overnight_factor=1.0,
        demand_weight=1.0,
        disruption_probability=0.0,
    )


def cargo() -> CargoProfile:
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


def context() -> SimulationContext:
    start = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    return SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=2),
        seed=42,
        run_id=1,
    )


def test_shared_loading_capacity_delays_second_departure() -> None:
    wh1 = warehouse(1, loading_capacity=1)
    wh2 = warehouse(2)

    result = run_concurrent_fleet_with_contention(
        context=context(),
        plans=[
            ContendedShipmentPlan(1, 1, route(1, 1, 2, 60), cargo()),
            ContendedShipmentPlan(2, 2, route(2, 1, 2, 60), cargo()),
        ],
        vehicles=[vehicle(1, 1), vehicle(2, 1)],
        warehouses={1: wh1, 2: wh2},
        movement_interval_seconds=600.0,
        warehouse_tick_seconds=60.0,
        base_consumption_pct_per_100km=1.0,
    )

    first = result.shipments[0].shipment
    second = result.shipments[1].shipment

    assert first.actual_departure is not None
    assert second.actual_departure is not None
    assert second.actual_departure > first.actual_departure


def test_loading_queue_produces_queue_telemetry() -> None:
    result = run_concurrent_fleet_with_contention(
        context=context(),
        plans=[
            ContendedShipmentPlan(1, 1, route(1, 1, 2, 60), cargo()),
            ContendedShipmentPlan(2, 2, route(2, 1, 2, 60), cargo()),
            ContendedShipmentPlan(3, 3, route(3, 1, 2, 60), cargo()),
        ],
        vehicles=[
            vehicle(1, 1),
            vehicle(2, 1),
            vehicle(3, 1),
        ],
        warehouses={
            1: warehouse(1, loading_capacity=1),
            2: warehouse(2),
        },
        warehouse_tick_seconds=60.0,
    )

    assert any(
        sample.row.queue_depth > 0
        for sample in result.warehouse_samples
    )


def test_unloading_contention_delays_delivery_completion() -> None:
    result = run_concurrent_fleet_with_contention(
        context=context(),
        plans=[
            ContendedShipmentPlan(1, 1, route(1, 1, 3, 60), cargo()),
            ContendedShipmentPlan(2, 2, route(2, 2, 3, 60), cargo()),
        ],
        vehicles=[
            vehicle(1, 1),
            vehicle(2, 2),
        ],
        warehouses={
            1: warehouse(1),
            2: warehouse(2),
            3: warehouse(3, unloading_capacity=1),
        },
        movement_interval_seconds=600.0,
        warehouse_tick_seconds=60.0,
        base_consumption_pct_per_100km=1.0,
    )

    deliveries = sorted(
        item.shipment.delivery_completed_at
        for item in result.shipments
    )

    assert deliveries[1] > deliveries[0]


def test_all_shipments_reach_delivered_state() -> None:
    result = run_concurrent_fleet_with_contention(
        context=context(),
        plans=[
            ContendedShipmentPlan(1, 1, route(1, 1, 3, 60), cargo()),
            ContendedShipmentPlan(2, 2, route(2, 2, 3, 120), cargo()),
        ],
        vehicles=[
            vehicle(1, 1),
            vehicle(2, 2),
        ],
        warehouses={
            1: warehouse(1),
            2: warehouse(2),
            3: warehouse(3),
        },
        movement_interval_seconds=600.0,
        warehouse_tick_seconds=60.0,
        base_consumption_pct_per_100km=1.0,
    )

    assert all(
        item.shipment.lifecycle_status.value == "DELIVERED"
        for item in result.shipments
    )


def test_vehicle_is_released_after_delivery() -> None:
    v1 = vehicle(1, 1)
    v2 = vehicle(2, 2)

    run_concurrent_fleet_with_contention(
        context=context(),
        plans=[
            ContendedShipmentPlan(1, 1, route(1, 1, 3, 60), cargo()),
            ContendedShipmentPlan(2, 2, route(2, 2, 3, 60), cargo()),
        ],
        vehicles=[v1, v2],
        warehouses={
            1: warehouse(1),
            2: warehouse(2),
            3: warehouse(3),
        },
        movement_interval_seconds=600.0,
        warehouse_tick_seconds=60.0,
        base_consumption_pct_per_100km=1.0,
    )

    assert v1.availability.value == "AVAILABLE"
    assert v2.availability.value == "AVAILABLE"
    assert v1.active_shipment_id is None
    assert v2.active_shipment_id is None


def test_duplicate_vehicle_plan_is_rejected() -> None:
    with pytest.raises(ValueError):
        run_concurrent_fleet_with_contention(
            context=context(),
            plans=[
                ContendedShipmentPlan(1, 1, route(1, 1, 2, 60), cargo()),
                ContendedShipmentPlan(2, 1, route(2, 1, 2, 60), cargo()),
            ],
            vehicles=[vehicle(1, 1)],
            warehouses={
                1: warehouse(1),
                2: warehouse(2),
            },
        )
