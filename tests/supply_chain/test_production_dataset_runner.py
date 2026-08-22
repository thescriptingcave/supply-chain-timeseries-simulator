from scripts.generate_supply_chain_v3_production import (
    build_production_categories,
)


def test_production_categories_have_expected_total() -> None:
    categories = build_production_categories(
        shipment_count=360,
        vehicle_count=8,
        seed=42,
        days=30,
    )

    assert len(categories) == 360

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


def test_production_categories_are_deterministic() -> None:
    a = build_production_categories(
        shipment_count=360,
        vehicle_count=8,
        seed=42,
        days=30,
    )
    b = build_production_categories(
        shipment_count=360,
        vehicle_count=8,
        seed=42,
        days=30,
    )

    assert a == b
