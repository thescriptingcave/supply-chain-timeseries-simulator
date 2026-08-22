from pathlib import Path


def test_true_live_weather_reuses_v3_weather_primitives() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    for token in (
        "weather_disruption(",
        "apply_weather_disruption(",
        "clear_weather_disruption(",
        "WEATHER PLANNED",
        "HEAVY_RAIN",
    ):
        assert token in text


def test_true_live_weather_still_uses_single_tick_runtime() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "tick_concurrent_shipment(" in text
    assert "run_disruption_aware_fleet(" not in text
    assert "run_concurrent_fleet(" not in text


def test_true_live_weather_eta_is_causally_attributed() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "weather_cause" in text
    assert "eta_cause_code = traffic_cause or weather_cause" in text


def test_true_live_weather_factor_is_cleared_after_tick() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "clear_live_weather_after_tick(" in text
    assert "clear_weather_disruption(" in text


def test_true_live_weather_log_exposes_state() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "weather={'ON' if applied_weather is not None else 'OFF'}" in text
