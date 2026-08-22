from pathlib import Path


def test_live_tick_api_exists_and_does_not_advance_context() -> None:
    text = Path("generators/supply_chain/concurrent.py").read_text()
    start = text.index("def tick_concurrent_shipment(")
    end = text.index("def run_concurrent_fleet(", start)
    body = text[start:end]
    assert "time=now" in body
    assert "context.advance" not in body
    assert "while " not in body
    assert "item.arrived = True" in body
