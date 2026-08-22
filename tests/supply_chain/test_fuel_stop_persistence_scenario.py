from pathlib import Path


def test_persisted_fuel_stop_gate_uses_single_stop_consumption_rate() -> None:
    script = Path("scripts/supply_chain_v3_fuel_stop.py").read_text()

    assert "base_consumption_pct_per_100km=2.5" in script
    assert "base_consumption_pct_per_100km=10.0" not in script
