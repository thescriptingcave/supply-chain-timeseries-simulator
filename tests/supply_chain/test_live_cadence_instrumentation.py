from pathlib import Path


def test_instrumented_streamer_uses_perf_counter() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()
    assert "perf_counter" in text


def test_instrumented_streamer_reports_tick_lateness() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()
    assert "lateness_s" in text
    assert "lateness=" in text


def test_instrumented_streamer_reports_database_timings() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()
    for token in (
        "telemetry_insert_ms",
        "event_insert_ms",
        "shipment_update_ms",
        "[TIMING]",
    ):
        assert token in text


def test_instrumentation_does_not_backfill_missed_ticks() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "live.next_tick_mono = current_mono + args.movement_interval" in text
    assert "while current_mono >= live.next_tick_mono" not in text
