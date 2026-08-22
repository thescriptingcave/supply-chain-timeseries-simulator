"""Deterministic vehicle breakdown execution for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .context import SimulationContext
from .disruptions import Disruption, DisruptionType, make_disruption_event
from .eta import apply_eta, calculate_eta
from .events import make_arrival_event, make_departure_event, maybe_make_eta_updated_event
from .lifecycle import arrive, depart, mark_ready
from .models import CargoProfile, OperationalEvent, Priority, RouteProfile, RouteState, Shipment, VehicleState, WarehouseState
from .movement import movement_tick
from .scheduler import priority_planning_buffer_minutes, scheduled_arrival_from_route, validate_shipment_compatibility
from .telemetry import TimedFleetTelemetrySample, make_fleet_telemetry_row
from .vehicles import begin_loading, begin_transit, begin_unloading, reserve_vehicle


@dataclass(slots=True, frozen=True)
class MechanicalShipmentPlan:
    shipment_id: int
    vehicle_id: int
    route: RouteProfile
    cargo: CargoProfile
    priority: Priority = Priority.STANDARD


@dataclass(slots=True)
class MechanicalShipmentResult:
    shipment: Shipment
    vehicle: VehicleState
    route_state: RouteState
    telemetry_samples: list[TimedFleetTelemetrySample] = field(default_factory=list)
    events: list[OperationalEvent] = field(default_factory=list)



def _append_or_replace_telemetry(
    samples: list[TimedFleetTelemetrySample],
    sample: TimedFleetTelemetrySample,
) -> None:
    """Keep one authoritative telemetry row per timestamp.

    When two state transitions land on the same timestamp, the later state
    replaces the earlier one. This is especially important at disruption
    boundaries where a movement tick and a stopped/resumed state can coincide.
    """
    if samples and samples[-1].time == sample.time:
        samples[-1] = sample
        return

    samples.append(sample)



def run_mechanical_disruption_shipment(
    *,
    context: SimulationContext,
    plan: MechanicalShipmentPlan,
    vehicle: VehicleState,
    origin: WarehouseState,
    destination: WarehouseState,
    disruption: Disruption,
    movement_interval_seconds: float = 600.0,
    base_consumption_pct_per_100km: float = 1.0,
    eta_event_threshold_min: float = 1.0,
) -> MechanicalShipmentResult:
    if disruption.disruption_type != DisruptionType.MECHANICAL:
        raise ValueError("mechanical disruption required")
    if disruption.vehicle_id != vehicle.profile.vehicle_id:
        raise ValueError("mechanical disruption must target this vehicle")

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
        planning_buffer_minutes=priority_planning_buffer_minutes(plan.priority),
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
    events = [make_departure_event(time=context.now(), shipment=shipment, vehicle=vehicle)]
    samples: list[TimedFleetTelemetrySample] = []
    started = False
    ended = False

    while shipment.actual_arrival is None:
        now = context.now()

        active = (
            disruption.is_active(now)
            and disruption.affects(
                route_id=plan.route.route_id,
                vehicle_id=vehicle.profile.vehicle_id,
            )
        )

        if active:
            if not started:
                started = True
                events.append(
                    make_disruption_event(
                        time=now,
                        disruption=disruption,
                        shipment=shipment,
                        vehicle=vehicle,
                        event_type="DISRUPTION_STARTED",
                    )
                )

            previous_eta = shipment.estimated_arrival
            baseline = calculate_eta(
                now=disruption.end_time,
                shipment=shipment,
                route_state=route_state,
                vehicle_profile=vehicle.profile,
            )
            new_eta = disruption.end_time + timedelta(
                minutes=baseline.remaining_travel_minutes
            )
            shipment.estimated_arrival = new_eta

            eta_event = maybe_make_eta_updated_event(
                time=now,
                shipment=shipment,
                vehicle=vehicle,
                previous_eta=previous_eta,
                new_eta=new_eta,
                threshold_minutes=eta_event_threshold_min,
                cause_code=disruption.cause_code,
            )
            if eta_event is not None:
                events.append(eta_event)

            original_speed = vehicle.speed_kmh
            vehicle.speed_kmh = 0.0

            stopped_sample = TimedFleetTelemetrySample(
                time=now,
                row=make_fleet_telemetry_row(
                    vehicle=vehicle,
                    shipment=shipment,
                    origin_lat=origin.profile.lat,
                    origin_lon=origin.profile.lon,
                    destination_lat=destination.profile.lat,
                    destination_lon=destination.profile.lon,
                ),
            )

            # A movement tick may end exactly when the breakdown begins.
            # In that case the prior tick has already emitted telemetry at
            # this timestamp. Replace that boundary sample with the stopped
            # state instead of persisting contradictory moving/stopped rows.
            _append_or_replace_telemetry(
                samples,
                stopped_sample,
            )

            vehicle.speed_kmh = original_speed

            step = min(
                timedelta(seconds=movement_interval_seconds),
                disruption.end_time - now,
            )
            if step > timedelta(0):
                context.advance(step)
            continue

        if started and not ended and now >= disruption.end_time:
            ended = True
            events.append(
                make_disruption_event(
                    time=now,
                    disruption=disruption,
                    shipment=shipment,
                    vehicle=vehicle,
                    event_type="DISRUPTION_ENDED",
                )
            )

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

        _append_or_replace_telemetry(
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
                ),
            ),
        )

        if shipment.route_progress_pct >= 100.0:
            arrive(shipment, sample_time)
            begin_unloading(vehicle, warehouse_id=destination.profile.warehouse_id)
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
            raise RuntimeError("mechanical simulation made no forward progress")
        context.advance(delta)

    return MechanicalShipmentResult(
        shipment=shipment,
        vehicle=vehicle,
        route_state=route_state,
        telemetry_samples=samples,
        events=events,
    )
