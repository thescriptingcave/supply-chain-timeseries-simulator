from pathlib import Path


def test_reefer_temperature_is_not_stored_on_vehicle_state() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "vehicle.cargo_temp_c" not in text
    assert "current_cargo_temp_c" in text


def test_live_tick_accepts_cargo_temperature_for_telemetry() -> None:
    text = Path("generators/supply_chain/concurrent.py").read_text()

    assert "cargo_temp_c: float | None = None" in text
    assert "cargo_temp_c=cargo_temp_c" in text


def test_true_live_reefer_changes_temperature_not_speed() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "REEFER_TEMP_EXCURSION" in text
    assert "live.current_cargo_temp_c = live.reefer_excursion_temp_c" in text
    assert "tick_concurrent_shipment(" in text


def test_true_live_reefer_has_start_and_end_events() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert '"CARGO_EXCEPTION_STARTED"' in text
    assert '"CARGO_EXCEPTION_ENDED"' in text


def test_true_live_reefer_recovers_temperature() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "live.current_cargo_temp_c = live.reefer_recovery_temp_c" in text


def test_true_live_reefer_does_not_pause_movement() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    function = text.split("def apply_live_reefer_state(", 1)[1].split(
        "\ndef ", 1
    )[0]

    assert "vehicle.speed_kmh = 0.0" not in function
    assert "movement_tick(" not in function


def test_true_live_reefer_log_exposes_temperature() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "reefer={'ON' if reefer_active else 'OFF'}" in text
    assert "cargo_temp=" in text
