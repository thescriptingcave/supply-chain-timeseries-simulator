from pathlib import Path


def test_live_scheduler_uses_monotonic_deadlines() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "next_shipment_mono = perf_counter()" in text
    assert "current_mono >= next_shipment_mono" in text
    assert "next_tick_mono" in text
    assert "current_mono < live.next_tick_mono" in text


def test_live_scheduler_does_not_use_wall_clock_for_due_checks() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "if now >= next_shipment_at" not in text
    assert "if now < live.next_tick_at" not in text


def test_live_streamer_keeps_utc_wall_clock_for_persisted_time() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "datetime.now(timezone.utc)" in text
    assert "now=current_wall.replace" not in text
    assert "now = current_wall.replace(microsecond=0)" in text


def test_missed_ticks_are_not_backfilled() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "live.next_tick_mono = current_mono + args.movement_interval" in text
    assert "while current_mono >= live.next_tick_mono" not in text


def test_clock_adjustments_are_diagnostic_only() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "[CLOCK ADJUSTMENT]" in text
    assert "abs(wall_gap_s - mono_gap_s) > 2.0" in text
