from datetime import datetime, timezone

import pytest

from generators.supply_chain.fuel_stop import (
    FuelStopPolicy,
    perform_refuel,
)
from generators.supply_chain.models import VehicleProfile, VehicleState


def vehicle(fuel_pct: float) -> VehicleState:
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
        fuel_level_pct=fuel_pct,
    )


def policy() -> FuelStopPolicy:
    return FuelStopPolicy(
        trigger_pct=25.0,
        refuel_to_pct=90.0,
        stop_duration_minutes=20.0,
    )


def test_default_refuel_still_rejects_fuel_above_threshold() -> None:
    with pytest.raises(ValueError):
        perform_refuel(
            now=datetime(2026, 8, 18, tzinfo=timezone.utc),
            vehicle=vehicle(26.0),
            policy=policy(),
        )


def test_preemptive_refuel_allows_projected_threshold_crossing() -> None:
    v = vehicle(26.0)

    stop = perform_refuel(
        now=datetime(2026, 8, 18, tzinfo=timezone.utc),
        vehicle=v,
        policy=policy(),
        allow_preemptive=True,
    )

    assert stop.fuel_before_pct == pytest.approx(26.0)
    assert stop.fuel_after_pct == pytest.approx(90.0)
    assert v.fuel_level_pct == pytest.approx(90.0)
