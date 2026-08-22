"""Shipment execution with state-driven refueling for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .context import SimulationContext
from .eta import apply_eta, calculate_eta
from .events import (
    make_arrival_event,
    make_departure_event,
    maybe_make_eta_updated_event,
)
from .fuel_stop import (
    FuelStopPolicy,
    make_fuel_stop_event,
    perform_refuel,
    should_refuel,
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
from .vehicles import begin_loading, begin_transit, begin_unloading, reserve_vehicle


@dataclass(slots=True, frozen=True)
class FuelStopShipmentPlan:
    shipment_id: int
    vehicle_id: int
    route: RouteProfile
    cargo: CargoProfile
    priority: Priority = Priority.STANDARD


@dataclass(slots=True)
class FuelStopShipmentResult:
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



def _projected_fuel_after_tick(
    *,
    vehicle: VehicleState,
    route_state: RouteState,
    movement_interval_seconds: float,
    base_consumption_pct_per_100km: float,
) -> float:
    """Estimate fuel after the next movement interval.

    This uses the current effective target speed and the same distance-based
    fuel model used by movement. It lets the engine refuel *before* a tick
    would cross the policy threshold or exhaust available fuel.
    """
    if movement_interval_seconds <= 0:
        raise ValueError("movement_interval_seconds must be positive")
    if base_consumption_pct_per_100km < 0:
        raise ValueError("base_consumption_pct_per_100km cannot be negative")

    # The movement module ultimately applies speed derived from RouteState and
    # VehicleProfile. For the fuel-stop gate we only need a conservative
    # estimate of the next interval's consumption. Vehicle speed may be zero
    # before the first movement tick, so use the route nominal speed adjusted
    # by the route/vehicle factors already represented in state/profile.
    speed_kmh = (
        route_state.profile.nominal_speed_kmh
        * route_state.traffic_factor
        * route_state.weather_factor
        * route_state.temporary_speed_factor
        * vehicle.profile.cruise_speed_factor
    )
    speed_kmh = max(
        route_state.profile.minimum_speed_kmh,
        min(route_state.profile.maximum_speed_kmh, speed_kmh),
    )

    distance_km = speed_kmh * (movement_interval_seconds / 3600.0)
    consumption_pct = (
        distance_km / 100.0
    ) * base_consumption_pct_per_100km * vehicle.profile.fuel_efficiency_factor

    return vehicle.fuel_level_pct - consumption_pct


def _needs_refuel_before_next_tick(
    *,
    vehicle: VehicleState,
    route_state: RouteState,
    policy: FuelStopPolicy,
    movement_interval_seconds: float,
    base_consumption_pct_per_100km: float,
) -> bool:
    """Return True when the next movement tick would cross the fuel trigger."""
    if should_refuel(vehicle, policy):
        return True

    projected = _projected_fuel_after_tick(
        vehicle=vehicle,
        route_state=route_state,
        movement_interval_seconds=movement_interval_seconds,
        base_consumption_pct_per_100km=base_consumption_pct_per_100km,
    )

    return projected <= policy.trigger_pct



def run_fuel_stop_shipment(
    *,
    context: SimulationContext,
    plan: FuelStopShipmentPlan,
    vehicle: VehicleState,
    origin: WarehouseState,
    destination: WarehouseState,
    policy: FuelStopPolicy,
    movement_interval_seconds: float = 600.0,
    base_consumption_pct_per_100km: float = 1.0,
    eta_event_threshold_min: float = 1.0,
) -> FuelStopShipmentResult:
    """Run one shipment and refuel once when fuel falls below policy threshold."""
    policy.validate()

    validate_shipment_compatibility(
        vehicle=vehicle,
        cargo=plan.cargo,
        origin_warehouse=origin,
        destination_warehouse=destination,
        # Scheduler compatibility requires a valid reserve threshold in (0, 100).
        # Fuel-stop behavior is governed separately by FuelStopPolicy below, so
        # use a minimal compatibility reserve that does not preempt the state-
        # driven refuel trigger.
        reserve_threshold_pct=1.0,
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
    events: list[OperationalEvent] = [
        make_departure_event(
            time=context.now(),
            shipment=shipment,
            vehicle=vehicle,
        )
    ]
    samples: list[TimedFleetTelemetrySample] = []

    refueled = False

    while shipment.actual_arrival is None:
        now = context.now()

        if (
            not refueled
            and _needs_refuel_before_next_tick(
                vehicle=vehicle,
                route_state=route_state,
                policy=policy,
                movement_interval_seconds=movement_interval_seconds,
                base_consumption_pct_per_100km=base_consumption_pct_per_100km,
            )
        ):
            stop = perform_refuel(
                now=now,
                vehicle=vehicle,
                policy=policy,
                allow_preemptive=True,
            )
            refueled = True

            events.append(
                make_fuel_stop_event(
                    event_type="FUEL_STOP_STARTED",
                    time=stop.start_time,
                    stop=stop,
                    shipment=shipment,
                    vehicle=vehicle,
                )
            )

            previous_eta = shipment.estimated_arrival
            shipment.estimated_arrival = max(
                previous_eta,
                stop.end_time
                + timedelta(
                    minutes=calculate_eta(
                        now=stop.end_time,
                        shipment=shipment,
                        route_state=route_state,
                        vehicle_profile=vehicle.profile,
                    ).remaining_travel_minutes
                ),
            )

            eta_event = maybe_make_eta_updated_event(
                time=stop.start_time,
                shipment=shipment,
                vehicle=vehicle,
                previous_eta=previous_eta,
                new_eta=shipment.estimated_arrival,
                threshold_minutes=eta_event_threshold_min,
                cause_code="LOW_FUEL_REFUEL",
            )
            if eta_event is not None:
                events.append(eta_event)

            original_speed = vehicle.speed_kmh
            vehicle.speed_kmh = 0.0
            _append_or_replace(
                samples,
                TimedFleetTelemetrySample(
                    time=stop.start_time,
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
            vehicle.speed_kmh = original_speed

            context.advance(stop.end_time - stop.start_time)

            events.append(
                make_fuel_stop_event(
                    event_type="FUEL_STOP_ENDED",
                    time=stop.end_time,
                    stop=stop,
                    shipment=shipment,
                    vehicle=vehicle,
                )
            )
            continue

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
            raise RuntimeError("fuel-stop simulation made no forward progress")
        context.advance(delta)

    return FuelStopShipmentResult(
        shipment=shipment,
        vehicle=vehicle,
        route_state=route_state,
        telemetry_samples=samples,
        events=events,
    )
