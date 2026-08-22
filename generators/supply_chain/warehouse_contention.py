"""Shared warehouse contention for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import Shipment, VehicleState, WarehouseState
from .warehouse_telemetry import WarehouseTelemetryRow, make_warehouse_telemetry_row
from .warehouses import update_warehouse_state_with_queues


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


def _capacity_for(warehouse: WarehouseState, operation_type: str) -> int:
    if operation_type == "LOADING":
        return warehouse.profile.loading_capacity
    if operation_type == "UNLOADING":
        return warehouse.profile.unloading_capacity
    raise ValueError("operation_type must be LOADING or UNLOADING")


def _active_count_for(warehouse: WarehouseState, operation_type: str) -> int:
    if operation_type == "LOADING":
        return warehouse.active_loading_count
    if operation_type == "UNLOADING":
        return warehouse.active_unloading_count
    raise ValueError("operation_type must be LOADING or UNLOADING")


def _increment_active(warehouse: WarehouseState, operation_type: str) -> None:
    if operation_type == "LOADING":
        warehouse.active_loading_count += 1
    elif operation_type == "UNLOADING":
        warehouse.active_unloading_count += 1
    else:
        raise ValueError("operation_type must be LOADING or UNLOADING")


def _decrement_active(warehouse: WarehouseState, operation_type: str) -> None:
    if operation_type == "LOADING":
        warehouse.active_loading_count -= 1
    elif operation_type == "UNLOADING":
        warehouse.active_unloading_count -= 1
    else:
        raise ValueError("operation_type must be LOADING or UNLOADING")


def _waiting_by_type(
    warehouse: WarehouseState,
    operations: list[WarehouseOperation],
) -> tuple[int, int]:
    loading = sum(
        1 for op in operations
        if op.warehouse is warehouse and op.waiting and op.operation_type == "LOADING"
    )
    unloading = sum(
        1 for op in operations
        if op.warehouse is warehouse and op.waiting and op.operation_type == "UNLOADING"
    )
    return loading, unloading


def _refresh_state(
    warehouse: WarehouseState,
    operations: list[WarehouseOperation],
) -> None:
    loading_queue, unloading_queue = _waiting_by_type(warehouse, operations)
    update_warehouse_state_with_queues(
        warehouse,
        loading_queue_depth=loading_queue,
        unloading_queue_depth=unloading_queue,
    )


def request_operation(
    *,
    shipment: Shipment,
    vehicle: VehicleState,
    warehouse: WarehouseState,
    operation_type: str,
    requested_at: datetime,
    duration_minutes: float,
) -> WarehouseOperation:
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


def try_start_operation(operation: WarehouseOperation, *, now: datetime) -> bool:
    if operation.complete:
        return False
    if operation.active:
        return True
    if now < operation.requested_at:
        return False

    capacity = _capacity_for(operation.warehouse, operation.operation_type)
    active = _active_count_for(operation.warehouse, operation.operation_type)
    if active >= capacity:
        return False

    operation.started_at = now
    _increment_active(operation.warehouse, operation.operation_type)
    return True


def complete_operation_if_due(operation: WarehouseOperation, *, now: datetime) -> bool:
    if not operation.active:
        return False
    due = operation.started_at + timedelta(minutes=operation.duration_minutes)
    if now < due:
        return False
    operation.completed_at = due
    _decrement_active(operation.warehouse, operation.operation_type)
    return True


def update_queue_depth(
    warehouse: WarehouseState,
    operations: list[WarehouseOperation],
) -> int:
    _refresh_state(warehouse, operations)
    return warehouse.queue_depth


def emit_warehouse_operation_telemetry(
    *,
    now: datetime,
    warehouse: WarehouseState,
    temperature_c: float = 22.0,
    humidity_pct: float = 50.0,
) -> TimedWarehouseOperationSample:
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
    if tick_seconds <= 0:
        raise ValueError("tick_seconds must be positive")
    if not operations:
        raise ValueError("operations cannot be empty")

    warehouses: list[WarehouseState] = []
    seen: set[int] = set()
    for op in operations:
        wid = op.warehouse.profile.warehouse_id
        if wid not in seen:
            seen.add(wid)
            warehouses.append(op.warehouse)

    result = WarehouseContentionResult(operations=operations)
    now = start_time

    while not all(op.complete for op in operations):
        for warehouse in warehouses:
            _refresh_state(warehouse, operations)

        for op in operations:
            try_start_operation(op, now=now)

        for warehouse in warehouses:
            _refresh_state(warehouse, operations)
            result.telemetry_samples.append(
                emit_warehouse_operation_telemetry(
                    now=now,
                    warehouse=warehouse,
                    temperature_c=temperature_c,
                    humidity_pct=humidity_pct,
                )
            )

        next_now = now + timedelta(seconds=tick_seconds)

        for op in operations:
            complete_operation_if_due(op, now=next_now)

        now = next_now

    return result
