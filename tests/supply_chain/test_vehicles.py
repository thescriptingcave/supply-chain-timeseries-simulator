import pytest

from generators.supply_chain.models import (
    VehicleAvailability,
    VehicleProfile,
    VehicleState,
)
from generators.supply_chain.vehicles import (
    apply_movement,
    begin_loading,
    begin_transit,
    begin_turnaround,
    begin_unloading,
    calculate_fuel_use_pct,
    needs_refuel,
    refuel,
    release_vehicle,
    reserve_vehicle,
)


def make_vehicle_state(
    *,
    fuel_level_pct: float = 100.0,
    efficiency: float = 1.0,
) -> VehicleState:
    profile = VehicleProfile(
        vehicle_id=1,
        vehicle_reg="TEST-1",
        vehicle_type="DRY_VAN",
        max_payload_kg=10000,
        fuel_type="DIESEL",
        fleet_operator="TEST",
        year_manufactured=2022,
        fuel_efficiency_factor=efficiency,
        reliability_factor=1.0,
        condition_factor=1.0,
        cruise_speed_factor=1.0,
        maintenance_risk_factor=1.0,
        reefer_capable=False,
    )

    return VehicleState(
        profile=profile,
        current_warehouse_id=1,
        lat=0.0,
        lon=0.0,
        fuel_level_pct=fuel_level_pct,
        odometer_km=1000.0,
    )


def test_vehicle_assignment_lifecycle() -> None:
    state = make_vehicle_state()

    reserve_vehicle(state, shipment_id=10)
    assert state.availability == VehicleAvailability.RESERVED
    assert state.active_shipment_id == 10

    begin_loading(state)
    assert state.availability == VehicleAvailability.LOADING

    begin_transit(state)
    assert state.availability == VehicleAvailability.IN_TRANSIT
    assert state.current_warehouse_id is None

    begin_unloading(state, warehouse_id=2)
    assert state.availability == VehicleAvailability.UNLOADING
    assert state.current_warehouse_id == 2

    begin_turnaround(state)
    assert state.availability == VehicleAvailability.TURNAROUND

    release_vehicle(state)
    assert state.availability == VehicleAvailability.AVAILABLE
    assert state.active_shipment_id is None


def test_vehicle_cannot_be_double_assigned() -> None:
    state = make_vehicle_state()
    reserve_vehicle(state, shipment_id=10)

    with pytest.raises(ValueError):
        reserve_vehicle(state, shipment_id=11)


def test_vehicle_cannot_depart_without_loading_state() -> None:
    state = make_vehicle_state()
    reserve_vehicle(state, shipment_id=10)

    with pytest.raises(ValueError):
        begin_transit(state)


def test_fuel_use_scales_with_distance() -> None:
    short = calculate_fuel_use_pct(
        distance_km=100,
        base_consumption_pct_per_100km=4.0,
        fuel_efficiency_factor=1.0,
    )
    long = calculate_fuel_use_pct(
        distance_km=200,
        base_consumption_pct_per_100km=4.0,
        fuel_efficiency_factor=1.0,
    )

    assert short == pytest.approx(4.0)
    assert long == pytest.approx(8.0)


def test_more_efficient_vehicle_uses_less_fuel() -> None:
    normal = calculate_fuel_use_pct(
        distance_km=200,
        base_consumption_pct_per_100km=4.0,
        fuel_efficiency_factor=1.0,
    )
    efficient = calculate_fuel_use_pct(
        distance_km=200,
        base_consumption_pct_per_100km=4.0,
        fuel_efficiency_factor=1.1,
    )

    assert efficient < normal


def test_movement_updates_fuel_and_odometer() -> None:
    state = make_vehicle_state(fuel_level_pct=80.0)
    reserve_vehicle(state, shipment_id=10)
    begin_loading(state)
    begin_transit(state)

    result = apply_movement(
        state,
        distance_km=100.0,
        base_consumption_pct_per_100km=5.0,
    )

    assert result.fuel_used_pct == pytest.approx(5.0)
    assert state.fuel_level_pct == pytest.approx(75.0)
    assert state.odometer_km == pytest.approx(1100.0)


def test_movement_cannot_create_negative_fuel() -> None:
    state = make_vehicle_state(fuel_level_pct=2.0)
    reserve_vehicle(state, shipment_id=10)
    begin_loading(state)
    begin_transit(state)

    with pytest.raises(ValueError):
        apply_movement(
            state,
            distance_km=100.0,
            base_consumption_pct_per_100km=5.0,
        )


def test_refuel_updates_persistent_fuel_state() -> None:
    state = make_vehicle_state(fuel_level_pct=20.0)

    added = refuel(state, target_fuel_pct=85.0)

    assert added == pytest.approx(65.0)
    assert state.fuel_level_pct == pytest.approx(85.0)


def test_needs_refuel_uses_reserve_threshold() -> None:
    low = make_vehicle_state(fuel_level_pct=15.0)
    healthy = make_vehicle_state(fuel_level_pct=50.0)

    assert needs_refuel(low, reserve_threshold_pct=15.0)
    assert not needs_refuel(healthy, reserve_threshold_pct=15.0)
