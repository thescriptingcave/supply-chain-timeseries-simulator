from pathlib import Path


def test_true_live_streamer_uses_single_tick_api() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "tick_concurrent_shipment(" in text
    assert "run_concurrent_fleet(" not in text
    assert "run_disruption_aware_fleet(" not in text
    assert "execute_live_normal_shipment(" not in text


def test_true_live_streamer_schedules_tick_from_monotonic_clock() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "next_tick_mono" in text
    assert "current_mono < live.next_tick_mono" in text
    assert "live.next_tick_mono = current_mono + args.movement_interval" in text


def test_true_live_streamer_requires_one_sample_per_tick() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "len(new_samples) != 1" in text
    assert "live tick must emit exactly one telemetry sample" in text


def test_true_live_streamer_does_not_create_future_sample_batches() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "TRUE LIVE mode started" in text
    assert "telemetry_rows=" not in text
