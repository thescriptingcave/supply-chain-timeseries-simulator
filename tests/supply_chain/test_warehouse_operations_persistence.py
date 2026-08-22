from datetime import datetime, timezone

from generators.supply_chain.models import (
    WarehouseOperatingState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.warehouse_operations_persistence import (
    WAREHOUSE_OPERATION_COLUMNS,
    warehouse_operations_to_row,
)
from generators.supply_chain.warehouse_telemetry import (
    make_warehouse_telemetry_row,
)


def make_warehouse() -> WarehouseState:
    state = WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=1,
            warehouse_name="Test",
            lat=0.0,
            lon=0.0,
            timezone="UTC",
            loading_capacity=5,
            unloading_capacity=5,
            baseline_loading_min=20.0,
            baseline_unloading_min=20.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )
    state.active_loading_count = 3
    state.active_unloading_count = 2
    state.queue_depth = 4
    state.congestion_factor = 1.45
    state.operating_state = WarehouseOperatingState.CONGESTED
    return state


def test_warehouse_operations_row_matches_schema() -> None:
    telemetry = make_warehouse_telemetry_row(
        warehouse=make_warehouse(),
        temperature_c=22.0,
        humidity_pct=50.0,
    )
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    row = warehouse_operations_to_row(
        sample_time=now,
        row=telemetry,
        run_id=10,
    )

    assert len(row) == len(WAREHOUSE_OPERATION_COLUMNS)
    assert row[0] == now
    assert row[1] == 1
    assert row[2] == 3
    assert row[3] == 2
    assert row[4] == 4
    assert row[5] == 1.45
    assert row[6] == "CONGESTED"
    assert row[7] == 10
