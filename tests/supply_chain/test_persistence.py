from datetime import datetime, timedelta, timezone

import json
import pytest

from generators.supply_chain.models import (
    OperationalEvent,
    Priority,
    Shipment,
    ShipmentLifecycle,
)
from generators.supply_chain.persistence import (
    EVENT_COLUMNS,
    FLEET_TELEMETRY_COLUMNS,
    SHIPMENT_COLUMNS,
    SIMULATION_RUN_COLUMNS,
    SimulationRunRecord,
    event_to_row,
    fleet_telemetry_to_row,
    insert_sql,
    iter_batches,
    shipment_to_row,
    simulation_run_to_row,
)
from generators.supply_chain.telemetry import FleetTelemetryRow


def make_shipment() -> Shipment:
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    return Shipment(
        shipment_id=1,
        run_id=10,
        vehicle_id=2,
        route_id=3,
        origin_wh_id=1,
        dest_wh_id=4,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=start,
        scheduled_arrival=start + timedelta(hours=8),
        estimated_arrival=start + timedelta(hours=8, minutes=10),
        lifecycle_status=ShipmentLifecycle.IN_TRANSIT,
        actual_departure=start + timedelta(minutes=20),
    )


def test_shipment_row_matches_database_column_count() -> None:
    row = shipment_to_row(make_shipment())

    assert len(row) == len(SHIPMENT_COLUMNS)
    assert row[9] == "IN_TRANSIT"
    assert row[10] == "STANDARD"


def test_fleet_telemetry_row_matches_database_column_count() -> None:
    sample = FleetTelemetryRow(
        vehicle_id=1,
        shipment_id=2,
        lat=10.0,
        lon=20.0,
        speed_kmh=80.0,
        heading_deg=90.0,
        engine_rpm=2200,
        fuel_level_pct=70.0,
        cargo_temp_c=None,
        cargo_humidity_pct=None,
        door_open=False,
        harsh_braking=False,
        harsh_acceleration=False,
        idle_time_sec=0,
        odometer_km=1000.0,
        geofence_zone="HIGHWAY",
    )
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    row = fleet_telemetry_to_row(
        sample_time=now,
        row=sample,
        run_id=99,
    )

    assert len(row) == len(FLEET_TELEMETRY_COLUMNS)
    assert row[0] == now
    assert row[-1] == 99


def test_event_row_matches_database_column_count() -> None:
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    event = OperationalEvent(
        event_id="EVT-1",
        time=now,
        event_type="ETA_UPDATED",
        shipment_id=1,
        vehicle_id=2,
        route_id=3,
        run_id=4,
        severity="INFO",
        cause_code="TRAFFIC_CONGESTION",
        detail={"delta_minutes": 12.5},
    )

    row = event_to_row(event)

    assert len(row) == len(EVENT_COLUMNS)
    assert json.loads(row[7])["delta_minutes"] == pytest.approx(12.5)


def test_simulation_run_row_matches_database_column_count() -> None:
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    record = SimulationRunRecord(
        generator_name="supply_chain",
        model_version="3.0.0",
        seed=42,
        simulation_start=start,
        simulation_end=start + timedelta(days=2),
        configuration_version="v3-default",
        status="STARTED",
        metadata_json={"test": True},
    )

    row = simulation_run_to_row(record)

    assert len(row) == len(SIMULATION_RUN_COLUMNS)
    assert row[0] == "supply_chain"
    assert row[2] == 42


def test_insert_sql_uses_explicit_columns() -> None:
    sql = insert_sql("sc_shipments", SHIPMENT_COLUMNS)

    assert sql.startswith("INSERT INTO sc_shipments (")
    assert "shipment_id" in sql
    assert sql.endswith("VALUES %s")


def test_batching_is_bounded_and_preserves_rows() -> None:
    rows = [(i,) for i in range(7)]

    batches = list(iter_batches(rows, batch_size=3))

    assert [len(batch) for batch in batches] == [3, 3, 1]
    assert [row for batch in batches for row in batch] == rows


def test_batching_rejects_invalid_size() -> None:
    with pytest.raises(ValueError):
        list(iter_batches([(1,)], batch_size=0))


def test_invalid_simulation_run_status_rejected() -> None:
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        simulation_run_to_row(
            SimulationRunRecord(
                generator_name="supply_chain",
                model_version="3.0.0",
                seed=42,
                simulation_start=start,
                simulation_end=start + timedelta(days=1),
                configuration_version=None,
                status="BOGUS",
            )
        )
