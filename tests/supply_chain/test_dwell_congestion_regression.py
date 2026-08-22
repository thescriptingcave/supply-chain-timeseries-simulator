from generators.supply_chain.config import DEFAULT_CONFIG
from generators.supply_chain.models import (
    CargoProfile,
    WarehouseOperatingState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.warehouses import calculate_loading_dwell


def make_warehouse() -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=1,
            warehouse_name="W1",
            lat=0.0,
            lon=0.0,
            timezone="UTC",
            loading_capacity=5,
            unloading_capacity=5,
            baseline_loading_min=20.0,
            baseline_unloading_min=20.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )


def cargo() -> CargoProfile:
    return CargoProfile(
        cargo_type="GENERAL_FREIGHT",
        requires_reefer=False,
        target_temp_c=None,
        min_temp_c=None,
        max_temp_c=None,
        target_humidity_pct=None,
        handling_sensitivity=1.0,
        loading_time_factor=1.0,
    )


def test_congested_state_affects_dwell_even_if_stored_factor_is_stale() -> None:
    normal = make_warehouse()
    congested = make_warehouse()

    # Reproduces the legacy/unit-test setup: state changes, but the cached
    # congestion_factor has not been refreshed yet.
    congested.operating_state = WarehouseOperatingState.CONGESTED
    assert congested.congestion_factor == 1.0

    normal_result = calculate_loading_dwell(
        warehouse_state=normal,
        cargo_profile=cargo(),
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )
    congested_result = calculate_loading_dwell(
        warehouse_state=congested,
        cargo_profile=cargo(),
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )

    assert congested_result.congestion_factor > 1.0
    assert congested_result.total_minutes > normal_result.total_minutes


def test_resource_pool_multiplier_is_not_reduced_by_fallback_logic() -> None:
    warehouse = make_warehouse()
    warehouse.operating_state = WarehouseOperatingState.CONGESTED
    warehouse.congestion_factor = 1.80

    result = calculate_loading_dwell(
        warehouse_state=warehouse,
        cargo_profile=cargo(),
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )

    assert result.congestion_factor == 1.80
