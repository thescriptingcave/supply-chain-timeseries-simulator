"""Small database smoke test for Supply Chain v3 persistence.

This script writes only one simulation-run metadata row, then marks it COMPLETED.
It does not yet generate shipments or telemetry.

Usage:
    uv run python scripts/supply_chain_v3_db_smoke.py
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg2

from generators.supply_chain.db_writer import SupplyChainWriter
from generators.supply_chain.persistence import SimulationRunRecord


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


def main() -> None:
    start = datetime.now(timezone.utc).replace(microsecond=0)
    end = start + timedelta(minutes=5)

    conn = psycopg2.connect(DB_URL)

    try:
        writer = SupplyChainWriter(conn)

        run_id = writer.create_simulation_run(
            SimulationRunRecord(
                generator_name="supply_chain",
                model_version="3.0.0",
                seed=42,
                simulation_start=start,
                simulation_end=end,
                configuration_version="v3-default",
                status="STARTED",
                metadata_json={"purpose": "database-smoke-test"},
            )
        )

        writer.update_simulation_run_status(run_id, "COMPLETED")

        print(f"[Supply Chain v3] DB smoke test passed. run_id={run_id}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
