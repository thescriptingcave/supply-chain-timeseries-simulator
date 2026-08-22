"""Cargo/reefer exception behavior for Supply Chain Generator v3.

This module models deterministic refrigerated-cargo temperature excursions.
The exception is an IoT/quality event: it does not necessarily stop the vehicle,
but it creates causal events and preserves the temperature breach in telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import OperationalEvent, Shipment, VehicleState


@dataclass(slots=True, frozen=True)
class ReeferTemperaturePolicy:
    min_temp_c: float
    max_temp_c: float
    recovery_temp_c: float
    cause_code: str = "REEFER_TEMP_EXCURSION"

    def validate(self) -> None:
        if self.min_temp_c >= self.max_temp_c:
            raise ValueError("min_temp_c must be less than max_temp_c")
        if not self.min_temp_c <= self.recovery_temp_c <= self.max_temp_c:
            raise ValueError(
                "recovery_temp_c must be inside the allowed temperature range"
            )


@dataclass(slots=True)
class ReeferExceptionState:
    active: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None
    peak_temp_c: float | None = None


def temperature_out_of_range(
    *,
    cargo_temp_c: float,
    policy: ReeferTemperaturePolicy,
) -> bool:
    policy.validate()
    return (
        cargo_temp_c < policy.min_temp_c
        or cargo_temp_c > policy.max_temp_c
    )


def update_reefer_exception(
    *,
    now: datetime,
    cargo_temp_c: float,
    policy: ReeferTemperaturePolicy,
    state: ReeferExceptionState,
) -> str | None:
    """Update exception state and return a boundary event type when one occurs."""
    out_of_range = temperature_out_of_range(
        cargo_temp_c=cargo_temp_c,
        policy=policy,
    )

    if out_of_range and not state.active:
        state.active = True
        state.started_at = now
        state.peak_temp_c = cargo_temp_c
        return "CARGO_EXCEPTION_STARTED"

    if out_of_range and state.active:
        if (
            state.peak_temp_c is None
            or cargo_temp_c > state.peak_temp_c
        ):
            state.peak_temp_c = cargo_temp_c
        return None

    if state.active and not out_of_range:
        state.active = False
        state.ended_at = now
        return "CARGO_EXCEPTION_ENDED"

    return None


def make_reefer_exception_event(
    *,
    event_type: str,
    time: datetime,
    cargo_temp_c: float,
    policy: ReeferTemperaturePolicy,
    state: ReeferExceptionState,
    shipment: Shipment,
    vehicle: VehicleState,
) -> OperationalEvent:
    if event_type not in {
        "CARGO_EXCEPTION_STARTED",
        "CARGO_EXCEPTION_ENDED",
    }:
        raise ValueError("invalid cargo exception event type")

    severity = (
        "CRITICAL"
        if event_type == "CARGO_EXCEPTION_STARTED"
        else "INFO"
    )

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
        cause_code=policy.cause_code,
        location_lat=vehicle.lat,
        location_lon=vehicle.lon,
        detail={
            "cargo_temp_c": cargo_temp_c,
            "min_temp_c": policy.min_temp_c,
            "max_temp_c": policy.max_temp_c,
            "recovery_temp_c": policy.recovery_temp_c,
            "peak_temp_c": state.peak_temp_c,
        },
    )
