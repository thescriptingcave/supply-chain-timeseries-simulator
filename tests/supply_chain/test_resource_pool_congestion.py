from datetime import datetime, timedelta, timezone

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
)


def make_wh() -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=1,
            warehouse_name="W1",
            lat=0.0,
            lon=0.0,
            timezone="UTC",
            loading_capacity=1,
            unloading_capacity=5,
            baseline_loading_min=10.0,
            baseline_unloading_min=10.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )


def shipment(i: int) -> Shipment:
    start = datetime(2026, 8, 18, tzinfo=timezone.utc)
    return Shipment(
        shipment_id=i,
        run_id=1,
        vehicle_id=i,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=start,
        scheduled_arrival=start + timedelta(hours=1),
        estimated_arrival=start + timedelta(hours=1),
    )


def vehicle(i: int) -> VehicleState:
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
        current_warehouse_id=1,
        lat=0.0,
        lon=0.0,
    )


def test_loading_queue_uses_loading_capacity_not_combined_capacity() -> None:
    wh = make_wh()
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)

    operations = [
        request_operation(
            shipment=shipment(i),
            vehicle=vehicle(i),
            warehouse=wh,
            operation_type="LOADING",
            requested_at=now,
            duration_minutes=10.0,
        )
        for i in (1, 2, 3)
    ]

    result = run_warehouse_contention(
        operations=operations,
        start_time=now,
        tick_seconds=60.0,
    )

    first = result.telemetry_samples[0].row
    assert first.loading_bays_active == 1
    assert first.queue_depth == 2
    assert first.operating_state == WarehouseOperatingState.CONGESTED.value
    assert first.congestion_factor > 1.0
