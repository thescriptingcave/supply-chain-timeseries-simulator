from pathlib import Path


def test_reefer_persistence_runner_exists() -> None:
    path = Path("scripts/supply_chain_v3_reefer_exception.py")
    assert path.exists()
    text = path.read_text()
    assert "REEFER_TEMP_EXCURSION" in text
    assert "excursion_temp_c=12.0" in text
