from generators.supply_chain.production_planner import planned_shipment_count
from generators.supply_chain.run_config import production_profile
from scripts.generate_supply_chain_v3_historical import (
    build_production_categories,
)


def test_365_day_historical_plan_has_expected_shipment_count() -> None:
    config = production_profile(days=365, seed=42)

    assert planned_shipment_count(
        vehicle_count=8,
        config=config,
    ) == 4380


def test_contention_cohort_never_exceeds_fleet_size() -> None:
    categories = build_production_categories(
        shipment_count=4380,
        vehicle_count=8,
        seed=42,
        days=365,
    )

    assert categories.count("contention") <= 8
    assert categories.count("contention") > 0


def test_365_day_historical_categories_cover_full_plan() -> None:
    categories = build_production_categories(
        shipment_count=4380,
        vehicle_count=8,
        seed=42,
        days=365,
    )

    assert len(categories) == 4380

    for category in (
        "contention",
        "traffic",
        "weather",
        "mechanical",
        "reefer",
        "fuel",
        "normal",
    ):
        assert categories.count(category) > 0
