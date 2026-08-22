from datetime import datetime, timedelta, timezone

from generators.supply_chain.persistence import (
    SimulationRunRecord,
    simulation_run_to_row,
)


def test_live_run_record_uses_valid_open_ended_horizon() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    record = SimulationRunRecord(
        generator_name="supply_chain_live",
        model_version="3.0.0",
        seed=42,
        simulation_start=start,
        simulation_end=start + timedelta(days=3650),
        configuration_version="v3-live",
        status="STARTED",
        metadata_json={"open_ended_live_run": True},
    )

    assert simulation_run_to_row(record) is not None
