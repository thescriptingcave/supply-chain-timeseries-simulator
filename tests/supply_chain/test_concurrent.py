from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.concurrent import (
    ConcurrentShipmentPlan,
    _advance_if_positive,
    initialize_concurrent_shipments,
    run_concurrent_fleet,
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


def warehouse(i: int) -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=i,
            warehouse_name=f"W{i}",
            lat=float(i),
            lon=float(i * 2),
            timezone="UTC",
            loading_capacity=5,
            unloading_capacity=5,
            baseline_loading_min=0.0,
            baseline_unloading_min=0.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )


def vehicle(i: int, wh: int) -> VehicleState:
    return VehicleState(
        profile=VehicleProfile(
            vehicle_id=i,
            vehicle_reg=f"V{i}",
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
        current_warehouse_id=wh,
        lat=float(wh),
        lon=float(wh * 2),
        fuel_level_pct=95.0,
        odometer_km=1000.0,
    )


def route(
    i: int,
    origin: int,
    dest: int,
    km: float,
) -> RouteProfile:
    return RouteProfile(
        route_id=i,
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


def context(hours: int = 4) -> SimulationContext:
    start = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    return SimulationContext(
        start,
        start + timedelta(hours=hours),
        seed=42,
        run_id=1,
    )


def test_zero_cycle_duration_does_not_advance_context() -> None:
    ctx = context()
    start = ctx.now()

    _advance_if_positive(ctx, 0.0)

    assert ctx.now() == start


def test_sub_microsecond_cycle_does_not_advance_context() -> None:
    ctx = context()
    start = ctx.now()

    _advance_if_positive(ctx, 1e-20)

    assert ctx.now() == start


def test_same_vehicle_cannot_have_overlapping_plans() -> None:
    plans = [
        ConcurrentShipmentPlan(
            1,
            1,
            route(1, 1, 2, 60),
            cargo(),
        ),
        ConcurrentShipmentPlan(
            2,
            1,
            route(2, 1, 2, 60),
            cargo(),
        ),
    ]

    with pytest.raises(ValueError):
        initialize_concurrent_shipments(
            context=context(),
            plans=plans,
            vehicles=[vehicle(1, 1)],
            warehouses={
                1: warehouse(1),
                2: warehouse(2),
            },
        )


def test_two_vehicles_run_on_same_clock() -> None:
    result = run_concurrent_fleet(
        context=context(),
        plans=[
            ConcurrentShipmentPlan(
                1,
                1,
                route(1, 1, 2, 60),
                cargo(),
            ),
            ConcurrentShipmentPlan(
                2,
                2,
                route(2, 3, 4, 120),
                cargo(),
            ),
        ],
        vehicles=[
            vehicle(1, 1),
            vehicle(2, 3),
        ],
        warehouses={
            1: warehouse(1),
            2: warehouse(2),
            3: warehouse(3),
            4: warehouse(4),
        },
        movement_interval_seconds=600.0,
    )

    assert len(result.shipments) == 2
    assert all(
        item.shipment.actual_arrival is not None
        for item in result.shipments
    )
    assert result.telemetry_rows > 0


def test_shorter_route_arrives_first() -> None:
    result = run_concurrent_fleet(
        context=context(),
        plans=[
            ConcurrentShipmentPlan(
                1,
                1,
                route(1, 1, 2, 60),
                cargo(),
            ),
            ConcurrentShipmentPlan(
                2,
                2,
                route(2, 3, 4, 120),
                cargo(),
            ),
        ],
        vehicles=[
            vehicle(1, 1),
            vehicle(2, 3),
        ],
        warehouses={
            1: warehouse(1),
            2: warehouse(2),
            3: warehouse(3),
            4: warehouse(4),
        },
        movement_interval_seconds=600.0,
    )

    assert (
        result.shipments[0].shipment.actual_arrival
        < result.shipments[1].shipment.actual_arrival
    )


def test_exact_arrival_time_not_delayed_to_other_vehicle_tick() -> None:
    result = run_concurrent_fleet(
        context=context(),
        plans=[
            ConcurrentShipmentPlan(
                1,
                1,
                route(1, 1, 2, 65),
                cargo(),
            ),
            ConcurrentShipmentPlan(
                2,
                2,
                route(2, 3, 4, 120),
                cargo(),
            ),
        ],
        vehicles=[
            vehicle(1, 1),
            vehicle(2, 3),
        ],
        warehouses={
            1: warehouse(1),
            2: warehouse(2),
            3: warehouse(3),
            4: warehouse(4),
        },
        movement_interval_seconds=600.0,
    )

    first = result.shipments[0].shipment

    assert (
        first.actual_arrival - first.actual_departure
    ).total_seconds() / 60.0 == pytest.approx(65.0)


def test_vehicle_state_remains_independent() -> None:
    v1 = vehicle(1, 1)
    v2 = vehicle(2, 3)

    run_concurrent_fleet(
        context=context(),
        plans=[
            ConcurrentShipmentPlan(
                1,
                1,
                route(1, 1, 2, 60),
                cargo(),
            ),
            ConcurrentShipmentPlan(
                2,
                2,
                route(2, 3, 4, 120),
                cargo(),
            ),
        ],
        vehicles=[v1, v2],
        warehouses={
            1: warehouse(1),
            2: warehouse(2),
            3: warehouse(3),
            4: warehouse(4),
        },
        movement_interval_seconds=600.0,
    )

    assert v1.odometer_km < v2.odometer_km
    assert v1.fuel_level_pct > v2.fuel_level_pct
