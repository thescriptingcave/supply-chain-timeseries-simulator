"""Shared warehouse contention for Supply Chain Generator v3.

This layer models finite loading/unloading capacity, queueing, operating-state
changes, and operational telemetry derived from shared warehouse state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import (
    Shipment,
    VehicleState,
    WarehouseOperatingState,
    WarehouseState,
)
from .warehouse_telemetry import (
    WarehouseTelemetryRow,
    make_warehouse_telemetry_row,
)
from .warehouses import update_warehouse_state


@dataclass(slots=True)
class WarehouseOperation:
    shipment: Shipment
    vehicle: VehicleState
    warehouse: WarehouseState
    operation_type: str
    requested_at: datetime
    duration_minutes: float
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def waiting(self) -> bool:
        return self.started_at is None and self.completed_at is None

    @property
    def active(self) -> bool:
        return self.started_at is not None and self.completed_at is None

    @property
    def complete(self) -> bool:
        return self.completed_at is not None


@dataclass(slots=True, frozen=True)
class TimedWarehouseOperationSample:
    time: datetime
    row: WarehouseTelemetryRow


@dataclass(slots=True)
class WarehouseContentionResult:
    operations: list[WarehouseOperation] = field(default_factory=list)
    telemetry_samples: list[TimedWarehouseOperationSample] = field(default_factory=list)


def _capacity_for(
    warehouse: WarehouseState,
    operation_type: str,
) -> int:
    if operation_type == "LOADING":
        return warehouse.profile.loading_capacity
    if operation_type == "UNLOADING":
        return warehouse.profile.unloading_capacity
    raise ValueError("operation_type must be LOADING or UNLOADING")


def _active_count_for(
    warehouse: WarehouseState,
    operation_type: str,
) -> int:
    if operation_type == "LOADING":
        return warehouse.active_loading_count
    if operation_type == "UNLOADING":
        return warehouse.active_unloading_count
    raise ValueError("operation_type must be LOADING or UNLOADING")


def _increment_active(
    warehouse: WarehouseState,
    operation_type: str,
) -> None:
    if operation_type == "LOADING":
        warehouse.active_loading_count += 1
    elif operation_type == "UNLOADING":
        warehouse.active_unloading_count += 1
    else:
        raise ValueError("operation_type must be LOADING or UNLOADING")


def _decrement_active(
    warehouse: WarehouseState,
    operation_type: str,
) -> None:
    if operation_type == "LOADING":
        warehouse.active_loading_count -= 1
    elif operation_type == "UNLOADING":
        warehouse.active_unloading_count -= 1
    else:
        raise ValueError("operation_type must be LOADING or UNLOADING")


def request_operation(
    *,
    shipment: Shipment,
    vehicle: VehicleState,
    warehouse: WarehouseState,
    operation_type: str,
    requested_at: datetime,
    duration_minutes: float,
) -> WarehouseOperation:
    """Create a warehouse operation request."""
    if duration_minutes < 0:
        raise ValueError("duration_minutes cannot be negative")

    _capacity_for(warehouse, operation_type)

    return WarehouseOperation(
        shipment=shipment,
        vehicle=vehicle,
        warehouse=warehouse,
        operation_type=operation_type,
        requested_at=requested_at,
        duration_minutes=duration_minutes,
    )


def try_start_operation(
    operation: WarehouseOperation,
    *,
    now: datetime,
) -> bool:
    """Start an operation when capacity is available."""
    if operation.complete:
        return False
    if operation.active:
        return True
    if now < operation.requested_at:
        return False

    warehouse = operation.warehouse
    capacity = _capacity_for(warehouse, operation.operation_type)
    active = _active_count_for(warehouse, operation.operation_type)

    if active >= capacity:
        return False

    operation.started_at = now
    _increment_active(warehouse, operation.operation_type)
    update_warehouse_state(warehouse)
    return True


def complete_operation_if_due(
    operation: WarehouseOperation,
    *,
    now: datetime,
) -> bool:
    """Complete an active operation when its dwell duration has elapsed."""
    if not operation.active:
        return False

    due = operation.started_at + timedelta(
        minutes=operation.duration_minutes
    )
    if now < due:
        return False

    operation.completed_at = due
    _decrement_active(
        operation.warehouse,
        operation.operation_type,
    )
    update_warehouse_state(operation.warehouse)
    return True


def update_queue_depth(
    warehouse: WarehouseState,
    operations: list[WarehouseOperation],
) -> int:
    """Derive queue depth from waiting operations for this warehouse."""
    waiting = sum(
        1
        for operation in operations
        if operation.warehouse is warehouse
        and operation.waiting
    )
    warehouse.queue_depth = waiting
    update_warehouse_state(warehouse)
    return waiting


def emit_warehouse_operation_telemetry(
    *,
    now: datetime,
    warehouse: WarehouseState,
    temperature_c: float = 22.0,
    humidity_pct: float = 50.0,
) -> TimedWarehouseOperationSample:
    """Emit one operational telemetry sample from current warehouse state."""
    return TimedWarehouseOperationSample(
        time=now,
        row=make_warehouse_telemetry_row(
            warehouse=warehouse,
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
        ),
    )


def run_warehouse_contention(
    *,
    operations: list[WarehouseOperation],
    start_time: datetime,
    tick_seconds: float = 60.0,
    temperature_c: float = 22.0,
    humidity_pct: float = 50.0,
) -> WarehouseContentionResult:
    """Run a small deterministic warehouse contention simulation."""
    if tick_seconds <= 0:
        raise ValueError("tick_seconds must be positive")
    if not operations:
        raise ValueError("operations cannot be empty")

    warehouses: list[WarehouseState] = []
    seen_ids: set[int] = set()
    for operation in operations:
        wid = operation.warehouse.profile.warehouse_id
        if wid not in seen_ids:
            seen_ids.add(wid)
            warehouses.append(operation.warehouse)

    result = WarehouseContentionResult(operations=operations)
    now = start_time

    while not all(operation.complete for operation in operations):
        for warehouse in warehouses:
            update_queue_depth(warehouse, operations)

        for operation in operations:
            try_start_operation(operation, now=now)

        for warehouse in warehouses:
            update_queue_depth(warehouse, operations)
            result.telemetry_samples.append(
                emit_warehouse_operation_telemetry(
                    now=now,
                    warehouse=warehouse,
                    temperature_c=temperature_c,
                    humidity_pct=humidity_pct,
                )
            )

        next_now = now + timedelta(seconds=tick_seconds)

        for operation in operations:
            complete_operation_if_due(
                operation,
                now=next_now,
            )

        now = next_now

        for warehouse in warehouses:
            update_queue_depth(warehouse, operations)

    return result
