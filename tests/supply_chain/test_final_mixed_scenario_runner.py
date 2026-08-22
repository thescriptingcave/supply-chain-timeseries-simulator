from pathlib import Path


def test_final_mixed_scenario_runner_exists_and_names_all_capabilities() -> None:
    path = Path("scripts/supply_chain_v3_mixed_scenario.py")
    assert path.exists()

    text = path.read_text()

    for token in (
        "warehouse_contention",
        "TRAFFIC_CONGESTION",
        "HEAVY_RAIN",
        "MECHANICAL_BREAKDOWN",
        "LOW_FUEL_REFUEL",
        "REEFER_TEMP_EXCURSION",
    ):
        assert token in text
