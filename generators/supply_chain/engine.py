"""End-to-end simulation engine for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .config import DEFAULT_CONFIG, SimulationConfig
from .context import SimulationContext
from .eta import apply_eta, calculate_eta
from .lifecycle import arrive, deliver, depart, mark_ready
from .events import (
    make_arrival_event,
    make_delivery_event,
    make_departure_event,
    maybe_make_eta_updated_event,
)
from .models import (
    CargoProfile,
    Priority,
    RouteProfile,
    RouteState,
    Shipment,
    OperationalEvent,
    VehicleState,
    WarehouseState,
)
from .movement import movement_tick
from .scheduler import (
    choose_vehicle,
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
from .warehouses import (
    calculate_loading_dwell,
    calculate_unloading_dwell,
    priority_rule_for,
)



def _advance_if_positive(
    context: SimulationContext,
    *,
    seconds: float = 0.0,
    minutes: float = 0.0,
) -> None:
    """Advance simulation time only when the requested duration is positive."""
    if seconds < 0 or minutes < 0:
        raise ValueError("simulation duration cannot be negative")

    delta = timedelta(seconds=seconds, minutes=minutes)

    if delta > timedelta(0):
        context.advance(delta)


@dataclass(slots=True)
class ShipmentExecutionResult:
    """Summary of one fully executed shipment."""

    shipment: Shipment
    vehicle_id: int
    origin_warehouse_id: int
    destination_warehouse_id: int
    distance_travelled_km: float
    fuel_used_pct: float
    final_odometer_km: float
    movement_ticks: int
    telemetry_samples: list[TimedFleetTelemetrySample] = field(default_factory=list)
    events: list[OperationalEvent] = field(default_factory=list)


def execute_single_shipment(
    *,
    context: SimulationContext,
    route: RouteProfile,
    route_state: RouteState,
    vehicles: list[VehicleState],
    origin_warehouse: WarehouseState,
    destination_warehouse: WarehouseState,
    cargo: CargoProfile,
    priority: Priority = Priority.STANDARD,
    shipment_id: int = 1,
    config: SimulationConfig = DEFAULT_CONFIG,
    base_consumption_pct_per_100km: float = 4.0,
    movement_interval_seconds: float = 600.0,
) -> ShipmentExecutionResult:
    """Execute one shipment through the v3 lifecycle with telemetry emission."""
    config.validate()

    if movement_interval_seconds <= 0:
        raise ValueError("movement_interval_seconds must be positive")

    if route.origin_wh_id != origin_warehouse.profile.warehouse_id:
        raise ValueError("route origin does not match origin warehouse")

    if route.dest_wh_id != destination_warehouse.profile.warehouse_id:
        raise ValueError("route destination does not match destination warehouse")

    vehicle = choose_vehicle(
        vehicles,
        cargo=cargo,
        origin_warehouse_id=route.origin_wh_id,
        reserve_threshold_pct=config.fuel_reserve_threshold_pct,
    )
    if vehicle is None:
        raise ValueError("no eligible vehicle available for shipment")

    validate_shipment_compatibility(
        vehicle=vehicle,
        cargo=cargo,
        origin_warehouse=origin_warehouse,
        destination_warehouse=destination_warehouse,
        reserve_threshold_pct=config.fuel_reserve_threshold_pct,
    )

    scheduled_departure = context.now()
    planning_buffer = priority_planning_buffer_minutes(priority)
    scheduled_arrival = scheduled_arrival_from_route(
        scheduled_departure=scheduled_departure,
        route=route,
        planning_buffer_minutes=planning_buffer,
    )

    shipment = Shipment(
        shipment_id=shipment_id,
        run_id=context.run_id,
        vehicle_id=vehicle.profile.vehicle_id,
        route_id=route.route_id,
        origin_wh_id=route.origin_wh_id,
        dest_wh_id=route.dest_wh_id,
        cargo_type=cargo.cargo_type,
        priority=priority,
        scheduled_departure=scheduled_departure,
        scheduled_arrival=scheduled_arrival,
        estimated_arrival=scheduled_arrival,
    )

    mark_ready(shipment, context.now())
    reserve_vehicle(vehicle, shipment_id=shipment_id)
    begin_loading(vehicle)

    priority_rule = priority_rule_for(
        priority,
        standard=config.standard_priority,
        expedited=config.expedited_priority,
        critical=config.critical_priority,
    )

    loading = calculate_loading_dwell(
        warehouse_state=origin_warehouse,
        cargo_profile=cargo,
        priority_rule=priority_rule,
    )
    _advance_if_positive(context, minutes=loading.total_minutes)

    starting_fuel = vehicle.fuel_level_pct
    total_distance = 0.0
    tick_count = 0
    telemetry_samples: list[TimedFleetTelemetrySample] = []
    events: list[OperationalEvent] = []

    depart(shipment, context.now())
    begin_transit(vehicle)
    events.append(
        make_departure_event(
            time=context.now(),
            shipment=shipment,
            vehicle=vehicle,
        )
    )

    while shipment.route_progress_pct < 100.0:
        tick = movement_tick(
            vehicle=vehicle,
            route_state=route_state,
            elapsed_seconds=movement_interval_seconds,
            current_progress_pct=shipment.route_progress_pct,
            origin_lat=origin_warehouse.profile.lat,
            origin_lon=origin_warehouse.profile.lon,
            destination_lat=destination_warehouse.profile.lat,
            destination_lon=destination_warehouse.profile.lon,
            base_consumption_pct_per_100km=base_consumption_pct_per_100km,
        )

        shipment.route_progress_pct = tick.route_progress_pct
        total_distance += tick.distance_km
        tick_count += 1

        previous_eta = shipment.estimated_arrival

        eta_result = calculate_eta(
            now=context.now(),
            shipment=shipment,
            route_state=route_state,
            vehicle_profile=vehicle.profile,
        )
        apply_eta(shipment, eta_result)

        eta_event = maybe_make_eta_updated_event(
            time=context.now(),
            shipment=shipment,
            vehicle=vehicle,
            previous_eta=previous_eta,
            new_eta=shipment.estimated_arrival,
            threshold_minutes=config.eta_event_threshold_min,
        )
        if eta_event is not None:
            events.append(eta_event)

        telemetry_samples.append(
            TimedFleetTelemetrySample(
                time=context.now(),
                row=make_fleet_telemetry_row(
                    vehicle=vehicle,
                    shipment=shipment,
                    origin_lat=origin_warehouse.profile.lat,
                    origin_lon=origin_warehouse.profile.lon,
                    destination_lat=destination_warehouse.profile.lat,
                    destination_lon=destination_warehouse.profile.lon,
                ),
            )
        )

        _advance_if_positive(context, seconds=tick.elapsed_seconds)

    arrive(shipment, context.now())
    begin_unloading(
        vehicle,
        warehouse_id=destination_warehouse.profile.warehouse_id,
    )
    events.append(
        make_arrival_event(
            time=context.now(),
            shipment=shipment,
            vehicle=vehicle,
        )
    )

    telemetry_samples.append(
        TimedFleetTelemetrySample(
            time=context.now(),
            row=make_fleet_telemetry_row(
                vehicle=vehicle,
                shipment=shipment,
                origin_lat=origin_warehouse.profile.lat,
                origin_lon=origin_warehouse.profile.lon,
                destination_lat=destination_warehouse.profile.lat,
                destination_lon=destination_warehouse.profile.lon,
            ),
        )
    )

    unloading = calculate_unloading_dwell(
        warehouse_state=destination_warehouse,
        cargo_profile=cargo,
        priority_rule=priority_rule,
    )
    _advance_if_positive(context, minutes=unloading.total_minutes)

    deliver(shipment, context.now())
    events.append(
        make_delivery_event(
            time=context.now(),
            shipment=shipment,
            vehicle=vehicle,
        )
    )
    begin_turnaround(vehicle)
    release_vehicle(vehicle)

    shipment.validate_temporal_integrity()
    vehicle.validate()

    return ShipmentExecutionResult(
        shipment=shipment,
        vehicle_id=vehicle.profile.vehicle_id,
        origin_warehouse_id=route.origin_wh_id,
        destination_warehouse_id=route.dest_wh_id,
        distance_travelled_km=total_distance,
        fuel_used_pct=starting_fuel - vehicle.fuel_level_pct,
        final_odometer_km=vehicle.odometer_km,
        movement_ticks=tick_count,
        telemetry_samples=telemetry_samples,
        events=events,
    )
