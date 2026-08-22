"""Operational disruptions for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .models import OperationalEvent, RouteState, Shipment, VehicleState


class DisruptionType(str, Enum):
    TRAFFIC = "TRAFFIC"
    WEATHER = "WEATHER"
    MECHANICAL = "MECHANICAL"
    FUEL_STOP = "FUEL_STOP"
    REEFER = "REEFER"


@dataclass(slots=True, frozen=True)
class Disruption:
    disruption_id: str
    disruption_type: DisruptionType
    cause_code: str
    severity: str
    start_time: datetime
    duration_minutes: float
    speed_factor: float = 1.0
    delay_minutes: float = 0.0
    route_id: int | None = None
    vehicle_id: int | None = None

    def __post_init__(self) -> None:
        if not self.disruption_id:
            raise ValueError("disruption_id is required")
        if not self.cause_code:
            raise ValueError("cause_code is required")
        if self.duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive")
        if not 0 < self.speed_factor <= 1.0:
            raise ValueError("speed_factor must be in the range (0, 1]")
        if self.delay_minutes < 0:
            raise ValueError("delay_minutes cannot be negative")
        if self.severity not in {"INFO", "WARNING", "CRITICAL"}:
            raise ValueError("invalid disruption severity")

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(minutes=self.duration_minutes)

    def is_active(self, now: datetime) -> bool:
        return self.start_time <= now < self.end_time

    def affects(self, *, route_id: int, vehicle_id: int) -> bool:
        if self.route_id is not None and self.route_id != route_id:
            return False
        if self.vehicle_id is not None and self.vehicle_id != vehicle_id:
            return False
        return True


@dataclass(slots=True, frozen=True)
class AppliedDisruption:
    active: bool
    previous_traffic_factor: float
    resulting_traffic_factor: float
    delay_minutes: float


def traffic_disruption(
    *,
    disruption_id: str,
    start_time: datetime,
    duration_minutes: float,
    speed_factor: float,
    route_id: int,
    severity: str = "WARNING",
    cause_code: str = "TRAFFIC_CONGESTION",
) -> Disruption:
    return Disruption(
        disruption_id=disruption_id,
        disruption_type=DisruptionType.TRAFFIC,
        cause_code=cause_code,
        severity=severity,
        start_time=start_time,
        duration_minutes=duration_minutes,
        speed_factor=speed_factor,
        route_id=route_id,
    )


def weather_disruption(
    *,
    disruption_id: str,
    start_time: datetime,
    duration_minutes: float,
    weather_factor: float,
    route_id: int,
    severity: str = "WARNING",
    cause_code: str = "HEAVY_RAIN",
) -> Disruption:
    return Disruption(
        disruption_id=disruption_id,
        disruption_type=DisruptionType.WEATHER,
        cause_code=cause_code,
        severity=severity,
        start_time=start_time,
        duration_minutes=duration_minutes,
        speed_factor=weather_factor,
        route_id=route_id,
    )


def mechanical_disruption(
    *,
    disruption_id: str,
    start_time: datetime,
    duration_minutes: float,
    vehicle_id: int,
    severity: str = "CRITICAL",
    cause_code: str = "MECHANICAL_BREAKDOWN",
) -> Disruption:
    return Disruption(
        disruption_id=disruption_id,
        disruption_type=DisruptionType.MECHANICAL,
        cause_code=cause_code,
        severity=severity,
        start_time=start_time,
        duration_minutes=duration_minutes,
        speed_factor=1.0,
        vehicle_id=vehicle_id,
    )


def apply_traffic_disruption(
    *,
    disruption: Disruption,
    now: datetime,
    route_state: RouteState,
    vehicle: VehicleState,
) -> AppliedDisruption:
    previous = route_state.traffic_factor
    if disruption.disruption_type != DisruptionType.TRAFFIC:
        raise ValueError("apply_traffic_disruption requires TRAFFIC disruption")

    active = (
        disruption.is_active(now)
        and disruption.affects(
            route_id=route_state.profile.route_id,
            vehicle_id=vehicle.profile.vehicle_id,
        )
    )
    if not active:
        return AppliedDisruption(False, previous, previous, 0.0)

    route_state.traffic_factor = previous * disruption.speed_factor
    return AppliedDisruption(
        True,
        previous,
        route_state.traffic_factor,
        disruption.delay_minutes,
    )


def clear_traffic_disruption(
    *,
    applied: AppliedDisruption,
    route_state: RouteState,
) -> None:
    if applied.active:
        route_state.traffic_factor = applied.previous_traffic_factor


def apply_weather_disruption(
    *,
    disruption: Disruption,
    now: datetime,
    route_state: RouteState,
    vehicle: VehicleState,
) -> AppliedDisruption:
    previous = route_state.weather_factor
    if disruption.disruption_type != DisruptionType.WEATHER:
        raise ValueError("apply_weather_disruption requires WEATHER disruption")

    active = (
        disruption.is_active(now)
        and disruption.affects(
            route_id=route_state.profile.route_id,
            vehicle_id=vehicle.profile.vehicle_id,
        )
    )
    if not active:
        return AppliedDisruption(False, previous, previous, 0.0)

    route_state.weather_factor = previous * disruption.speed_factor
    return AppliedDisruption(
        True,
        previous,
        route_state.weather_factor,
        disruption.delay_minutes,
    )


def clear_weather_disruption(
    *,
    applied: AppliedDisruption,
    route_state: RouteState,
) -> None:
    if applied.active:
        route_state.weather_factor = applied.previous_traffic_factor


def make_disruption_event(
    *,
    time: datetime,
    disruption: Disruption,
    shipment: Shipment,
    vehicle: VehicleState,
    event_type: str = "DISRUPTION_STARTED",
) -> OperationalEvent:
    return OperationalEvent(
        event_id=(
            f"{event_type}-{shipment.shipment_id}-"
            f"{disruption.disruption_id}-{int(time.timestamp())}"
        ),
        time=time,
        event_type=event_type,
        shipment_id=shipment.shipment_id,
        vehicle_id=vehicle.profile.vehicle_id,
        route_id=shipment.route_id,
        run_id=shipment.run_id,
        severity=disruption.severity,
        cause_code=disruption.cause_code,
        location_lat=vehicle.lat,
        location_lon=vehicle.lon,
        detail={
            "disruption_id": disruption.disruption_id,
            "disruption_type": disruption.disruption_type.value,
            "start_time": disruption.start_time.isoformat(),
            "end_time": disruption.end_time.isoformat(),
            "speed_factor": disruption.speed_factor,
            "delay_minutes": disruption.delay_minutes,
        },
    )
