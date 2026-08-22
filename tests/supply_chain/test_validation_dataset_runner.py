from scripts.generate_supply_chain_v3_validation import (
    build_validation_categories,
)


def test_validation_categories_have_expected_total() -> None:
    categories = build_validation_categories(
        shipment_count=24,
        vehicle_count=8,
        seed=42,
        days=2,
    )

    assert len(categories) == 24
    assert categories.count("contention") == 3
    assert categories.count("traffic") > 0
    assert categories.count("weather") > 0
    assert categories.count("mechanical") > 0
    assert categories.count("reefer") > 0
    assert categories.count("fuel") > 0


def test_validation_categories_are_deterministic() -> None:
    a = build_validation_categories(
        shipment_count=24,
        vehicle_count=8,
        seed=42,
        days=2,
    )
    b = build_validation_categories(
        shipment_count=24,
        vehicle_count=8,
        seed=42,
        days=2,
    )

    assert a == b
