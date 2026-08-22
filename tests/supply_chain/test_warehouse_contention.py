from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.models import (
    Priority,
    Shipment,
    VehicleProfile,
    VehicleState,
    WarehouseOperatingState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.warehouse_contention import (
    request_operation,
    run_warehouse_contention,
    try_start_operation,
    update_queue_depth,
)


def shipment(shipment_id: int) -> Shipment:
    start = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    return Shipment(
        shipment_id=shipment_id,
        run_id=1,
        vehicle_id=shipment_id,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=start,
        scheduled_arrival=start + timedelta(hours=1),
        estimated_arrival=start + timedelta(hours=1),
    )


def vehicle(vehicle_id: int) -> VehicleState:
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
        current_warehouse_id=1,
        lat=0.0,
        lon=0.0,
    )


def warehouse(
    *,
    loading_capacity: int = 1,
    unloading_capacity: int = 1,
) -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=1,
            warehouse_name="W1",
            lat=0.0,
            lon=0.0,
            timezone="UTC",
            loading_capacity=loading_capacity,
            unloading_capacity=unloading_capacity,
            baseline_loading_min=10.0,
            baseline_unloading_min=10.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )


def test_second_loading_operation_waits_when_capacity_full() -> None:
    wh = warehouse(loading_capacity=1)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    first = request_operation(
        shipment=shipment(1),
        vehicle=vehicle(1),
        warehouse=wh,
        operation_type="LOADING",
        requested_at=now,
        duration_minutes=10,
    )
    second = request_operation(
        shipment=shipment(2),
        vehicle=vehicle(2),
        warehouse=wh,
        operation_type="LOADING",
        requested_at=now,
        duration_minutes=10,
    )

    assert try_start_operation(first, now=now)
    assert not try_start_operation(second, now=now)


def test_queue_depth_is_derived_from_waiting_operations() -> None:
    wh = warehouse(loading_capacity=1)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    operations = [
        request_operation(
            shipment=shipment(i),
            vehicle=vehicle(i),
            warehouse=wh,
            operation_type="LOADING",
            requested_at=now,
            duration_minutes=10,
        )
        for i in (1, 2, 3)
    ]

    try_start_operation(operations[0], now=now)
    depth = update_queue_depth(wh, operations)

    assert depth == 2
    assert wh.queue_depth == 2


def test_contention_delays_second_operation() -> None:
    wh = warehouse(loading_capacity=1)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    operations = [
        request_operation(
            shipment=shipment(i),
            vehicle=vehicle(i),
            warehouse=wh,
            operation_type="LOADING",
            requested_at=now,
            duration_minutes=10,
        )
        for i in (1, 2)
    ]

    result = run_warehouse_contention(
        operations=operations,
        start_time=now,
        tick_seconds=60,
    )

    first, second = result.operations

    assert first.started_at == now
    assert first.completed_at == now + timedelta(minutes=10)
    assert second.started_at >= first.completed_at
    assert second.completed_at >= second.started_at + timedelta(minutes=10)


def test_contention_produces_nonzero_queue_telemetry() -> None:
    wh = warehouse(loading_capacity=1)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    operations = [
        request_operation(
            shipment=shipment(i),
            vehicle=vehicle(i),
            warehouse=wh,
            operation_type="LOADING",
            requested_at=now,
            duration_minutes=10,
        )
        for i in (1, 2, 3)
    ]

    result = run_warehouse_contention(
        operations=operations,
        start_time=now,
        tick_seconds=60,
    )

    assert any(
        sample.row.queue_depth > 0
        for sample in result.telemetry_samples
    )


def test_congestion_state_appears_under_heavy_queue() -> None:
    wh = warehouse(
        loading_capacity=1,
        unloading_capacity=1,
    )
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    operations = [
        request_operation(
            shipment=shipment(i),
            vehicle=vehicle(i),
            warehouse=wh,
            operation_type="LOADING",
            requested_at=now,
            duration_minutes=10,
        )
        for i in range(1, 6)
    ]

    result = run_warehouse_contention(
        operations=operations,
        start_time=now,
        tick_seconds=60,
    )

    assert any(
        sample.row.operating_state
        == WarehouseOperatingState.CONGESTED.value
        for sample in result.telemetry_samples
    )


def test_loading_and_unloading_have_separate_capacity() -> None:
    wh = warehouse(
        loading_capacity=1,
        unloading_capacity=1,
    )
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    loading = request_operation(
        shipment=shipment(1),
        vehicle=vehicle(1),
        warehouse=wh,
        operation_type="LOADING",
        requested_at=now,
        duration_minutes=10,
    )
    unloading = request_operation(
        shipment=shipment(2),
        vehicle=vehicle(2),
        warehouse=wh,
        operation_type="UNLOADING",
        requested_at=now,
        duration_minutes=10,
    )

    assert try_start_operation(loading, now=now)
    assert try_start_operation(unloading, now=now)
    assert wh.active_loading_count == 1
    assert wh.active_unloading_count == 1
