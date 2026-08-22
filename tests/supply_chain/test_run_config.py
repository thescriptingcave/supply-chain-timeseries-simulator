import random

import pytest

from generators.supply_chain.production_planner import (
    build_event_plan,
    planned_shipment_count,
)
from generators.supply_chain.run_config import SupplyChainV3RunConfig


def test_default_run_config_is_valid() -> None:
    SupplyChainV3RunConfig().validate()


def test_planned_shipment_count_scales_with_days_and_fleet() -> None:
    config = SupplyChainV3RunConfig(
        simulation_days=2,
        target_shipments_per_vehicle_per_day=1.5,
    )

    assert planned_shipment_count(
        vehicle_count=8,
        config=config,
    ) == 24


def test_event_plan_is_deterministic_for_seed() -> None:
    config = SupplyChainV3RunConfig()

    a = build_event_plan(
        rng=random.Random(42),
        config=config,
        requires_reefer=True,
    )
    b = build_event_plan(
        rng=random.Random(42),
        config=config,
        requires_reefer=True,
    )

    assert a == b


def test_non_reefer_shipment_cannot_get_reefer_excursion() -> None:
    config = SupplyChainV3RunConfig(
        reefer_excursion_probability_per_shipment=1.0,
    )

    plan = build_event_plan(
        rng=random.Random(42),
        config=config,
        requires_reefer=False,
    )

    assert not plan.reefer_excursion


def test_invalid_probability_rejected() -> None:
    with pytest.raises(ValueError):
        SupplyChainV3RunConfig(
            traffic_probability_per_shipment=1.1
        ).validate()
