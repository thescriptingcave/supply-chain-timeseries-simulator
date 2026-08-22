from pathlib import Path


def test_live_streamer_reports_clock_adjustments() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "[CLOCK ADJUSTMENT]" in text
    assert "monotonic_gap=" in text
    assert "wall_gap=" in text


def test_clock_adjustment_detection_uses_monotonic_clock() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "previous_loop_mono = perf_counter()" in text
    assert "current_mono = perf_counter()" in text
    assert "mono_gap_s = current_mono - previous_loop_mono" in text
    assert "abs(wall_gap_s - mono_gap_s) > 2.0" in text
