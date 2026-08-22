"""Disruption-aware concurrent movement for Supply Chain Generator v3.

This integration layer applies deterministic traffic disruptions during
concurrent movement. It is intentionally focused on traffic first; weather,
mechanical faults, and fuel stops will plug into the same disruption contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .context import SimulationContext
from .disruptions import (
    AppliedDisruption,
    Disruption,
    DisruptionType,
    apply_traffic_disruption,
    apply_weather_disruption,
    clear_traffic_disruption,
    clear_weather_disruption,
    make_disruption_event,
)
from .eta import (
    apply_eta,
    calculate_eta,
    calculate_eta_with_temporary_traffic,
    calculate_eta_with_temporary_weather,
)
from .events import (
    make_arrival_event,
    make_departure_event,
    maybe_make_eta_updated_event,
)
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
from .vehicles import (
    begin_loading,
    begin_transit,
    begin_unloading,
    reserve_vehicle,
)


@dataclass(slots=True, frozen=True)
class DisruptedShipmentPlan:
    shipment_id: int
    vehicle_id: int
    route: RouteProfile
    cargo: CargoProfile
    priority: Priority = Priority.STANDARD


@dataclass(slots=True)
class ActiveDisruptedShipment:
    shipment: Shipment
    vehicle: VehicleState
    route_state: RouteState
    origin: WarehouseState
    destination: WarehouseState
    telemetry_samples: list[TimedFleetTelemetrySample] = field(default_factory=list)
    events: list[OperationalEvent] = field(default_factory=list)
    active_disruption_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class DisruptionAwareFleetResult:
    shipments: list[ActiveDisruptedShipment] = field(default_factory=list)

    @property
    def telemetry_rows(self) -> int:
        return sum(len(item.telemetry_samples) for item in self.shipments)

    @property
    def event_count(self) -> int:
        return sum(len(item.events) for item in self.shipments)


def _vehicle_by_id(
    vehicles: list[VehicleState],
    vehicle_id: int,
) -> VehicleState:
    for vehicle in vehicles:
        if vehicle.profile.vehicle_id == vehicle_id:
            return vehicle
    raise ValueError(f"vehicle_id={vehicle_id} not found")


def _traffic_disruptions_for(
    *,
    disruptions: list[Disruption],
    now: datetime,
    route_id: int,
    vehicle_id: int,
) -> list[Disruption]:
    return [
        disruption
        for disruption in disruptions
        if disruption.disruption_type == DisruptionType.TRAFFIC
        and disruption.is_active(now)
        and disruption.affects(
            route_id=route_id,
            vehicle_id=vehicle_id,
        )
    ]


def _weather_disruptions_for(
    *,
    disruptions: list[Disruption],
    now: datetime,
    route_id: int,
    vehicle_id: int,
) -> list[Disruption]:
    return [
        disruption
        for disruption in disruptions
        if disruption.disruption_type == DisruptionType.WEATHER
        and disruption.is_active(now)
        and disruption.affects(
            route_id=route_id,
            vehicle_id=vehicle_id,
        )
    ]


def _apply_active_weather(
    *,
    item: ActiveDisruptedShipment,
    disruptions: list[Disruption],
    now: datetime,
) -> list[tuple[Disruption, AppliedDisruption]]:
    applied: list[tuple[Disruption, AppliedDisruption]] = []

    for disruption in _weather_disruptions_for(
        disruptions=disruptions,
        now=now,
        route_id=item.route_state.profile.route_id,
        vehicle_id=item.vehicle.profile.vehicle_id,
    ):
        result = apply_weather_disruption(
            disruption=disruption,
            now=now,
            route_state=item.route_state,
            vehicle=item.vehicle,
        )
        applied.append((disruption, result))

        if (
            result.active
            and disruption.disruption_id not in item.active_disruption_ids
        ):
            item.active_disruption_ids.add(disruption.disruption_id)
            item.events.append(
                make_disruption_event(
                    time=now,
                    disruption=disruption,
                    shipment=item.shipment,
                    vehicle=item.vehicle,
                    event_type="DISRUPTION_STARTED",
                )
            )

    return applied


def _clear_applied_weather(
    *,
    item: ActiveDisruptedShipment,
    applied: list[tuple[Disruption, AppliedDisruption]],
) -> None:
    for _, result in reversed(applied):
        clear_weather_disruption(
            applied=result,
            route_state=item.route_state,
        )


def _apply_active_traffic(
    *,
    item: ActiveDisruptedShipment,
    disruptions: list[Disruption],
    now: datetime,
) -> list[tuple[Disruption, AppliedDisruption]]:
    """Apply all traffic effects for this tick and emit start events once."""
    applied: list[tuple[Disruption, AppliedDisruption]] = []

    for disruption in _traffic_disruptions_for(
        disruptions=disruptions,
        now=now,
        route_id=item.route_state.profile.route_id,
        vehicle_id=item.vehicle.profile.vehicle_id,
    ):
        result = apply_traffic_disruption(
            disruption=disruption,
            now=now,
            route_state=item.route_state,
            vehicle=item.vehicle,
        )
        applied.append((disruption, result))

        if (
            result.active
            and disruption.disruption_id not in item.active_disruption_ids
        ):
            item.active_disruption_ids.add(disruption.disruption_id)
            item.events.append(
                make_disruption_event(
                    time=now,
                    disruption=disruption,
                    shipment=item.shipment,
                    vehicle=item.vehicle,
                    event_type="DISRUPTION_STARTED",
                )
            )

    return applied


def _clear_applied_traffic(
    *,
    item: ActiveDisruptedShipment,
    applied: list[tuple[Disruption, AppliedDisruption]],
) -> None:
    """Restore traffic factor in reverse order after a movement tick."""
    for _, result in reversed(applied):
        clear_traffic_disruption(
            applied=result,
            route_state=item.route_state,
        )


def _emit_ended_disruptions(
    *,
    item: ActiveDisruptedShipment,
    disruptions: list[Disruption],
    now: datetime,
) -> None:
    """Emit one end event when an already-started disruption window closes."""
    ended_ids = [
        disruption_id
        for disruption_id in item.active_disruption_ids
        if any(
            disruption.disruption_id == disruption_id
            and now >= disruption.end_time
            for disruption in disruptions
        )
    ]

    for disruption_id in ended_ids:
        disruption = next(
            disruption
            for disruption in disruptions
            if disruption.disruption_id == disruption_id
        )
        item.events.append(
            make_disruption_event(
                time=now,
                disruption=disruption,
                shipment=item.shipment,
                vehicle=item.vehicle,
                event_type="DISRUPTION_ENDED",
            )
        )
        item.active_disruption_ids.remove(disruption_id)


def run_disruption_aware_fleet(
    *,
    context: SimulationContext,
    plans: list[DisruptedShipmentPlan],
    vehicles: list[VehicleState],
    warehouses: dict[int, WarehouseState],
    disruptions: list[Disruption],
    movement_interval_seconds: float = 600.0,
    base_consumption_pct_per_100km: float = 1.0,
    reserve_threshold_pct: float = 15.0,
    eta_event_threshold_min: float = 5.0,
) -> DisruptionAwareFleetResult:
    """Run multiple vehicles concurrently with deterministic traffic effects."""
    if movement_interval_seconds <= 0:
        raise ValueError("movement_interval_seconds must be positive")

    used_vehicle_ids: set[int] = set()
    active: list[ActiveDisruptedShipment] = []

    for plan in plans:
        if plan.vehicle_id in used_vehicle_ids:
            raise ValueError(
                f"vehicle_id={plan.vehicle_id} assigned to overlapping plans"
            )
        used_vehicle_ids.add(plan.vehicle_id)

        vehicle = _vehicle_by_id(vehicles, plan.vehicle_id)
        origin = warehouses[plan.route.origin_wh_id]
        destination = warehouses[plan.route.dest_wh_id]

        validate_shipment_compatibility(
            vehicle=vehicle,
            cargo=plan.cargo,
            origin_warehouse=origin,
            destination_warehouse=destination,
            reserve_threshold_pct=reserve_threshold_pct,
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
            vehicle_id=plan.vehicle_id,
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

        active.append(
            ActiveDisruptedShipment(
                shipment=shipment,
                vehicle=vehicle,
                route_state=RouteState(profile=plan.route),
                origin=origin,
                destination=destination,
                events=[
                    make_departure_event(
                        time=context.now(),
                        shipment=shipment,
                        vehicle=vehicle,
                    )
                ],
            )
        )

    arrived_ids: set[int] = set()

    while len(arrived_ids) < len(active):
        cycle_start = context.now()
        max_elapsed = 0.0

        for item in active:
            if item.shipment.shipment_id in arrived_ids:
                continue

            _emit_ended_disruptions(
                item=item,
                disruptions=disruptions,
                now=cycle_start,
            )

            applied_traffic = _apply_active_traffic(
                item=item,
                disruptions=disruptions,
                now=cycle_start,
            )
            applied_weather = _apply_active_weather(
                item=item,
                disruptions=disruptions,
                now=cycle_start,
            )

            tick = movement_tick(
                vehicle=item.vehicle,
                route_state=item.route_state,
                elapsed_seconds=movement_interval_seconds,
                current_progress_pct=item.shipment.route_progress_pct,
                origin_lat=item.origin.profile.lat,
                origin_lon=item.origin.profile.lon,
                destination_lat=item.destination.profile.lat,
                destination_lon=item.destination.profile.lon,
                base_consumption_pct_per_100km=base_consumption_pct_per_100km,
            )

            item.shipment.route_progress_pct = tick.route_progress_pct
            max_elapsed = max(max_elapsed, tick.elapsed_seconds)

            sample_time = cycle_start + timedelta(
                seconds=tick.elapsed_seconds
            )

            previous_eta = item.shipment.estimated_arrival

            if applied_traffic:
                disruption, applied_effect = applied_traffic[0]
                eta_result = calculate_eta_with_temporary_traffic(
                    now=sample_time,
                    shipment=item.shipment,
                    route_state=item.route_state,
                    vehicle_profile=item.vehicle.profile,
                    disruption_end=disruption.end_time,
                    normal_traffic_factor=(
                        applied_effect.previous_traffic_factor
                    ),
                )
                cause_code = disruption.cause_code
            elif applied_weather:
                disruption, applied_effect = applied_weather[0]
                eta_result = calculate_eta_with_temporary_weather(
                    now=sample_time,
                    shipment=item.shipment,
                    route_state=item.route_state,
                    vehicle_profile=item.vehicle.profile,
                    disruption_end=disruption.end_time,
                    normal_weather_factor=(
                        applied_effect.previous_traffic_factor
                    ),
                )
                cause_code = disruption.cause_code
            else:
                eta_result = calculate_eta(
                    now=sample_time,
                    shipment=item.shipment,
                    route_state=item.route_state,
                    vehicle_profile=item.vehicle.profile,
                )
                cause_code = None

            apply_eta(item.shipment, eta_result)

            eta_event = maybe_make_eta_updated_event(
                time=sample_time,
                shipment=item.shipment,
                vehicle=item.vehicle,
                previous_eta=previous_eta,
                new_eta=item.shipment.estimated_arrival,
                threshold_minutes=eta_event_threshold_min,
                cause_code=cause_code,
            )
            if eta_event is not None:
                item.events.append(eta_event)

            item.telemetry_samples.append(
                TimedFleetTelemetrySample(
                    time=sample_time,
                    row=make_fleet_telemetry_row(
                        vehicle=item.vehicle,
                        shipment=item.shipment,
                        origin_lat=item.origin.profile.lat,
                        origin_lon=item.origin.profile.lon,
                        destination_lat=item.destination.profile.lat,
                        destination_lon=item.destination.profile.lon,
                    ),
                )
            )

            _clear_applied_weather(
                item=item,
                applied=applied_weather,
            )
            _clear_applied_traffic(
                item=item,
                applied=applied_traffic,
            )

            if item.shipment.route_progress_pct >= 100.0:
                arrive(item.shipment, sample_time)
                begin_unloading(
                    item.vehicle,
                    warehouse_id=item.destination.profile.warehouse_id,
                )
                item.events.append(
                    make_arrival_event(
                        time=sample_time,
                        shipment=item.shipment,
                        vehicle=item.vehicle,
                    )
                )
                arrived_ids.add(item.shipment.shipment_id)

        if len(arrived_ids) == len(active):
            break

        delta = timedelta(seconds=max_elapsed)
        if delta <= timedelta(0):
            raise RuntimeError(
                "disruption-aware simulation made no forward progress"
            )
        context.advance(delta)

    return DisruptionAwareFleetResult(shipments=active)
