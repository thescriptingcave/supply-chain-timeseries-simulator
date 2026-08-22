from pathlib import Path


def test_production_runner_exists() -> None:
    path = Path("scripts/generate_supply_chain_v3.py")
    assert path.exists()

    text = path.read_text()

    assert "--days" in text
    assert "Production planning gate passed" in text
    assert "No rows were written" in text
