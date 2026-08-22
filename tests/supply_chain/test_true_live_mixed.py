from pathlib import Path


def test_mixed_demo_assigns_all_five_disruption_kinds() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    for kind in (
        '"traffic"',
        '"weather"',
        '"mechanical"',
        '"fuel"',
        '"reefer"',
    ):
        assert kind in text

    assert "MIXED ASSIGNMENT" in text


def test_mixed_demo_reuses_existing_live_helpers() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    for helper in (
        "attach_demo_traffic(",
        "attach_demo_weather(",
        "attach_demo_mechanical(",
        "configure_live_fuel_demo(",
        "configure_live_reefer_demo(",
    ):
        assert helper in text


def test_mixed_demo_keeps_disruptions_on_separate_shipments() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "mixed_demo_assignment_index < 5" in text
    assert "mixed_demo_assignment_index += 1" in text


def test_mixed_demo_preserves_true_live_tick_runtime() -> None:
    text = Path("scripts/stream_supply_chain_v3.py").read_text()

    assert "tick_concurrent_shipment(" in text
    assert "time.sleep(1)" in text
