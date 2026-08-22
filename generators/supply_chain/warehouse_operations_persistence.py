"""Warehouse operational persistence mapping for Supply Chain Generator v3."""

from __future__ import annotations

from datetime import datetime

from .warehouse_telemetry import WarehouseTelemetryRow


WAREHOUSE_OPERATION_COLUMNS = (
    "time",
    "warehouse_id",
    "loading_bays_active",
    "unloading_bays_active",
    "queue_depth",
    "congestion_factor",
    "operating_state",
    "run_id",
)


def warehouse_operations_to_row(
    *,
    sample_time: datetime,
    row: WarehouseTelemetryRow,
    run_id: int | None,
) -> tuple:
    """Map WarehouseTelemetryRow to sc_warehouse_operations."""
    return (
        sample_time,
        row.warehouse_id,
        row.loading_bays_active,
        row.unloading_bays_active,
        row.queue_depth,
        row.congestion_factor,
        row.operating_state,
        run_id,
    )
