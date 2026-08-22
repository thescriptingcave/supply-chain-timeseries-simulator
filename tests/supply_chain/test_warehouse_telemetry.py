import pytest

from generators.supply_chain.models import (
    WarehouseOperatingState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.warehouse_telemetry import (
    make_warehouse_telemetry_row,
)


def make_warehouse() -> WarehouseState:
    profile = WarehouseProfile(
        warehouse_id=1,
        warehouse_name="Test Warehouse",
        lat=0.0,
        lon=0.0,
        timezone="UTC",
        loading_capacity=5,
        unloading_capacity=4,
        baseline_loading_min=20.0,
        baseline_unloading_min=18.0,
        congestion_sensitivity=1.0,
        cold_storage_capable=True,
    )
    return WarehouseState(profile=profile)


def test_row_reflects_warehouse_state() -> None:
    warehouse = make_warehouse()
    warehouse.active_loading_count = 3
    warehouse.active_unloading_count = 2
    warehouse.queue_depth = 4
    warehouse.congestion_factor = 1.45
    warehouse.operating_state = WarehouseOperatingState.CONGESTED

    row = make_warehouse_telemetry_row(
        warehouse=warehouse,
        temperature_c=22.5,
        humidity_pct=48.0,
    )

    assert row.warehouse_id == 1
    assert row.temperature_c == pytest.approx(22.5)
    assert row.humidity_pct == pytest.approx(48.0)
    assert row.loading_bays_active == 3
    assert row.unloading_bays_active == 2
    assert row.queue_depth == 4
    assert row.congestion_factor == pytest.approx(1.45)
    assert row.operating_state == "CONGESTED"


def test_rejects_invalid_humidity() -> None:
    with pytest.raises(ValueError):
        make_warehouse_telemetry_row(
            warehouse=make_warehouse(),
            temperature_c=20.0,
            humidity_pct=101.0,
        )


def test_rejects_loading_over_capacity() -> None:
    warehouse = make_warehouse()
    warehouse.active_loading_count = 6

    with pytest.raises(ValueError):
        make_warehouse_telemetry_row(
            warehouse=warehouse,
            temperature_c=20.0,
            humidity_pct=50.0,
        )


def test_rejects_unloading_over_capacity() -> None:
    warehouse = make_warehouse()
    warehouse.active_unloading_count = 5

    with pytest.raises(ValueError):
        make_warehouse_telemetry_row(
            warehouse=warehouse,
            temperature_c=20.0,
            humidity_pct=50.0,
        )


def test_rejects_negative_queue_depth() -> None:
    warehouse = make_warehouse()
    warehouse.queue_depth = -1

    with pytest.raises(ValueError):
        make_warehouse_telemetry_row(
            warehouse=warehouse,
            temperature_c=20.0,
            humidity_pct=50.0,
        )
