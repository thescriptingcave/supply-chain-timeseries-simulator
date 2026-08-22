from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.models import (
    Priority,
    Shipment,
    ShipmentLifecycle,
    VehicleProfile,
    VehicleState,
)


def test_shipment_rejects_invalid_schedule() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)

    shipment = Shipment(
        shipment_id=None,
        run_id=None,
        vehicle_id=1,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=start,
        scheduled_arrival=start,
        estimated_arrival=start,
        lifecycle_status=ShipmentLifecycle.PLANNED,
    )

    with pytest.raises(ValueError):
        shipment.validate_temporal_integrity()


def test_vehicle_state_rejects_invalid_fuel() -> None:
    profile = VehicleProfile(
        vehicle_id=1,
        vehicle_reg="TEST-1",
        vehicle_type="DRY_VAN",
        max_payload_kg=1000,
        fuel_type="DIESEL",
        fleet_operator="TEST",
        year_manufactured=2022,
        fuel_efficiency_factor=1.0,
        reliability_factor=1.0,
        condition_factor=1.0,
        cruise_speed_factor=1.0,
        maintenance_risk_factor=1.0,
        reefer_capable=False,
    )

    state = VehicleState(
        profile=profile,
        current_warehouse_id=1,
        lat=0.0,
        lon=0.0,
        fuel_level_pct=101.0,
    )

    with pytest.raises(ValueError):
        state.validate()
