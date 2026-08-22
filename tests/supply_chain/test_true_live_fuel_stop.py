from pathlib import Path


def test_true_live_fuel_demo_is_threshold_driven() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "fuel_level_pct <= live.fuel_trigger_pct" in text
    assert "FUEL STOP PENDING" in text


def test_true_live_refuel_uses_vehicle_domain_function() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "refuel(" in text
    assert "target_fuel_pct=live.fuel_refuel_to_pct" in text


def test_fuel_stop_is_stationary_and_does_not_move_odometer() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    function = text.split("def tick_live_fuel_stop(", 1)[1].split(
        "\ndef ", 1
    )[0]

    assert "vehicle.speed_kmh = 0.0" in function
    assert "movement_tick(" not in function
    assert "odometer_km =" not in function
    assert "at_fuel_stop=True" in function


def test_fuel_stop_events_are_causal_and_named() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert '"FUEL_STOP_STARTED"' in text
    assert '"FUEL_STOP_ENDED"' in text
    assert '"LOW_FUEL_REFUEL"' in text
    assert "cause_code=\"LOW_FUEL_REFUEL\"" in text


def test_fuel_rises_once_at_stop_start() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    function = text.split("def begin_live_fuel_stop(", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert function.count("refuel(") == 1
