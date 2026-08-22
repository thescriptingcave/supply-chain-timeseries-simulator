import pytest

from generators.supply_chain.config import DEFAULT_CONFIG
from generators.supply_chain.models import (
    CargoProfile,
    WarehouseOperatingState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.warehouses import (
    calculate_loading_dwell,
    calculate_operating_state,
    calculate_unloading_dwell,
    can_handle_cargo,
    update_warehouse_state,
)


def make_warehouse(
    *,
    loading_capacity: int = 6,
    unloading_capacity: int = 6,
    loading_minutes: float = 20.0,
    unloading_minutes: float = 18.0,
    sensitivity: float = 1.0,
    cold_storage: bool = True,
) -> WarehouseState:
    profile = WarehouseProfile(
        warehouse_id=1,
        warehouse_name="Test Warehouse",
        lat=0.0,
        lon=0.0,
        timezone="UTC",
        loading_capacity=loading_capacity,
        unloading_capacity=unloading_capacity,
        baseline_loading_min=loading_minutes,
        baseline_unloading_min=unloading_minutes,
        congestion_sensitivity=sensitivity,
        cold_storage_capable=cold_storage,
    )
    return WarehouseState(profile=profile)


def make_cargo(
    *,
    requires_reefer: bool = False,
    loading_factor: float = 1.0,
) -> CargoProfile:
    return CargoProfile(
        cargo_type="TEST",
        requires_reefer=requires_reefer,
        target_temp_c=None,
        min_temp_c=None,
        max_temp_c=None,
        target_humidity_pct=None,
        handling_sensitivity=1.0,
        loading_time_factor=loading_factor,
    )


def test_operating_state_thresholds() -> None:
    assert calculate_operating_state(
        active_operations=5,
        capacity=10,
    ) == WarehouseOperatingState.NORMAL

    assert calculate_operating_state(
        active_operations=6,
        capacity=10,
    ) == WarehouseOperatingState.BUSY

    assert calculate_operating_state(
        active_operations=9,
        capacity=10,
    ) == WarehouseOperatingState.CONGESTED


def test_update_state_uses_workload() -> None:
    warehouse = make_warehouse(loading_capacity=5, unloading_capacity=5)
    warehouse.active_loading_count = 4
    warehouse.active_unloading_count = 3
    warehouse.queue_depth = 2

    state = update_warehouse_state(warehouse)

    assert state == WarehouseOperatingState.CONGESTED
    assert warehouse.congestion_factor > 1.0


def test_congestion_increases_loading_dwell() -> None:
    normal = make_warehouse()
    congested = make_warehouse()
    congested.operating_state = WarehouseOperatingState.CONGESTED

    cargo = make_cargo()

    normal_result = calculate_loading_dwell(
        warehouse_state=normal,
        cargo_profile=cargo,
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )
    congested_result = calculate_loading_dwell(
        warehouse_state=congested,
        cargo_profile=cargo,
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )

    assert congested_result.total_minutes > normal_result.total_minutes


def test_cargo_handling_factor_increases_dwell() -> None:
    warehouse = make_warehouse()
    ordinary = make_cargo(loading_factor=1.0)
    sensitive = make_cargo(loading_factor=1.3)

    ordinary_result = calculate_loading_dwell(
        warehouse_state=warehouse,
        cargo_profile=ordinary,
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )
    sensitive_result = calculate_loading_dwell(
        warehouse_state=warehouse,
        cargo_profile=sensitive,
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )

    assert sensitive_result.total_minutes > ordinary_result.total_minutes


def test_critical_priority_reduces_controllable_dwell() -> None:
    warehouse = make_warehouse()
    cargo = make_cargo()

    standard = calculate_loading_dwell(
        warehouse_state=warehouse,
        cargo_profile=cargo,
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )
    critical = calculate_loading_dwell(
        warehouse_state=warehouse,
        cargo_profile=cargo,
        priority_rule=DEFAULT_CONFIG.critical_priority,
    )

    assert critical.total_minutes < standard.total_minutes


def test_unloading_uses_unloading_baseline() -> None:
    warehouse = make_warehouse(
        loading_minutes=30.0,
        unloading_minutes=15.0,
    )
    cargo = make_cargo()

    loading = calculate_loading_dwell(
        warehouse_state=warehouse,
        cargo_profile=cargo,
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )
    unloading = calculate_unloading_dwell(
        warehouse_state=warehouse,
        cargo_profile=cargo,
        priority_rule=DEFAULT_CONFIG.standard_priority,
    )

    assert unloading.total_minutes < loading.total_minutes


def test_reefer_cargo_requires_cold_storage() -> None:
    reefer_cargo = make_cargo(requires_reefer=True)

    cold = make_warehouse(cold_storage=True)
    dry = make_warehouse(cold_storage=False)

    assert can_handle_cargo(
        warehouse_state=cold,
        cargo_profile=reefer_cargo,
    )
    assert not can_handle_cargo(
        warehouse_state=dry,
        cargo_profile=reefer_cargo,
    )


def test_general_cargo_does_not_require_cold_storage() -> None:
    dry = make_warehouse(cold_storage=False)

    assert can_handle_cargo(
        warehouse_state=dry,
        cargo_profile=make_cargo(requires_reefer=False),
    )


def test_invalid_capacity_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_operating_state(
            active_operations=1,
            capacity=0,
        )
