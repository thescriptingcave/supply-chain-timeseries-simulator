"""Concurrent multi-vehicle simulation core for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .context import SimulationContext
from .eta import apply_eta, calculate_eta
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
class ConcurrentShipmentPlan:
    shipment_id: int
    vehicle_id: int
    route: RouteProfile
    cargo: CargoProfile
    priority: Priority = Priority.STANDARD


@dataclass(slots=True)
class ActiveConcurrentShipment:
    shipment: Shipment
    vehicle: VehicleState
    route_state: RouteState
    origin: WarehouseState
    destination: WarehouseState
    telemetry_samples: list[TimedFleetTelemetrySample] = field(default_factory=list)
    events: list[OperationalEvent] = field(default_factory=list)
    arrived: bool = False


@dataclass(slots=True)
class ConcurrentFleetResult:
    shipments: list[ActiveConcurrentShipment] = field(default_factory=list)

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


def _advance_if_positive(
    context: SimulationContext,
    seconds: float,
) -> None:
    """Advance only when the resulting timedelta is strictly positive."""
    if seconds < 0:
        raise ValueError("seconds cannot be negative")

    delta = timedelta(seconds=seconds)

    if delta > timedelta(0):
        context.advance(delta)


def initialize_concurrent_shipments(
    *,
    context: SimulationContext,
    plans: list[ConcurrentShipmentPlan],
    vehicles: list[VehicleState],
    warehouses: dict[int, WarehouseState],
    reserve_threshold_pct: float = 15.0,
) -> list[ActiveConcurrentShipment]:
    if not plans:
        raise ValueError("plans cannot be empty")

    used_vehicle_ids: set[int] = set()
    active: list[ActiveConcurrentShipment] = []

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
        reserve_vehicle(vehicle, plan.shipment_id)
        begin_loading(vehicle)
        depart(shipment, context.now())
        begin_transit(vehicle)

        active.append(
            ActiveConcurrentShipment(
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

    return active



@dataclass(slots=True, frozen=True)
class ConcurrentTickResult:
    sample: TimedFleetTelemetrySample
    events: tuple[OperationalEvent, ...]
    arrived: bool


def tick_concurrent_shipment(
    *,
    item: ActiveConcurrentShipment,
    now: datetime,
    movement_interval_seconds: float = 60.0,
    base_consumption_pct_per_100km: float = 1.0,
    eta_event_threshold_min: float = 5.0,
    eta_cause_code: str | None = None,
    cargo_temp_c: float | None = None,
) -> ConcurrentTickResult:
    """Advance one active shipment by exactly one movement tick.

    This is the incremental counterpart to ``run_concurrent_fleet`` and is
    intended for wall-clock/live execution. It mutates only the supplied
    active shipment and never advances a SimulationContext or loops to arrival.
    """
    if movement_interval_seconds <= 0:
        raise ValueError("movement_interval_seconds must be positive")
    if item.arrived:
        raise ValueError("cannot tick an arrived shipment")

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

    emitted: list[OperationalEvent] = []
    previous_eta = item.shipment.estimated_arrival
    eta_result = calculate_eta(
        now=now,
        shipment=item.shipment,
        route_state=item.route_state,
        vehicle_profile=item.vehicle.profile,
    )
    apply_eta(item.shipment, eta_result)

    eta_event = maybe_make_eta_updated_event(
        time=now,
        shipment=item.shipment,
        vehicle=item.vehicle,
        previous_eta=previous_eta,
        new_eta=item.shipment.estimated_arrival,
        threshold_minutes=eta_event_threshold_min,
        cause_code=eta_cause_code,
    )
    if eta_event is not None:
        item.events.append(eta_event)
        emitted.append(eta_event)

    # In live mode the persisted observation time is the wall-clock tick time.
    # We do not write ``now + elapsed`` because that would create future rows.
    sample = TimedFleetTelemetrySample(
        time=now,
        row=make_fleet_telemetry_row(
            vehicle=item.vehicle,
            shipment=item.shipment,
            origin_lat=item.origin.profile.lat,
            origin_lon=item.origin.profile.lon,
            destination_lat=item.destination.profile.lat,
            destination_lon=item.destination.profile.lon,
            cargo_temp_c=cargo_temp_c,
        ),
    )
    item.telemetry_samples.append(sample)

    if item.shipment.route_progress_pct >= 100.0:
        item.arrived = True
        arrive(item.shipment, now)
        begin_unloading(
            item.vehicle,
            warehouse_id=item.destination.profile.warehouse_id,
        )
        arrival_event = make_arrival_event(
            time=now,
            shipment=item.shipment,
            vehicle=item.vehicle,
        )
        item.events.append(arrival_event)
        emitted.append(arrival_event)

    return ConcurrentTickResult(
        sample=sample,
        events=tuple(emitted),
        arrived=item.arrived,
    )

def run_concurrent_fleet(
    *,
    context: SimulationContext,
    plans: list[ConcurrentShipmentPlan],
    vehicles: list[VehicleState],
    warehouses: dict[int, WarehouseState],
    movement_interval_seconds: float = 600.0,
    base_consumption_pct_per_100km: float = 1.0,
    eta_event_threshold_min: float = 5.0,
) -> ConcurrentFleetResult:
    """Run multiple vehicles on one authoritative simulation clock."""
    if movement_interval_seconds <= 0:
        raise ValueError("movement_interval_seconds must be positive")

    active = initialize_concurrent_shipments(
        context=context,
        plans=plans,
        vehicles=vehicles,
        warehouses=warehouses,
    )

    while any(not item.arrived for item in active):
        cycle_start = context.now()
        cycle_elapsed = 0.0
        arrivals_this_cycle: list[
            tuple[ActiveConcurrentShipment, datetime]
        ] = []

        for item in active:
            if item.arrived:
                continue

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
            cycle_elapsed = max(cycle_elapsed, tick.elapsed_seconds)

            previous_eta = item.shipment.estimated_arrival
            eta_result = calculate_eta(
                now=cycle_start,
                shipment=item.shipment,
                route_state=item.route_state,
                vehicle_profile=item.vehicle.profile,
            )
            apply_eta(item.shipment, eta_result)

            eta_event = maybe_make_eta_updated_event(
                time=cycle_start,
                shipment=item.shipment,
                vehicle=item.vehicle,
                previous_eta=previous_eta,
                new_eta=item.shipment.estimated_arrival,
                threshold_minutes=eta_event_threshold_min,
            )
            if eta_event is not None:
                item.events.append(eta_event)

            sample_time = cycle_start + timedelta(
                seconds=tick.elapsed_seconds
            )

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

            if item.shipment.route_progress_pct >= 100.0:
                item.arrived = True
                arrivals_this_cycle.append((item, sample_time))

        for item, arrival_time in arrivals_this_cycle:
            arrive(item.shipment, arrival_time)
            begin_unloading(
                item.vehicle,
                warehouse_id=item.destination.profile.warehouse_id,
            )
            item.events.append(
                make_arrival_event(
                    time=arrival_time,
                    shipment=item.shipment,
                    vehicle=item.vehicle,
                )
            )

        if cycle_elapsed <= 0:
            break

        _advance_if_positive(context, cycle_elapsed)

    if any(not item.arrived for item in active):
        raise RuntimeError(
            "concurrent simulation stopped before all active shipments arrived"
        )

    return ConcurrentFleetResult(shipments=active)
