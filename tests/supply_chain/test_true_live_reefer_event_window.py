from pathlib import Path


def test_reefer_end_event_reuses_original_excursion_window() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "reefer_started_at: datetime | None = None" in text
    assert "live.reefer_started_at = now" in text
    assert "start_time=live.reefer_started_at or now" in text


def test_reefer_event_does_not_restart_window_at_recovery() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    helper = text.split("def _make_reefer_event(", 1)[1].split(
        "\ndef ", 1
    )[0]

    assert "start_time=now" not in helper
    assert "duration_minutes=live.reefer_duration_seconds / 60.0" in helper
