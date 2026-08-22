"""Vehicle-availability scheduling for Supply Chain Generator v3 validation runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import VehicleProfile


@dataclass(slots=True)
class VehicleAvailabilityWindow:
    vehicle_id: int
    available_at: datetime


def initialize_vehicle_availability(
    *,
    vehicle_profiles: list[VehicleProfile],
    start_time: datetime,
) -> dict[int, VehicleAvailabilityWindow]:
    if not vehicle_profiles:
        raise ValueError("vehicle_profiles cannot be empty")

    return {
        profile.vehicle_id: VehicleAvailabilityWindow(
            vehicle_id=profile.vehicle_id,
            available_at=start_time,
        )
        for profile in vehicle_profiles
    }


def choose_available_vehicle(
    *,
    vehicle_profiles: list[VehicleProfile],
    availability: dict[int, VehicleAvailabilityWindow],
    requested_departure: datetime,
    requires_reefer: bool,
) -> tuple[VehicleProfile, datetime]:
    """Choose the earliest compatible available vehicle.

    If no compatible vehicle is free at the requested departure time, the
    shipment is delayed until the earliest compatible vehicle becomes free.
    """
    compatible = [
        profile
        for profile in vehicle_profiles
        if (not requires_reefer or profile.reefer_capable)
    ]

    if not compatible:
        raise ValueError("no compatible vehicle available for shipment")

    compatible.sort(
        key=lambda profile: (
            availability[profile.vehicle_id].available_at,
            profile.vehicle_id,
        )
    )

    selected = compatible[0]
    actual_start = max(
        requested_departure,
        availability[selected.vehicle_id].available_at,
    )

    return selected, actual_start


def mark_vehicle_available(
    *,
    availability: dict[int, VehicleAvailabilityWindow],
    vehicle_id: int,
    available_at: datetime,
    turnaround_minutes: float = 0.0,
) -> None:
    if turnaround_minutes < 0:
        raise ValueError("turnaround_minutes cannot be negative")

    availability[vehicle_id].available_at = (
        available_at + timedelta(minutes=turnaround_minutes)
    )
