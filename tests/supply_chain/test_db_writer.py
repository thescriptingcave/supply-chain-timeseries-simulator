from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from generators.supply_chain.db_writer import SupplyChainWriter
from generators.supply_chain.models import (
    Priority,
    Shipment,
    ShipmentLifecycle,
)
from generators.supply_chain.persistence import SimulationRunRecord


def make_conn():
    conn = MagicMock()
    cursor = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = cursor
    context.__exit__.return_value = False
    conn.cursor.return_value = context
    return conn, cursor


def make_run_record() -> SimulationRunRecord:
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    return SimulationRunRecord(
        generator_name="supply_chain",
        model_version="3.0.0",
        seed=42,
        simulation_start=start,
        simulation_end=start + timedelta(days=2),
        configuration_version="v3-default",
        status="STARTED",
        metadata_json={"test": True},
    )


def make_shipment(shipment_id: int) -> Shipment:
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    return Shipment(
        shipment_id=shipment_id,
        run_id=10,
        vehicle_id=1,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=start,
        scheduled_arrival=start + timedelta(hours=8),
        estimated_arrival=start + timedelta(hours=8),
        lifecycle_status=ShipmentLifecycle.IN_TRANSIT,
        actual_departure=start,
    )


def test_writer_rejects_invalid_batch_size() -> None:
    with pytest.raises(ValueError):
        SupplyChainWriter(MagicMock(), batch_size=0)


def test_allocate_shipment_id_commits_and_returns_value() -> None:
    conn, cursor = make_conn()
    cursor.fetchone.return_value = (77,)

    writer = SupplyChainWriter(conn)
    shipment_id = writer.allocate_shipment_id()

    assert shipment_id == 77
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_create_simulation_run_returns_run_id_and_commits() -> None:
    conn, cursor = make_conn()
    cursor.fetchone.return_value = (123,)

    writer = SupplyChainWriter(conn)

    run_id = writer.create_simulation_run(make_run_record())

    assert run_id == 123
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_update_simulation_run_status() -> None:
    conn, cursor = make_conn()
    cursor.rowcount = 1

    writer = SupplyChainWriter(conn)
    writer.update_simulation_run_status(123, "COMPLETED")

    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_update_missing_simulation_run_rolls_back() -> None:
    conn, cursor = make_conn()
    cursor.rowcount = 0

    writer = SupplyChainWriter(conn)

    with pytest.raises(RuntimeError):
        writer.update_simulation_run_status(123, "COMPLETED")

    conn.rollback.assert_called_once()


@patch("generators.supply_chain.db_writer.execute_values")
def test_insert_shipments_uses_bounded_batches(
    execute_values_mock,
) -> None:
    conn, _ = make_conn()
    writer = SupplyChainWriter(conn, batch_size=2)

    count = writer.insert_shipments(
        [make_shipment(1), make_shipment(2), make_shipment(3)]
    )

    assert count == 3
    assert execute_values_mock.call_count == 2
    assert conn.commit.call_count == 2


@patch("generators.supply_chain.db_writer.execute_values")
def test_insert_failure_rolls_back(
    execute_values_mock,
) -> None:
    conn, _ = make_conn()
    execute_values_mock.side_effect = RuntimeError("database error")

    writer = SupplyChainWriter(conn, batch_size=2)

    with pytest.raises(RuntimeError):
        writer.insert_shipments([make_shipment(1)])

    conn.rollback.assert_called_once()


def test_invalid_run_status_rejected_before_database_call() -> None:
    conn, _ = make_conn()
    writer = SupplyChainWriter(conn)

    with pytest.raises(ValueError):
        writer.update_simulation_run_status(1, "INVALID")

    conn.cursor.assert_not_called()
