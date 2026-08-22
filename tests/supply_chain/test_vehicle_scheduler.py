from datetime import datetime, timedelta, timezone

from generators.supply_chain.models import VehicleProfile
from generators.supply_chain.vehicle_scheduler import (
    choose_available_vehicle,
    initialize_vehicle_availability,
    mark_vehicle_available,
)


def profile(vehicle_id: int, *, reefer: bool = False) -> VehicleProfile:
    return VehicleProfile(
        vehicle_id=vehicle_id,
        vehicle_reg=f"V{vehicle_id}",
        vehicle_type="REEFER" if reefer else "DRY_VAN",
        max_payload_kg=10000,
        fuel_type="DIESEL",
        fleet_operator="TEST",
        year_manufactured=2022,
        fuel_efficiency_factor=1.0,
        reliability_factor=1.0,
        condition_factor=1.0,
        cruise_speed_factor=1.0,
        maintenance_risk_factor=1.0,
        reefer_capable=reefer,
    )


def test_scheduler_delays_shipment_until_vehicle_is_free() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    vehicles = [profile(1), profile(2)]
    availability = initialize_vehicle_availability(
        vehicle_profiles=vehicles,
        start_time=start,
    )

    mark_vehicle_available(
        availability=availability,
        vehicle_id=1,
        available_at=start + timedelta(hours=5),
    )
    mark_vehicle_available(
        availability=availability,
        vehicle_id=2,
        available_at=start + timedelta(hours=3),
    )

    selected, actual_start = choose_available_vehicle(
        vehicle_profiles=vehicles,
        availability=availability,
        requested_departure=start + timedelta(hours=1),
        requires_reefer=False,
    )

    assert selected.vehicle_id == 2
    assert actual_start == start + timedelta(hours=3)


def test_scheduler_respects_reefer_capability() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    vehicles = [profile(1), profile(2, reefer=True)]
    availability = initialize_vehicle_availability(
        vehicle_profiles=vehicles,
        start_time=start,
    )

    selected, _ = choose_available_vehicle(
        vehicle_profiles=vehicles,
        availability=availability,
        requested_departure=start,
        requires_reefer=True,
    )

    assert selected.vehicle_id == 2


def test_turnaround_extends_availability() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    vehicles = [profile(1)]
    availability = initialize_vehicle_availability(
        vehicle_profiles=vehicles,
        start_time=start,
    )

    mark_vehicle_available(
        availability=availability,
        vehicle_id=1,
        available_at=start + timedelta(hours=2),
        turnaround_minutes=30,
    )

    assert (
        availability[1].available_at
        == start + timedelta(hours=2, minutes=30)
    )
