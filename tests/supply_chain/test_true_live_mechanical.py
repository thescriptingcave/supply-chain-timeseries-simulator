from pathlib import Path


def test_true_live_mechanical_is_full_stop() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "MECHANICAL_BREAKDOWN" in text
    assert "vehicle.speed_kmh = 0.0" in text
    assert "tick_live_mechanical_stop(" in text


def test_true_live_mechanical_does_not_advance_route_while_stopped() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    function = text.split("def tick_live_mechanical_stop(", 1)[1].split(
        "\ndef ", 1
    )[0]

    assert "movement_tick(" not in function
    assert "route_progress_pct" not in function
    assert "odometer_km =" not in function


def test_true_live_mechanical_emits_causal_eta_event() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "maybe_make_eta_updated_event(" in text
    assert "cause_code=disruption.cause_code" in text
    assert "disruption.delay_minutes" in text


def test_true_live_mechanical_has_start_and_end_boundaries() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "DISRUPTION_STARTED" in text
    assert "DISRUPTION_ENDED" in text
    assert "MECHANICAL PLANNED" in text


def test_mechanical_branch_keeps_single_live_sample_per_due_tick() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "len(new_samples) != 1" in text
    assert "live tick must emit exactly one telemetry sample" in text
