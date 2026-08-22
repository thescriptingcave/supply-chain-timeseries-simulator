"""State-driven fuel-stop behavior for Supply Chain Generator v3.

A fuel stop is triggered by vehicle fuel state rather than by a pre-scheduled
external disruption. The first v3 implementation is deterministic and designed
for integration testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import OperationalEvent, Shipment, VehicleState


@dataclass(slots=True, frozen=True)
class FuelStopPolicy:
    trigger_pct: float = 25.0
    refuel_to_pct: float = 90.0
    stop_duration_minutes: float = 20.0

    def validate(self) -> None:
        if not 0 <= self.trigger_pct <= 100:
            raise ValueError("trigger_pct must be between 0 and 100")
        if not 0 <= self.refuel_to_pct <= 100:
            raise ValueError("refuel_to_pct must be between 0 and 100")
        if self.refuel_to_pct <= self.trigger_pct:
            raise ValueError("refuel_to_pct must exceed trigger_pct")
        if self.stop_duration_minutes <= 0:
            raise ValueError("stop_duration_minutes must be positive")


@dataclass(slots=True, frozen=True)
class FuelStop:
    start_time: datetime
    end_time: datetime
    fuel_before_pct: float
    fuel_after_pct: float
    cause_code: str = "LOW_FUEL_REFUEL"


def should_refuel(
    vehicle: VehicleState,
    policy: FuelStopPolicy,
) -> bool:
    policy.validate()
    return vehicle.fuel_level_pct <= policy.trigger_pct


def perform_refuel(
    *,
    now: datetime,
    vehicle: VehicleState,
    policy: FuelStopPolicy,
    allow_preemptive: bool = False,
) -> FuelStop:
    """Apply a deterministic refuel stop to the vehicle state.

    By default, refueling is allowed only when the current fuel level is at or
    below the trigger threshold. The fuel-stop engine may set
    ``allow_preemptive=True`` when the *next movement tick* is projected to
    cross the threshold or exhaust available fuel.
    """
    policy.validate()

    if not allow_preemptive and not should_refuel(vehicle, policy):
        raise ValueError("vehicle fuel level does not require refueling")

    before = vehicle.fuel_level_pct
    vehicle.fuel_level_pct = policy.refuel_to_pct

    return FuelStop(
        start_time=now,
        end_time=now + timedelta(minutes=policy.stop_duration_minutes),
        fuel_before_pct=before,
        fuel_after_pct=vehicle.fuel_level_pct,
    )


def make_fuel_stop_event(
    *,
    event_type: str,
    time: datetime,
    stop: FuelStop,
    shipment: Shipment,
    vehicle: VehicleState,
) -> OperationalEvent:
    if event_type not in {"FUEL_STOP_STARTED", "FUEL_STOP_ENDED"}:
        raise ValueError("invalid fuel-stop event type")

    severity = "WARNING" if event_type == "FUEL_STOP_STARTED" else "INFO"

    return OperationalEvent(
        event_id=(
            f"{event_type}-{shipment.shipment_id}-"
            f"{vehicle.profile.vehicle_id}-{int(time.timestamp())}"
        ),
        time=time,
        event_type=event_type,
        shipment_id=shipment.shipment_id,
        vehicle_id=vehicle.profile.vehicle_id,
        route_id=shipment.route_id,
        run_id=shipment.run_id,
        severity=severity,
        cause_code=stop.cause_code,
        location_lat=vehicle.lat,
        location_lon=vehicle.lon,
        detail={
            "fuel_before_pct": stop.fuel_before_pct,
            "fuel_after_pct": stop.fuel_after_pct,
            "stop_duration_minutes": (
                stop.end_time - stop.start_time
            ).total_seconds() / 60.0,
        },
    )
