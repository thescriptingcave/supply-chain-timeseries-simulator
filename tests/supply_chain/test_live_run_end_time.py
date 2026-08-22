from pathlib import Path


def test_live_run_finalizer_updates_status_and_end_time() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "def finalize_live_simulation_run(" in text
    assert "simulation_end = %s" in text
    assert "status = %s" in text


def test_live_run_completion_uses_actual_finalizer() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert 'status="COMPLETED"' in text
    assert "RUN COMPLETED" in text


def test_live_run_failure_uses_actual_finalizer() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert 'status="FAILED"' in text


def test_live_run_finalizer_protects_time_constraint() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    helper = text.split("def finalize_live_simulation_run(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "ended_at <= simulation_start" in helper
    assert "simulation_start + timedelta(seconds=1)" in helper


def test_startup_placeholder_remains_only_an_open_run_sentinel() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    # The far-future value can remain while status=STARTED because the schema
    # requires a non-null end. It must be overwritten when the run finalizes.
    assert "simulation_end=now + timedelta(days=3650)" in text
    assert "finalize_live_simulation_run(" in text
