"""Deterministic reefer temperature-excursion integration for v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .cargo_exceptions import (
    ReeferExceptionState,
    ReeferTemperaturePolicy,
    make_reefer_exception_event,
    update_reefer_exception,
)
from .context import SimulationContext
from .eta import apply_eta, calculate_eta
from .events import make_arrival_event, make_departure_event, maybe_make_eta_updated_event
from .lifecycle import arrive, depart, mark_ready
from .models import (
    CargoProfile,
    OperationalEvent,
    Priority,
    RouteProfile,
    RouteState,
    Shipment,
    VehicleState,
    WarehouseState,
)
from .movement import movement_tick
from .scheduler import (
    priority_planning_buffer_minutes,
    scheduled_arrival_from_route,
    validate_shipment_compatibility,
)
from .telemetry import TimedFleetTelemetrySample, make_fleet_telemetry_row
from .vehicles import begin_loading, begin_transit, begin_unloading, reserve_vehicle


@dataclass(slots=True, frozen=True)
class ReeferShipmentPlan:
    shipment_id: int
    vehicle_id: int
    route: RouteProfile
    cargo: CargoProfile
    priority: Priority = Priority.STANDARD


@dataclass(slots=True, frozen=True)
class TemperatureExcursion:
    start_time: datetime
    end_time: datetime
    excursion_temp_c: float

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise ValueError("excursion end_time must be after start_time")

    def is_active(self, now: datetime) -> bool:
        return self.start_time <= now < self.end_time


@dataclass(slots=True)
class ReeferShipmentResult:
    shipment: Shipment
    vehicle: VehicleState
    route_state: RouteState
    telemetry_samples: list[TimedFleetTelemetrySample] = field(default_factory=list)
    events: list[OperationalEvent] = field(default_factory=list)


def _append_or_replace(
    samples: list[TimedFleetTelemetrySample],
    sample: TimedFleetTelemetrySample,
) -> None:
    if samples and samples[-1].time == sample.time:
        samples[-1] = sample
    else:
        samples.append(sample)


def run_reefer_exception_shipment(
    *,
    context: SimulationContext,
    plan: ReeferShipmentPlan,
    vehicle: VehicleState,
    origin: WarehouseState,
    destination: WarehouseState,
    policy: ReeferTemperaturePolicy,
    excursion: TemperatureExcursion,
    normal_cargo_temp_c: float,
    movement_interval_seconds: float = 600.0,
    base_consumption_pct_per_100km: float = 1.0,
    eta_event_threshold_min: float = 1.0,
) -> ReeferShipmentResult:
    """Run one refrigerated shipment through a deterministic temp excursion."""
    policy.validate()

    if not plan.cargo.requires_reefer:
        raise ValueError("reefer exception requires reefer cargo")
    if not vehicle.profile.reefer_capable:
        raise ValueError("vehicle must be reefer capable")

    validate_shipment_compatibility(
        vehicle=vehicle,
        cargo=plan.cargo,
        origin_warehouse=origin,
        destination_warehouse=destination,
        reserve_threshold_pct=15.0,
    )

    scheduled_departure = context.now()
    scheduled_arrival = scheduled_arrival_from_route(
        scheduled_departure=scheduled_departure,
        route=plan.route,
        planning_buffer_minutes=priority_planning_buffer_minutes(
            plan.priority
        ),
    )

    shipment = Shipment(
        shipment_id=plan.shipment_id,
        run_id=context.run_id,
        vehicle_id=vehicle.profile.vehicle_id,
        route_id=plan.route.route_id,
        origin_wh_id=plan.route.origin_wh_id,
        dest_wh_id=plan.route.dest_wh_id,
        cargo_type=plan.cargo.cargo_type,
        priority=plan.priority,
        scheduled_departure=scheduled_departure,
        scheduled_arrival=scheduled_arrival,
        estimated_arrival=scheduled_arrival,
    )

    mark_ready(shipment, context.now())
    reserve_vehicle(vehicle, shipment.shipment_id)
    begin_loading(vehicle)
    depart(shipment, context.now())
    begin_transit(vehicle)

    route_state = RouteState(profile=plan.route)
    state = ReeferExceptionState()
    events: list[OperationalEvent] = [
        make_departure_event(
            time=context.now(),
            shipment=shipment,
            vehicle=vehicle,
        )
    ]
    samples: list[TimedFleetTelemetrySample] = []

    while shipment.actual_arrival is None:
        now = context.now()

        tick = movement_tick(
            vehicle=vehicle,
            route_state=route_state,
            elapsed_seconds=movement_interval_seconds,
            current_progress_pct=shipment.route_progress_pct,
            origin_lat=origin.profile.lat,
            origin_lon=origin.profile.lon,
            destination_lat=destination.profile.lat,
            destination_lon=destination.profile.lon,
            base_consumption_pct_per_100km=base_consumption_pct_per_100km,
        )

        shipment.route_progress_pct = tick.route_progress_pct
        sample_time = now + timedelta(seconds=tick.elapsed_seconds)

        previous_eta = shipment.estimated_arrival
        eta_result = calculate_eta(
            now=sample_time,
            shipment=shipment,
            route_state=route_state,
            vehicle_profile=vehicle.profile,
        )
        apply_eta(shipment, eta_result)

        eta_event = maybe_make_eta_updated_event(
            time=sample_time,
            shipment=shipment,
            vehicle=vehicle,
            previous_eta=previous_eta,
            new_eta=shipment.estimated_arrival,
            threshold_minutes=eta_event_threshold_min,
        )
        if eta_event is not None:
            events.append(eta_event)

        cargo_temp_c = (
            excursion.excursion_temp_c
            if excursion.is_active(sample_time)
            else normal_cargo_temp_c
        )
        boundary = update_reefer_exception(
            now=sample_time,
            cargo_temp_c=cargo_temp_c,
            policy=policy,
            state=state,
        )
        if boundary is not None:
            events.append(
                make_reefer_exception_event(
                    event_type=boundary,
                    time=sample_time,
                    cargo_temp_c=cargo_temp_c,
                    policy=policy,
                    state=state,
                    shipment=shipment,
                    vehicle=vehicle,
                )
            )

        _append_or_replace(
            samples,
            TimedFleetTelemetrySample(
                time=sample_time,
                row=make_fleet_telemetry_row(
                    vehicle=vehicle,
                    shipment=shipment,
                    origin_lat=origin.profile.lat,
                    origin_lon=origin.profile.lon,
                    destination_lat=destination.profile.lat,
                    destination_lon=destination.profile.lon,
                    cargo_temp_c=cargo_temp_c,
                    cargo_humidity_pct=plan.cargo.target_humidity_pct,
                ),
            ),
        )

        if shipment.route_progress_pct >= 100.0:
            arrive(shipment, sample_time)
            begin_unloading(
                vehicle,
                warehouse_id=destination.profile.warehouse_id,
            )
            events.append(
                make_arrival_event(
                    time=sample_time,
                    shipment=shipment,
                    vehicle=vehicle,
                )
            )
            break

        delta = timedelta(seconds=tick.elapsed_seconds)
        if delta <= timedelta(0):
            raise RuntimeError("reefer simulation made no forward progress")
        context.advance(delta)

    return ReeferShipmentResult(
        shipment=shipment,
        vehicle=vehicle,
        route_state=route_state,
        telemetry_samples=samples,
        events=events,
    )
