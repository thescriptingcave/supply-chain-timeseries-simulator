from dataclasses import replace

from generators.supply_chain.models import (
    WarehouseProfile,
    WarehouseState,
)
from scripts.supply_chain_v3_concurrent_contention import (
    constrained_runtime_warehouse,
)


def test_runtime_capacity_override_does_not_mutate_reference_profile() -> None:
    original = WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=1,
            warehouse_name="W1",
            lat=0.0,
            lon=0.0,
            timezone="UTC",
            loading_capacity=5,
            unloading_capacity=4,
            baseline_loading_min=20.0,
            baseline_unloading_min=18.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )

    constrained = constrained_runtime_warehouse(
        original,
        loading_capacity=1,
        unloading_capacity=1,
    )

    assert original.profile.loading_capacity == 5
    assert original.profile.unloading_capacity == 4
    assert constrained.profile.loading_capacity == 1
    assert constrained.profile.unloading_capacity == 1
