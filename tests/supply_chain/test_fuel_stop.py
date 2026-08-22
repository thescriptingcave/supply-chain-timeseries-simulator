from datetime import datetime, timezone

import pytest

from generators.supply_chain.fuel_stop import (
    FuelStopPolicy,
    perform_refuel,
    should_refuel,
)
from generators.supply_chain.models import VehicleProfile, VehicleState


def vehicle(fuel: float) -> VehicleState:
    return VehicleState(
        profile=VehicleProfile(
            vehicle_id=1,
            vehicle_reg="V1",
            vehicle_type="DRY_VAN",
            max_payload_kg=10000,
            fuel_type="DIESEL",
            fleet_operator="TEST",
            year_manufactured=2022,
            fuel_efficiency_factor=1.0,
            reliability_factor=1.0,
            condition_factor=1.0,
            cruise_speed_factor=1.0,
            maintenance_risk_factor=1.0,
            reefer_capable=False,
        ),
        current_warehouse_id=1,
        lat=0.0,
        lon=0.0,
        fuel_level_pct=fuel,
    )


def test_low_fuel_triggers_stop() -> None:
    assert should_refuel(vehicle(20.0), FuelStopPolicy(trigger_pct=25.0))


def test_fuel_above_threshold_does_not_trigger() -> None:
    assert not should_refuel(vehicle(40.0), FuelStopPolicy(trigger_pct=25.0))


def test_refuel_restores_target_level() -> None:
    v = vehicle(20.0)
    stop = perform_refuel(
        now=datetime(2026, 8, 18, tzinfo=timezone.utc),
        vehicle=v,
        policy=FuelStopPolicy(
            trigger_pct=25.0,
            refuel_to_pct=90.0,
            stop_duration_minutes=20.0,
        ),
    )
    assert stop.fuel_before_pct == pytest.approx(20.0)
    assert stop.fuel_after_pct == pytest.approx(90.0)
    assert v.fuel_level_pct == pytest.approx(90.0)


def test_invalid_policy_rejected() -> None:
    with pytest.raises(ValueError):
        FuelStopPolicy(
            trigger_pct=30.0,
            refuel_to_pct=20.0,
        ).validate()
