"""Warehouse operating-state and dwell rules for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass

from .config import PriorityRule
from .models import CargoProfile, Priority, WarehouseOperatingState, WarehouseState


@dataclass(slots=True, frozen=True)
class DwellCalculation:
    base_minutes: float
    congestion_factor: float
    cargo_factor: float
    priority_factor: float
    operational_noise_minutes: float
    total_minutes: float


def calculate_operating_state(
    *,
    active_operations: int,
    capacity: int,
    queue_depth: int = 0,
) -> WarehouseOperatingState:
    """Generic workload classifier retained for existing callers/tests."""
    if capacity <= 0:
        raise ValueError("capacity must be positive")
    if active_operations < 0:
        raise ValueError("active_operations cannot be negative")
    if queue_depth < 0:
        raise ValueError("queue_depth cannot be negative")

    effective_pressure = (active_operations + queue_depth) / capacity

    if effective_pressure > 0.85:
        return WarehouseOperatingState.CONGESTED
    if queue_depth > 0 or active_operations / capacity >= 0.60:
        return WarehouseOperatingState.BUSY
    return WarehouseOperatingState.NORMAL


def calculate_resource_pool_state(
    *,
    active_loading: int,
    loading_capacity: int,
    loading_queue: int,
    active_unloading: int,
    unloading_capacity: int,
    unloading_queue: int,
) -> WarehouseOperatingState:
    """Classify from the most constrained warehouse resource pool."""
    values = (
        active_loading,
        loading_capacity,
        loading_queue,
        active_unloading,
        unloading_capacity,
        unloading_queue,
    )
    if any(value < 0 for value in values):
        raise ValueError("warehouse resource values cannot be negative")
    if loading_capacity <= 0 or unloading_capacity <= 0:
        raise ValueError("warehouse capacities must be positive")

    loading_pressure = (active_loading + loading_queue) / loading_capacity
    unloading_pressure = (active_unloading + unloading_queue) / unloading_capacity
    max_pressure = max(loading_pressure, unloading_pressure)

    if max_pressure > 1.0:
        return WarehouseOperatingState.CONGESTED
    if max_pressure >= 0.60 or loading_queue > 0 or unloading_queue > 0:
        return WarehouseOperatingState.BUSY
    return WarehouseOperatingState.NORMAL


def congestion_multiplier_from_resource_pools(
    state: WarehouseState,
    *,
    loading_queue_depth: int,
    unloading_queue_depth: int,
) -> float:
    """Derive multiplier from the most pressured loading/unloading pool."""
    sensitivity = state.profile.congestion_sensitivity
    if sensitivity <= 0:
        raise ValueError("congestion_sensitivity must be positive")

    loading_pressure = (
        state.active_loading_count + loading_queue_depth
    ) / state.profile.loading_capacity
    unloading_pressure = (
        state.active_unloading_count + unloading_queue_depth
    ) / state.profile.unloading_capacity
    max_pressure = max(loading_pressure, unloading_pressure)

    if max_pressure <= 0.60:
        base = 1.00
    elif max_pressure <= 1.00:
        base = 1.18
    else:
        base = 1.45

    excess = max(0.0, max_pressure - 1.0)
    return 1.0 + ((base - 1.0) * sensitivity) + (0.25 * excess * sensitivity)


def congestion_multiplier(state: WarehouseState) -> float:
    """Fallback multiplier for callers that only know aggregate queue depth."""
    sensitivity = state.profile.congestion_sensitivity
    if sensitivity <= 0:
        raise ValueError("congestion_sensitivity must be positive")

    total_capacity = (
        state.profile.loading_capacity + state.profile.unloading_capacity
    )
    if total_capacity <= 0:
        raise ValueError("warehouse total capacity must be positive")

    state_base = {
        WarehouseOperatingState.NORMAL: 1.00,
        WarehouseOperatingState.BUSY: 1.18,
        WarehouseOperatingState.CONGESTED: 1.45,
    }[state.operating_state]

    queue_pressure = state.queue_depth / total_capacity
    return max(
        1.0,
        1.0
        + ((state_base - 1.0) * sensitivity)
        + (queue_pressure * 0.25 * sensitivity),
    )


def update_warehouse_state_with_queues(
    state: WarehouseState,
    *,
    loading_queue_depth: int,
    unloading_queue_depth: int,
) -> WarehouseOperatingState:
    """Update state using separate loading and unloading queue pressure."""
    state.queue_depth = loading_queue_depth + unloading_queue_depth
    state.operating_state = calculate_resource_pool_state(
        active_loading=state.active_loading_count,
        loading_capacity=state.profile.loading_capacity,
        loading_queue=loading_queue_depth,
        active_unloading=state.active_unloading_count,
        unloading_capacity=state.profile.unloading_capacity,
        unloading_queue=unloading_queue_depth,
    )
    state.congestion_factor = congestion_multiplier_from_resource_pools(
        state,
        loading_queue_depth=loading_queue_depth,
        unloading_queue_depth=unloading_queue_depth,
    )
    return state.operating_state


def update_warehouse_state(state: WarehouseState) -> WarehouseOperatingState:
    """Aggregate fallback used by older callers."""
    capacity = (
        state.profile.loading_capacity + state.profile.unloading_capacity
    )
    active = state.active_loading_count + state.active_unloading_count
    state.operating_state = calculate_operating_state(
        active_operations=active,
        capacity=capacity,
        queue_depth=state.queue_depth,
    )
    state.congestion_factor = congestion_multiplier(state)
    return state.operating_state


def calculate_loading_dwell(
    *,
    warehouse_state: WarehouseState,
    cargo_profile: CargoProfile,
    priority_rule: PriorityRule,
    operational_noise_minutes: float = 0.0,
) -> DwellCalculation:
    return _calculate_dwell(
        base_minutes=warehouse_state.profile.baseline_loading_min,
        warehouse_state=warehouse_state,
        cargo_profile=cargo_profile,
        priority_rule=priority_rule,
        operational_noise_minutes=operational_noise_minutes,
    )


def calculate_unloading_dwell(
    *,
    warehouse_state: WarehouseState,
    cargo_profile: CargoProfile,
    priority_rule: PriorityRule,
    operational_noise_minutes: float = 0.0,
) -> DwellCalculation:
    return _calculate_dwell(
        base_minutes=warehouse_state.profile.baseline_unloading_min,
        warehouse_state=warehouse_state,
        cargo_profile=cargo_profile,
        priority_rule=priority_rule,
        operational_noise_minutes=operational_noise_minutes,
    )


def _calculate_dwell(
    *,
    base_minutes: float,
    warehouse_state: WarehouseState,
    cargo_profile: CargoProfile,
    priority_rule: PriorityRule,
    operational_noise_minutes: float,
) -> DwellCalculation:
    if base_minutes < 0:
        raise ValueError("base dwell minutes cannot be negative")
    if operational_noise_minutes < -base_minutes:
        raise ValueError("operational noise would make dwell negative")

    # `operating_state` is authoritative, while `congestion_factor` may be a
    # richer resource-pool value calculated by the contention engine. Use the
    # larger of the generic state-derived multiplier and the stored multiplier
    # so manually-set CONGESTED state and resource-pool pressure both affect dwell.
    congestion = max(
        warehouse_state.congestion_factor,
        congestion_multiplier(warehouse_state),
    )
    cargo_factor = cargo_profile.loading_time_factor
    priority_factor = priority_rule.loading_factor

    if cargo_factor <= 0 or priority_factor <= 0:
        raise ValueError("dwell factors must be positive")

    total = max(
        0.0,
        (
            base_minutes
            * congestion
            * cargo_factor
            * priority_factor
            + operational_noise_minutes
        ),
    )

    return DwellCalculation(
        base_minutes=base_minutes,
        congestion_factor=congestion,
        cargo_factor=cargo_factor,
        priority_factor=priority_factor,
        operational_noise_minutes=operational_noise_minutes,
        total_minutes=total,
    )


def can_handle_cargo(
    *,
    warehouse_state: WarehouseState,
    cargo_profile: CargoProfile,
) -> bool:
    if cargo_profile.requires_reefer:
        return warehouse_state.profile.cold_storage_capable
    return True


def priority_rule_for(
    priority: Priority,
    *,
    standard: PriorityRule,
    expedited: PriorityRule,
    critical: PriorityRule,
) -> PriorityRule:
    return {
        Priority.STANDARD: standard,
        Priority.EXPEDITED: expedited,
        Priority.CRITICAL: critical,
    }[priority]
