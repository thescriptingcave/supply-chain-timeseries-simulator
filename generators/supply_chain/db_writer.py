"""PostgreSQL/TimescaleDB writer for Supply Chain Generator v3."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from psycopg2.extras import execute_values

from .persistence import (
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
from .warehouse_operations_persistence import (
    WAREHOUSE_OPERATION_COLUMNS,
    warehouse_operations_to_row,
)


class SupplyChainWriter:
    """Bounded-batch persistence for Supply Chain v3."""

    def __init__(
        self,
        conn: Any,
        *,
        batch_size: int = 5000,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        self.conn = conn
        self.batch_size = batch_size

    def allocate_shipment_id(self) -> int:
        """Reserve the next sc_shipments sequence value."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT nextval('sc_shipments_shipment_id_seq')"
            )
            result = cur.fetchone()

        if result is None:
            self.conn.rollback()
            raise RuntimeError("shipment sequence did not return an id")

        self.conn.commit()
        return int(result[0])

    def create_simulation_run(
        self,
        record: SimulationRunRecord,
    ) -> int:
        """Insert a simulation-run record and return run_id."""
        sql = f"""
            INSERT INTO sc_simulation_runs (
                {", ".join(SIMULATION_RUN_COLUMNS)}
            )
            VALUES ({", ".join(["%s"] * len(SIMULATION_RUN_COLUMNS))})
            RETURNING run_id
        """

        row = simulation_run_to_row(record)

        with self.conn.cursor() as cur:
            cur.execute(sql, row)
            result = cur.fetchone()

        if result is None:
            self.conn.rollback()
            raise RuntimeError("simulation run insert did not return run_id")

        self.conn.commit()
        return int(result[0])

    def update_simulation_run_status(
        self,
        run_id: int,
        status: str,
    ) -> None:
        """Update the lifecycle status of a simulation run."""
        if run_id <= 0:
            raise ValueError("run_id must be positive")

        if status not in {
            "STARTED",
            "COMPLETED",
            "FAILED",
            "VALIDATION_FAILED",
        }:
            raise ValueError("invalid simulation run status")

        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sc_simulation_runs
                SET status = %s
                WHERE run_id = %s
                """,
                (status, run_id),
            )

            if cur.rowcount != 1:
                self.conn.rollback()
                raise RuntimeError(
                    f"expected one simulation run row for run_id={run_id}"
                )

        self.conn.commit()

    def insert_shipments(self, shipments: Iterable) -> int:
        rows = (shipment_to_row(shipment) for shipment in shipments)
        return self._insert_batches(
            table="sc_shipments",
            columns=SHIPMENT_COLUMNS,
            rows=rows,
        )

    def insert_events(self, events: Iterable) -> int:
        rows = (event_to_row(event) for event in events)
        return self._insert_batches(
            table="sc_events",
            columns=EVENT_COLUMNS,
            rows=rows,
        )

    def insert_fleet_telemetry(
        self,
        samples: Iterable[tuple],
    ) -> int:
        """Insert `(sample_time, FleetTelemetryRow, run_id)` tuples."""
        rows = (
            fleet_telemetry_to_row(
                sample_time=sample_time,
                row=telemetry_row,
                run_id=run_id,
            )
            for sample_time, telemetry_row, run_id in samples
        )

        return self._insert_batches(
            table="sc_fleet_telemetry",
            columns=FLEET_TELEMETRY_COLUMNS,
            rows=rows,
        )

    def insert_warehouse_operations(
        self,
        samples: Iterable[tuple],
    ) -> int:
        """Insert `(sample_time, WarehouseTelemetryRow, run_id)` tuples."""
        rows = (
            warehouse_operations_to_row(
                sample_time=sample_time,
                row=telemetry_row,
                run_id=run_id,
            )
            for sample_time, telemetry_row, run_id in samples
        )

        return self._insert_batches(
            table="sc_warehouse_operations",
            columns=WAREHOUSE_OPERATION_COLUMNS,
            rows=rows,
        )

    def _insert_batches(
        self,
        *,
        table: str,
        columns: tuple[str, ...],
        rows: Iterable[tuple],
    ) -> int:
        """Insert rows in bounded batches and commit each completed batch."""
        sql = insert_sql(table, columns)
        total = 0

        try:
            with self.conn.cursor() as cur:
                for batch in iter_batches(
                    rows,
                    batch_size=self.batch_size,
                ):
                    execute_values(cur, sql, batch)
                    self.conn.commit()
                    total += len(batch)

            return total

        except Exception:
            self.conn.rollback()
            raise
