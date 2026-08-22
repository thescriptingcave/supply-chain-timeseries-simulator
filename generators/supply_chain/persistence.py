"""PostgreSQL/TimescaleDB persistence adapters for Supply Chain Generator v3."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .models import OperationalEvent, Shipment
from .telemetry import FleetTelemetryRow


@dataclass(slots=True, frozen=True)
class SimulationRunRecord:
    generator_name: str
    model_version: str
    seed: int
    simulation_start: datetime
    simulation_end: datetime
    configuration_version: str | None
    status: str
    metadata_json: dict | None = None


SHIPMENT_COLUMNS = (
    "shipment_id",
    "vehicle_id",
    "origin_wh_id",
    "dest_wh_id",
    "cargo_type",
    "scheduled_departure",
    "scheduled_arrival",
    "actual_departure",
    "actual_arrival",
    "lifecycle_status",
    "priority",
    "run_id",
    "route_id",
    "estimated_arrival",
    "delivery_completed_at",
)

FLEET_TELEMETRY_COLUMNS = (
    "time",
    "vehicle_id",
    "shipment_id",
    "lat",
    "lon",
    "speed_kmh",
    "heading_deg",
    "altitude_m",
    "engine_rpm",
    "fuel_level_pct",
    "coolant_temp_c",
    "cargo_temp_c",
    "cargo_humidity_pct",
    "door_open",
    "harsh_braking",
    "harsh_acceleration",
    "idle_time_sec",
    "odometer_km",
    "geofence_zone",
    "run_id",
)

EVENT_COLUMNS = (
    "time",
    "event_id",
    "shipment_id",
    "event_type",
    "location_lat",
    "location_lon",
    "warehouse_id",
    "detail_json",
    "severity",
    "vehicle_id",
    "route_id",
    "run_id",
    "cause_code",
)

SIMULATION_RUN_COLUMNS = (
    "generator_name",
    "model_version",
    "seed",
    "simulation_start",
    "simulation_end",
    "configuration_version",
    "status",
    "metadata_json",
)


def shipment_to_row(shipment: Shipment) -> tuple:
    """Map Shipment domain state to the current sc_shipments schema."""
    shipment.validate_temporal_integrity()

    return (
        shipment.shipment_id,
        shipment.vehicle_id,
        shipment.origin_wh_id,
        shipment.dest_wh_id,
        shipment.cargo_type,
        shipment.scheduled_departure,
        shipment.scheduled_arrival,
        shipment.actual_departure,
        shipment.actual_arrival,
        shipment.lifecycle_status.value,
        shipment.priority.value,
        shipment.run_id,
        shipment.route_id,
        shipment.estimated_arrival,
        shipment.delivery_completed_at,
    )


def fleet_telemetry_to_row(
    *,
    sample_time: datetime,
    row: FleetTelemetryRow,
    run_id: int | None,
    altitude_m: float | None = None,
    coolant_temp_c: float | None = None,
) -> tuple:
    """Map FleetTelemetryRow to the current sc_fleet_telemetry schema."""
    return (
        sample_time,
        row.vehicle_id,
        row.shipment_id,
        row.lat,
        row.lon,
        row.speed_kmh,
        row.heading_deg,
        altitude_m,
        row.engine_rpm,
        row.fuel_level_pct,
        coolant_temp_c,
        row.cargo_temp_c,
        row.cargo_humidity_pct,
        row.door_open,
        row.harsh_braking,
        row.harsh_acceleration,
        row.idle_time_sec,
        row.odometer_km,
        row.geofence_zone,
        run_id,
    )


def event_to_row(event: OperationalEvent) -> tuple:
    """Map OperationalEvent to the current sc_events schema."""
    return (
        event.time,
        event.event_id,
        event.shipment_id,
        event.event_type,
        event.location_lat,
        event.location_lon,
        event.warehouse_id,
        json.dumps(event.detail),
        event.severity,
        event.vehicle_id,
        event.route_id,
        event.run_id,
        event.cause_code,
    )


def simulation_run_to_row(record: SimulationRunRecord) -> tuple:
    """Map SimulationRunRecord to sc_simulation_runs insert values."""
    if record.simulation_end <= record.simulation_start:
        raise ValueError("simulation_end must be after simulation_start")

    if record.status not in {
        "STARTED",
        "COMPLETED",
        "FAILED",
        "VALIDATION_FAILED",
    }:
        raise ValueError("invalid simulation run status")

    return (
        record.generator_name,
        record.model_version,
        record.seed,
        record.simulation_start,
        record.simulation_end,
        record.configuration_version,
        record.status,
        json.dumps(record.metadata_json) if record.metadata_json is not None else None,
    )


def insert_sql(table: str, columns: tuple[str, ...]) -> str:
    """Build explicit-column INSERT SQL for execute_values."""
    if not table:
        raise ValueError("table is required")
    if not columns:
        raise ValueError("columns are required")

    column_sql = ", ".join(columns)
    return f"INSERT INTO {table} ({column_sql}) VALUES %s"


def iter_batches(
    rows: Iterable[tuple],
    *,
    batch_size: int,
) -> Iterable[list[tuple]]:
    """Yield bounded-memory batches from any row iterable."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    batch: list[tuple] = []

    for row in rows:
        batch.append(row)

        if len(batch) >= batch_size:
            yield batch
            batch = []

    if batch:
        yield batch
