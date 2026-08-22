from pathlib import Path

from generators.supply_chain.concurrent import tick_concurrent_shipment


def test_tick_api_accepts_optional_eta_cause_code() -> None:
    # Contract test: the live disruption wrapper must be able to attribute
    # ETA movement without creating a separate simulation loop.
    assert "eta_cause_code" in tick_concurrent_shipment.__annotations__


def test_live_traffic_reuses_v3_disruption_primitives() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    for token in (
        "traffic_disruption(",
        "apply_traffic_disruption(",
        "clear_traffic_disruption(",
        "make_disruption_event(",
        "TRAFFIC PLANNED",
    ):
        assert token in text


def test_live_traffic_still_uses_one_tick_api() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "tick_concurrent_shipment(" in text
    assert "run_disruption_aware_fleet(" not in text
    assert "run_concurrent_fleet(" not in text


def test_live_traffic_eta_is_causally_attributed() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "eta_cause_code=eta_cause_code" in text
    assert "disruption.cause_code" in text


def test_live_traffic_factor_is_cleared_after_each_tick() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "clear_live_traffic_after_tick(" in text
    assert "clear_traffic_disruption(" in text
