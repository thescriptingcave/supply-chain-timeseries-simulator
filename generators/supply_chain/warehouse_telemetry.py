"""Warehouse telemetry derivation for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass

from .models import WarehouseState


@dataclass(slots=True, frozen=True)
class WarehouseTelemetryRow:
    """One warehouse environmental/operational telemetry sample."""

    warehouse_id: int
    temperature_c: float
    humidity_pct: float
    loading_bays_active: int
    unloading_bays_active: int
    queue_depth: int
    congestion_factor: float
    operating_state: str


def make_warehouse_telemetry_row(
    *,
    warehouse: WarehouseState,
    temperature_c: float,
    humidity_pct: float,
) -> WarehouseTelemetryRow:
    """Create warehouse telemetry from current persistent warehouse state."""
    if not -60.0 <= temperature_c <= 70.0:
        raise ValueError("temperature_c outside supported simulation range")

    if not 0.0 <= humidity_pct <= 100.0:
        raise ValueError("humidity_pct must be between 0 and 100")

    if warehouse.active_loading_count < 0:
        raise ValueError("active_loading_count cannot be negative")

    if warehouse.active_unloading_count < 0:
        raise ValueError("active_unloading_count cannot be negative")

    if warehouse.queue_depth < 0:
        raise ValueError("queue_depth cannot be negative")

    if warehouse.active_loading_count > warehouse.profile.loading_capacity:
        raise ValueError("active loading operations exceed warehouse capacity")

    if warehouse.active_unloading_count > warehouse.profile.unloading_capacity:
        raise ValueError("active unloading operations exceed warehouse capacity")

    return WarehouseTelemetryRow(
        warehouse_id=warehouse.profile.warehouse_id,
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        loading_bays_active=warehouse.active_loading_count,
        unloading_bays_active=warehouse.active_unloading_count,
        queue_depth=warehouse.queue_depth,
        congestion_factor=warehouse.congestion_factor,
        operating_state=warehouse.operating_state.value,
    )
