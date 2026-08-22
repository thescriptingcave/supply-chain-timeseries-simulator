"""Concurrent fleet execution with shared warehouse contention.

This integration layer keeps the stable concurrent movement core separate while
adding finite loading/unloading capacity, queue-delayed departures, queue-delayed
delivery completion, and warehouse operational telemetry.

It models one concurrent "wave" of shipments. Vehicle reuse across waves comes
later in the full generator orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import DEFAULT_CONFIG, SimulationConfig
from .context import SimulationContext
from .eta import apply_eta, calculate_eta
from .events import (
    make_arrival_event,
    make_delivery_event,
    make_departure_event,
    maybe_make_eta_updated_event,
)
from .lifecycle import arrive, deliver, depart, mark_ready
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
    begin_turnaround,
    begin_unloading,
    release_vehicle,
    reserve_vehicle,
)
from .warehouse_contention import (
    TimedWarehouseOperationSample,
    WarehouseOperation,
    request_operation,
    run_warehouse_contention,
)
from .warehouses import (
    calculate_loading_dwell,
    calculate_unloading_dwell,
    priority_rule_for,
)


@dataclass(slots=True, frozen=True)
class ContendedShipmentPlan:
    shipment_id: int
    vehicle_id: int
    route: RouteProfile
    cargo: CargoProfile
    priority: Priority = Priority.STANDARD


@dataclass(slots=True)
class ContendedShipmentExecution:
    shipment: Shipment
    vehicle: VehicleState
    route_state: RouteState
    origin: WarehouseState
    destination: WarehouseState
    cargo: CargoProfile
    telemetry_samples: list[TimedFleetTelemetrySample] = field(default_factory=list)
    events: list[OperationalEvent] = field(default_factory=list)


@dataclass(slots=True)
class ConcurrentContentionResult:
    shipments: list[ContendedShipmentExecution] = field(default_factory=list)
    warehouse_samples: list[TimedWarehouseOperationSample] = field(default_factory=list)

    @property
    def fleet_telemetry_rows(self) -> int:
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


def _priority_rule(
    priority: Priority,
    config: SimulationConfig,
):
    return priority_rule_for(
        priority,
        standard=config.standard_priority,
        expedited=config.expedited_priority,
        critical=config.critical_priority,
    )


def _build_loading_operations(
    *,
    start_time: datetime,
    executions: list[ContendedShipmentExecution],
    config: SimulationConfig,
) -> list[WarehouseOperation]:
    operations: list[WarehouseOperation] = []

    for item in executions:
        dwell = calculate_loading_dwell(
            warehouse_state=item.origin,
            cargo_profile=item.cargo,
            priority_rule=_priority_rule(item.shipment.priority, config),
        )
        operations.append(
            request_operation(
                shipment=item.shipment,
                vehicle=item.vehicle,
                warehouse=item.origin,
                operation_type="LOADING",
                requested_at=start_time,
                duration_minutes=dwell.total_minutes,
            )
        )

    return operations


def _build_unloading_operations(
    *,
    executions: list[ContendedShipmentExecution],
    config: SimulationConfig,
) -> list[WarehouseOperation]:
    operations: list[WarehouseOperation] = []

    for item in executions:
        if item.shipment.actual_arrival is None:
            raise RuntimeError("cannot schedule unloading before arrival")

        dwell = calculate_unloading_dwell(
            warehouse_state=item.destination,
            cargo_profile=item.cargo,
            priority_rule=_priority_rule(item.shipment.priority, config),
        )
        operations.append(
            request_operation(
                shipment=item.shipment,
                vehicle=item.vehicle,
                warehouse=item.destination,
                operation_type="UNLOADING",
                requested_at=item.shipment.actual_arrival,
                duration_minutes=dwell.total_minutes,
            )
        )

    return operations


def _loading_completion_by_shipment(
    operations: list[WarehouseOperation],
) -> dict[int, datetime]:
    result: dict[int, datetime] = {}
    for operation in operations:
        if operation.completed_at is None:
            raise RuntimeError("loading operation did not complete")
        result[operation.shipment.shipment_id] = operation.completed_at
    return result


def run_concurrent_fleet_with_contention(
    *,
    context: SimulationContext,
    plans: list[ContendedShipmentPlan],
    vehicles: list[VehicleState],
    warehouses: dict[int, WarehouseState],
    config: SimulationConfig = DEFAULT_CONFIG,
    movement_interval_seconds: float = 600.0,
    warehouse_tick_seconds: float = 60.0,
    base_consumption_pct_per_100km: float = 1.0,
) -> ConcurrentContentionResult:
    """Execute one concurrent shipment wave with shared warehouse resources."""
    config.validate()

    if not plans:
        raise ValueError("plans cannot be empty")
    if movement_interval_seconds <= 0:
        raise ValueError("movement_interval_seconds must be positive")
    if warehouse_tick_seconds <= 0:
        raise ValueError("warehouse_tick_seconds must be positive")

    used_vehicle_ids: set[int] = set()
    executions: list[ContendedShipmentExecution] = []
    start_time = context.now()

    # Build shipment/domain state without departing vehicles yet.
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
            reserve_threshold_pct=config.fuel_reserve_threshold_pct,
        )

        scheduled_arrival = scheduled_arrival_from_route(
            scheduled_departure=start_time,
            route=plan.route,
            planning_buffer_minutes=priority_planning_buffer_minutes(plan.priority),
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
            scheduled_departure=start_time,
            scheduled_arrival=scheduled_arrival,
            estimated_arrival=scheduled_arrival,
        )

        mark_ready(shipment, start_time)
        reserve_vehicle(vehicle, plan.shipment_id)
        begin_loading(vehicle)

        executions.append(
            ContendedShipmentExecution(
                shipment=shipment,
                vehicle=vehicle,
                route_state=RouteState(profile=plan.route),
                origin=origin,
                destination=destination,
                cargo=plan.cargo,
            )
        )

    # Shared loading contention determines the actual departure time for each
    # shipment. Multiple warehouses are handled by one contention run.
    loading_ops = _build_loading_operations(
        start_time=start_time,
        executions=executions,
        config=config,
    )
    loading_result = run_warehouse_contention(
        operations=loading_ops,
        start_time=start_time,
        tick_seconds=warehouse_tick_seconds,
    )
    departure_times = _loading_completion_by_shipment(loading_result.operations)

    # Concurrent movement with staggered departures.
    arrived_ids: set[int] = set()

    while len(arrived_ids) < len(executions):
        now = context.now()
        cycle_elapsed = movement_interval_seconds
        any_active = False
        next_departure: datetime | None = None

        for item in executions:
            shipment_id = item.shipment.shipment_id

            if shipment_id in arrived_ids:
                continue

            departure_time = departure_times[shipment_id]

            if item.shipment.actual_departure is None:
                if now < departure_time:
                    if next_departure is None or departure_time < next_departure:
                        next_departure = departure_time
                    continue

                depart(item.shipment, departure_time)
                begin_transit(item.vehicle)
                item.events.append(
                    make_departure_event(
                        time=departure_time,
                        shipment=item.shipment,
                        vehicle=item.vehicle,
                    )
                )

            any_active = True

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
                threshold_minutes=config.eta_event_threshold_min,
            )
            if eta_event is not None:
                item.events.append(eta_event)

            sample_time = now + timedelta(seconds=tick.elapsed_seconds)
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
                arrived_ids.add(shipment_id)

        if len(arrived_ids) == len(executions):
            break

        if any_active:
            delta = timedelta(seconds=cycle_elapsed)
            if delta > timedelta(0):
                context.advance(delta)
            continue

        if next_departure is None:
            raise RuntimeError("no active shipment and no future departure")

        delta = next_departure - context.now()
        if delta > timedelta(0):
            context.advance(delta)

    # Shared unloading contention determines delivery completion.
    unloading_ops = _build_unloading_operations(
        executions=executions,
        config=config,
    )
    unloading_start = min(
        operation.requested_at
        for operation in unloading_ops
    )
    unloading_result = run_warehouse_contention(
        operations=unloading_ops,
        start_time=unloading_start,
        tick_seconds=warehouse_tick_seconds,
    )

    unloading_by_shipment = {
        operation.shipment.shipment_id: operation
        for operation in unloading_result.operations
    }

    for item in executions:
        operation = unloading_by_shipment[item.shipment.shipment_id]
        if operation.completed_at is None:
            raise RuntimeError("unloading operation did not complete")

        deliver(item.shipment, operation.completed_at)
        item.events.append(
            make_delivery_event(
                time=operation.completed_at,
                shipment=item.shipment,
                vehicle=item.vehicle,
            )
        )
        begin_turnaround(item.vehicle)
        release_vehicle(item.vehicle)

    return ConcurrentContentionResult(
        shipments=executions,
        warehouse_samples=(
            loading_result.telemetry_samples
            + unloading_result.telemetry_samples
        ),
    )
