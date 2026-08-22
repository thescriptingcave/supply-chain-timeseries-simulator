#!/usr/bin/env python3
"""True wall-clock Supply Chain V3 live streamer with cadence instrumentation."""

from __future__ import annotations

import argparse
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter

import psycopg2

from generators.supply_chain.concurrent import (
    ActiveConcurrentShipment,
    ConcurrentShipmentPlan,
    initialize_concurrent_shipments,
    tick_concurrent_shipment,
)
from generators.supply_chain.context import SimulationContext
from generators.supply_chain.events import maybe_make_eta_updated_event
from generators.supply_chain.disruptions import (
    AppliedDisruption,
    Disruption,
    DisruptionType,
    apply_traffic_disruption,
    apply_weather_disruption,
    clear_traffic_disruption,
    clear_weather_disruption,
    make_disruption_event,
    traffic_disruption,
    weather_disruption,
)
from generators.supply_chain.db_writer import SupplyChainWriter
from generators.supply_chain.models import (
    CargoProfile,
    RouteProfile,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.persistence import SimulationRunRecord
from generators.supply_chain.telemetry import (
    TimedFleetTelemetrySample,
    make_fleet_telemetry_row,
)
from generators.supply_chain.vehicles import begin_turnaround, refuel, release_vehicle
from generators.supply_chain.vehicle_scheduler import (
    initialize_vehicle_availability,
    mark_vehicle_available,
)
from scripts.streaming_common import ShutdownFlag


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


@dataclass(slots=True)
class LiveActive:
    item: ActiveConcurrentShipment
    next_tick_mono: float
    traffic: Disruption | None = None
    traffic_started: bool = False
    traffic_ended: bool = False
    weather: Disruption | None = None
    weather_started: bool = False
    weather_ended: bool = False
    mechanical: Disruption | None = None
    mechanical_started: bool = False
    mechanical_ended: bool = False
    fuel_demo: bool = False
    fuel_trigger_pct: float = 25.0
    fuel_refuel_to_pct: float = 90.0
    fuel_stop_duration_seconds: int = 120
    fuel_stop_pending: bool = False
    fuel_stop_active: bool = False
    fuel_stop_completed: bool = False
    fuel_stop_started_at: datetime | None = None
    fuel_stop_end_mono: float | None = None
    fuel_before_pct: float | None = None
    reefer_demo: bool = False
    reefer_start_delay_seconds: int = 120
    reefer_duration_seconds: int = 120
    reefer_excursion_temp_c: float = 12.0
    reefer_recovery_temp_c: float = 4.0
    reefer_started: bool = False
    reefer_ended: bool = False
    reefer_started_at: datetime | None = None
    reefer_start_mono: float | None = None
    reefer_end_mono: float | None = None
    current_cargo_temp_c: float | None = None


@dataclass(slots=True)
class TimingStats:
    shipment_start_ms: float = 0.0
    tick_compute_ms: float = 0.0
    telemetry_insert_ms: float = 0.0
    event_insert_ms: float = 0.0
    shipment_update_ms: float = 0.0
    loop_ms: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shipment-interval", type=int, default=300)
    parser.add_argument("--movement-interval", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--traffic-demo",
        action="store_true",
        help="Inject one deterministic live traffic event into the first shipment.",
    )
    parser.add_argument(
        "--traffic-start-delay",
        type=int,
        default=120,
        help="Seconds after departure before demo congestion begins.",
    )
    parser.add_argument(
        "--traffic-duration",
        type=int,
        default=120,
        help="Seconds the demo congestion remains active.",
    )
    parser.add_argument(
        "--traffic-speed-factor",
        type=float,
        default=0.5,
        help="Multiplicative speed factor for the demo congestion.",
    )
    parser.add_argument(
        "--weather-demo",
        action="store_true",
        help="Inject one deterministic live weather event into the first shipment.",
    )
    parser.add_argument(
        "--weather-start-delay",
        type=int,
        default=120,
        help="Seconds after departure before demo weather begins.",
    )
    parser.add_argument(
        "--weather-duration",
        type=int,
        default=120,
        help="Seconds the demo weather event remains active.",
    )
    parser.add_argument(
        "--weather-speed-factor",
        type=float,
        default=0.7,
        help="Multiplicative route weather factor for the demo event.",
    )
    parser.add_argument(
        "--mechanical-demo",
        action="store_true",
        help="Inject one deterministic live mechanical breakdown into the first shipment.",
    )
    parser.add_argument(
        "--mechanical-start-delay",
        type=int,
        default=120,
        help="Seconds after departure before the demo breakdown begins.",
    )
    parser.add_argument(
        "--mechanical-duration",
        type=int,
        default=120,
        help="Seconds the demo vehicle remains stopped.",
    )
    parser.add_argument(
        "--fuel-demo",
        action="store_true",
        help="Run one deterministic threshold-driven live fuel stop on the first shipment.",
    )
    parser.add_argument(
        "--fuel-trigger-pct",
        type=float,
        default=25.0,
        help="Fuel percentage at or below which the demo stop becomes pending.",
    )
    parser.add_argument(
        "--fuel-refuel-to-pct",
        type=float,
        default=90.0,
        help="Target fuel percentage applied when the live refuel begins.",
    )
    parser.add_argument(
        "--fuel-stop-duration",
        type=int,
        default=120,
        help="Seconds the vehicle remains stopped while refueling.",
    )
    parser.add_argument(
        "--fuel-demo-start-pct",
        type=float,
        default=25.02,
        help="Initial fuel for the first demo vehicle so threshold crossing happens quickly.",
    )
    parser.add_argument(
        "--reefer-demo",
        action="store_true",
        help="Inject one deterministic live reefer temperature excursion into the first shipment.",
    )
    parser.add_argument(
        "--reefer-start-delay",
        type=int,
        default=120,
        help="Seconds after departure before the reefer excursion begins.",
    )
    parser.add_argument(
        "--reefer-duration",
        type=int,
        default=120,
        help="Seconds the cargo temperature remains above range.",
    )
    parser.add_argument(
        "--reefer-excursion-temp",
        type=float,
        default=12.0,
        help="Cargo temperature during the demo excursion.",
    )
    parser.add_argument(
        "--reefer-recovery-temp",
        type=float,
        default=4.0,
        help="Cargo temperature after the excursion clears.",
    )
    parser.add_argument(
        "--mixed-demo",
        action="store_true",
        help=(
            "Run one deterministic live mixed-disruption scenario: "
            "traffic, weather, mechanical, fuel, and reefer on separate shipments."
        ),
    )
    parser.add_argument(
        "--timing-log-threshold-ms",
        type=float,
        default=250.0,
        help="Print detailed timing when loop work exceeds this threshold.",
    )
    return parser.parse_args()


def load_routes(cur) -> list[RouteProfile]:
    cur.execute(
        """
        SELECT
            route_id, origin_wh_id, dest_wh_id, distance_km,
            nominal_speed_kmh, minimum_speed_kmh, maximum_speed_kmh,
            baseline_travel_min, congestion_sensitivity,
            weather_sensitivity, morning_peak_factor,
            evening_peak_factor, overnight_factor,
            demand_weight, disruption_probability
        FROM sc_routes
        WHERE active = true
        ORDER BY route_id
        """
    )
    rows = cur.fetchall()
    return [
        RouteProfile(
            route_id=r[0],
            origin_wh_id=r[1],
            dest_wh_id=r[2],
            distance_km=float(r[3]),
            nominal_speed_kmh=float(r[4]),
            minimum_speed_kmh=float(r[5]),
            maximum_speed_kmh=float(r[6]),
            baseline_travel_min=float(r[7]),
            congestion_sensitivity=float(r[8]),
            weather_sensitivity=float(r[9]),
            morning_peak_factor=float(r[10]),
            evening_peak_factor=float(r[11]),
            overnight_factor=float(r[12]),
            demand_weight=float(r[13]),
            disruption_probability=float(r[14]),
        )
        for r in rows
    ]


def load_warehouses(cur) -> dict[int, WarehouseState]:
    cur.execute(
        """
        SELECT
            warehouse_id, warehouse_name, lat, lon, timezone,
            loading_capacity, unloading_capacity,
            baseline_loading_min, baseline_unloading_min,
            congestion_sensitivity, cold_storage_capable
        FROM sc_warehouses
        ORDER BY warehouse_id
        """
    )
    return {
        r[0]: WarehouseState(
            profile=WarehouseProfile(
                warehouse_id=r[0],
                warehouse_name=r[1],
                lat=float(r[2]),
                lon=float(r[3]),
                timezone=r[4],
                loading_capacity=r[5],
                unloading_capacity=r[6],
                baseline_loading_min=float(r[7]),
                baseline_unloading_min=float(r[8]),
                congestion_sensitivity=float(r[9]),
                cold_storage_capable=r[10],
            )
        )
        for r in cur.fetchall()
    }


def load_vehicle_profiles(cur) -> list[VehicleProfile]:
    cur.execute(
        """
        SELECT
            vehicle_id, vehicle_reg, vehicle_type, max_payload_kg,
            fuel_type, fleet_operator, year_manufactured,
            fuel_efficiency_factor, reliability_factor,
            condition_factor, cruise_speed_factor,
            maintenance_risk_factor, reefer_capable
        FROM sc_vehicles
        ORDER BY vehicle_id
        """
    )
    return [
        VehicleProfile(
            vehicle_id=r[0],
            vehicle_reg=r[1],
            vehicle_type=r[2],
            max_payload_kg=float(r[3]) if r[3] is not None else None,
            fuel_type=r[4],
            fleet_operator=r[5],
            year_manufactured=r[6],
            fuel_efficiency_factor=float(r[7]),
            reliability_factor=float(r[8]),
            condition_factor=float(r[9]),
            cruise_speed_factor=float(r[10]),
            maintenance_risk_factor=float(r[11]),
            reefer_capable=r[12],
        )
        for r in cur.fetchall()
    ]


def load_general_cargo(cur) -> CargoProfile:
    cur.execute(
        """
        SELECT
            cargo_type, requires_reefer, target_temp_c,
            min_temp_c, max_temp_c, target_humidity_pct,
            handling_sensitivity, loading_time_factor
        FROM sc_cargo_profiles
        WHERE active = true
          AND requires_reefer = false
        ORDER BY cargo_type
        LIMIT 1
        """
    )
    r = cur.fetchone()
    if r is None:
        raise RuntimeError("no general cargo profile found")
    return CargoProfile(
        cargo_type=r[0],
        requires_reefer=r[1],
        target_temp_c=float(r[2]) if r[2] is not None else None,
        min_temp_c=float(r[3]) if r[3] is not None else None,
        max_temp_c=float(r[4]) if r[4] is not None else None,
        target_humidity_pct=float(r[5]) if r[5] is not None else None,
        handling_sensitivity=float(r[6]),
        loading_time_factor=float(r[7]),
    )


def initialize_vehicle_states(
    profiles: list[VehicleProfile],
    warehouses: dict[int, WarehouseState],
) -> dict[int, VehicleState]:
    warehouse_ids = sorted(warehouses)
    return {
        profile.vehicle_id: VehicleState(
            profile=profile,
            current_warehouse_id=warehouses[
                warehouse_ids[i % len(warehouse_ids)]
            ].profile.warehouse_id,
            lat=warehouses[
                warehouse_ids[i % len(warehouse_ids)]
            ].profile.lat,
            lon=warehouses[
                warehouse_ids[i % len(warehouse_ids)]
            ].profile.lon,
            fuel_level_pct=95.0,
            odometer_km=100000.0 + profile.vehicle_id * 1000.0,
        )
        for i, profile in enumerate(profiles)
    }


def update_persisted_shipment(conn, shipment) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sc_shipments
            SET
                actual_departure = %s,
                actual_arrival = %s,
                lifecycle_status = %s,
                estimated_arrival = %s,
                delivery_completed_at = %s
            WHERE shipment_id = %s
              AND run_id = %s
            """,
            (
                shipment.actual_departure,
                shipment.actual_arrival,
                shipment.lifecycle_status.value,
                shipment.estimated_arrival,
                shipment.delivery_completed_at,
                shipment.shipment_id,
                shipment.run_id,
            ),
        )
    conn.commit()


def choose_idle_vehicle_and_route(
    rng,
    vehicle_states,
    active,
    routes,
):
    active_vehicle_ids = {
        live.item.vehicle.profile.vehicle_id
        for live in active.values()
    }
    for vehicle in sorted(
        vehicle_states.values(),
        key=lambda v: v.profile.vehicle_id,
    ):
        if vehicle.profile.vehicle_id in active_vehicle_ids:
            continue
        candidates = [
            route
            for route in routes
            if route.origin_wh_id == vehicle.current_warehouse_id
        ]
        if candidates:
            return vehicle, rng.choice(candidates)
    return None


def start_live_shipment(
    *,
    now,
    run_id,
    shipment_id,
    vehicle,
    route,
    cargo,
    warehouses,
    movement_interval_seconds,
    start_mono,
):
    context = SimulationContext(
        simulation_start=now,
        simulation_end=now + timedelta(days=3),
        seed=shipment_id,
        run_id=run_id,
    )
    item = initialize_concurrent_shipments(
        context=context,
        plans=[
            ConcurrentShipmentPlan(
                shipment_id=shipment_id,
                vehicle_id=vehicle.profile.vehicle_id,
                route=route,
                cargo=cargo,
            )
        ],
        vehicles=[vehicle],
        warehouses=warehouses,
    )[0]
    return LiveActive(
        item=item,
        next_tick_mono=start_mono + movement_interval_seconds,
    )



def attach_demo_traffic(
    *,
    live: LiveActive,
    run_id: int,
    departure: datetime,
    start_delay_seconds: int,
    duration_seconds: int,
    speed_factor: float,
) -> None:
    """Attach one deterministic traffic window to a live shipment."""
    if start_delay_seconds < 0:
        raise ValueError("traffic-start-delay cannot be negative")
    if duration_seconds <= 0:
        raise ValueError("traffic-duration must be positive")
    if not 0 < speed_factor <= 1.0:
        raise ValueError("traffic-speed-factor must be in (0, 1]")

    shipment = live.item.shipment
    live.traffic = traffic_disruption(
        disruption_id=f"LIVE-TRAFFIC-{run_id}-{shipment.shipment_id}",
        start_time=departure + timedelta(seconds=start_delay_seconds),
        duration_minutes=duration_seconds / 60.0,
        speed_factor=speed_factor,
        route_id=shipment.route_id,
    )


def apply_live_traffic_before_tick(
    *,
    live: LiveActive,
    now: datetime,
) -> tuple[AppliedDisruption | None, str | None]:
    """Apply the active traffic factor and emit its start boundary once."""
    disruption = live.traffic
    if disruption is None:
        return None, None

    if (
        live.traffic_started
        and not live.traffic_ended
        and now >= disruption.end_time
    ):
        live.item.events.append(
            make_disruption_event(
                time=now,
                disruption=disruption,
                shipment=live.item.shipment,
                vehicle=live.item.vehicle,
                event_type="DISRUPTION_ENDED",
            )
        )
        live.traffic_ended = True
        return None, None

    applied = apply_traffic_disruption(
        disruption=disruption,
        now=now,
        route_state=live.item.route_state,
        vehicle=live.item.vehicle,
    )

    if applied.active and not live.traffic_started:
        live.item.events.append(
            make_disruption_event(
                time=now,
                disruption=disruption,
                shipment=live.item.shipment,
                vehicle=live.item.vehicle,
                event_type="DISRUPTION_STARTED",
            )
        )
        live.traffic_started = True

    if applied.active:
        return applied, disruption.cause_code

    return None, None


def clear_live_traffic_after_tick(
    *,
    live: LiveActive,
    applied: AppliedDisruption | None,
) -> None:
    """Restore route traffic factor after the one live movement tick."""
    if applied is not None:
        clear_traffic_disruption(
            applied=applied,
            route_state=live.item.route_state,
        )



def attach_demo_weather(
    *,
    live: LiveActive,
    run_id: int,
    departure: datetime,
    start_delay_seconds: int,
    duration_seconds: int,
    weather_factor: float,
) -> None:
    """Attach one deterministic heavy-rain window to a live shipment."""
    if start_delay_seconds < 0:
        raise ValueError("weather-start-delay cannot be negative")
    if duration_seconds <= 0:
        raise ValueError("weather-duration must be positive")
    if not 0 < weather_factor <= 1.0:
        raise ValueError("weather-speed-factor must be in (0, 1]")

    shipment = live.item.shipment
    live.weather = weather_disruption(
        disruption_id=f"LIVE-WEATHER-{run_id}-{shipment.shipment_id}",
        start_time=departure + timedelta(seconds=start_delay_seconds),
        duration_minutes=duration_seconds / 60.0,
        weather_factor=weather_factor,
        route_id=shipment.route_id,
        cause_code="HEAVY_RAIN",
    )


def apply_live_weather_before_tick(
    *,
    live: LiveActive,
    now: datetime,
) -> tuple[AppliedDisruption | None, str | None]:
    """Apply active live weather and emit start/end boundary events once."""
    disruption = live.weather
    if disruption is None:
        return None, None

    if (
        live.weather_started
        and not live.weather_ended
        and now >= disruption.end_time
    ):
        live.item.events.append(
            make_disruption_event(
                time=now,
                disruption=disruption,
                shipment=live.item.shipment,
                vehicle=live.item.vehicle,
                event_type="DISRUPTION_ENDED",
            )
        )
        live.weather_ended = True
        return None, None

    applied = apply_weather_disruption(
        disruption=disruption,
        now=now,
        route_state=live.item.route_state,
        vehicle=live.item.vehicle,
    )

    if applied.active and not live.weather_started:
        live.item.events.append(
            make_disruption_event(
                time=now,
                disruption=disruption,
                shipment=live.item.shipment,
                vehicle=live.item.vehicle,
                event_type="DISRUPTION_STARTED",
            )
        )
        live.weather_started = True

    if applied.active:
        return applied, disruption.cause_code

    return None, None


def clear_live_weather_after_tick(
    *,
    live: LiveActive,
    applied: AppliedDisruption | None,
) -> None:
    """Restore route weather factor after one live movement tick."""
    if applied is not None:
        clear_weather_disruption(
            applied=applied,
            route_state=live.item.route_state,
        )



def attach_demo_mechanical(
    *,
    live: LiveActive,
    run_id: int,
    departure: datetime,
    start_delay_seconds: int,
    duration_seconds: int,
) -> None:
    """Attach one deterministic full-stop mechanical breakdown."""
    if start_delay_seconds < 0:
        raise ValueError("mechanical-start-delay cannot be negative")
    if duration_seconds <= 0:
        raise ValueError("mechanical-duration must be positive")

    shipment = live.item.shipment
    live.mechanical = Disruption(
        disruption_id=f"LIVE-MECH-{run_id}-{shipment.shipment_id}",
        disruption_type=DisruptionType.MECHANICAL,
        cause_code="MECHANICAL_BREAKDOWN",
        severity="CRITICAL",
        start_time=departure + timedelta(seconds=start_delay_seconds),
        duration_minutes=duration_seconds / 60.0,
        # Mechanical breakdown is modeled as a stop, not a speed multiplier.
        speed_factor=1.0,
        delay_minutes=duration_seconds / 60.0,
        vehicle_id=shipment.vehicle_id,
    )


def mechanical_is_active(*, live: LiveActive, now: datetime) -> bool:
    disruption = live.mechanical
    return (
        disruption is not None
        and disruption.is_active(now)
        and disruption.affects(
            route_id=live.item.shipment.route_id,
            vehicle_id=live.item.vehicle.profile.vehicle_id,
        )
    )


def begin_live_mechanical_if_needed(
    *,
    live: LiveActive,
    now: datetime,
) -> list:
    """Emit breakdown start and one material ETA update."""
    disruption = live.mechanical
    if disruption is None or not mechanical_is_active(live=live, now=now):
        return []
    if live.mechanical_started:
        return []

    emitted = []
    live.mechanical_started = True

    start_event = make_disruption_event(
        time=now,
        disruption=disruption,
        shipment=live.item.shipment,
        vehicle=live.item.vehicle,
        event_type="DISRUPTION_STARTED",
    )
    live.item.events.append(start_event)
    emitted.append(start_event)

    previous_eta = live.item.shipment.estimated_arrival
    live.item.shipment.estimated_arrival = (
        previous_eta + timedelta(minutes=disruption.delay_minutes)
    )
    eta_event = maybe_make_eta_updated_event(
        time=now,
        shipment=live.item.shipment,
        vehicle=live.item.vehicle,
        previous_eta=previous_eta,
        new_eta=live.item.shipment.estimated_arrival,
        threshold_minutes=1.0,
        cause_code=disruption.cause_code,
    )
    if eta_event is not None:
        live.item.events.append(eta_event)
        emitted.append(eta_event)

    return emitted


def end_live_mechanical_if_needed(
    *,
    live: LiveActive,
    now: datetime,
) -> list:
    """Emit the breakdown end boundary once the stop window closes."""
    disruption = live.mechanical
    if (
        disruption is None
        or not live.mechanical_started
        or live.mechanical_ended
        or now < disruption.end_time
    ):
        return []

    event = make_disruption_event(
        time=now,
        disruption=disruption,
        shipment=live.item.shipment,
        vehicle=live.item.vehicle,
        event_type="DISRUPTION_ENDED",
    )
    live.item.events.append(event)
    live.mechanical_ended = True
    return [event]


def tick_live_mechanical_stop(
    *,
    live: LiveActive,
    now: datetime,
    movement_interval_seconds: float,
) -> TimedFleetTelemetrySample:
    """Persist one stationary observation without advancing route or odometer."""
    vehicle = live.item.vehicle
    vehicle.speed_kmh = 0.0
    vehicle.engine_rpm = 0
    vehicle.idle_time_sec += int(movement_interval_seconds)

    sample = TimedFleetTelemetrySample(
        time=now,
        row=make_fleet_telemetry_row(
            vehicle=vehicle,
            shipment=live.item.shipment,
            origin_lat=live.item.origin.profile.lat,
            origin_lon=live.item.origin.profile.lon,
            destination_lat=live.item.destination.profile.lat,
            destination_lon=live.item.destination.profile.lon,
            cargo_temp_c=live.current_cargo_temp_c,
        ),
    )
    live.item.telemetry_samples.append(sample)
    return sample



def configure_live_fuel_demo(
    *,
    live: LiveActive,
    start_fuel_pct: float,
    trigger_pct: float,
    refuel_to_pct: float,
    stop_duration_seconds: int,
) -> None:
    """Configure a threshold-driven fuel stop for one live shipment."""
    if not 0 < trigger_pct < 100:
        raise ValueError("fuel-trigger-pct must be between 0 and 100")
    if not trigger_pct < refuel_to_pct <= 100:
        raise ValueError("fuel-refuel-to-pct must be above trigger and <= 100")
    if not trigger_pct < start_fuel_pct <= 100:
        raise ValueError("fuel-demo-start-pct must be above trigger and <= 100")
    if stop_duration_seconds <= 0:
        raise ValueError("fuel-stop-duration must be positive")

    live.fuel_demo = True
    live.fuel_trigger_pct = trigger_pct
    live.fuel_refuel_to_pct = refuel_to_pct
    live.fuel_stop_duration_seconds = stop_duration_seconds
    live.item.vehicle.fuel_level_pct = start_fuel_pct


def mark_fuel_stop_pending_if_needed(*, live: LiveActive) -> bool:
    """Arm a refuel stop after normal movement crosses the reserve threshold."""
    if (
        not live.fuel_demo
        or live.fuel_stop_pending
        or live.fuel_stop_active
        or live.fuel_stop_completed
    ):
        return False

    if live.item.vehicle.fuel_level_pct <= live.fuel_trigger_pct:
        live.fuel_stop_pending = True
        return True

    return False


def _fuel_stop_event(
    *,
    live: LiveActive,
    now: datetime,
    event_type: str,
    severity: str,
):
    """Create a fuel-specific event using the existing disruption event contract."""
    duration_minutes = live.fuel_stop_duration_seconds / 60.0
    disruption = Disruption(
        disruption_id=(
            f"LIVE-FUEL-{live.item.shipment.run_id}-"
            f"{live.item.shipment.shipment_id}"
        ),
        disruption_type=DisruptionType.FUEL_STOP,
        cause_code="LOW_FUEL_REFUEL",
        severity=severity,
        start_time=live.fuel_stop_started_at or now,
        duration_minutes=duration_minutes,
        speed_factor=1.0,
        delay_minutes=duration_minutes,
        vehicle_id=live.item.vehicle.profile.vehicle_id,
    )
    event = make_disruption_event(
        time=now,
        disruption=disruption,
        shipment=live.item.shipment,
        vehicle=live.item.vehicle,
        event_type=event_type,
    )
    event.detail.update(
        {
            "fuel_before_pct": live.fuel_before_pct,
            "fuel_after_pct": live.item.vehicle.fuel_level_pct,
            "stop_duration_minutes": duration_minutes,
        }
    )
    return event


def begin_live_fuel_stop(
    *,
    live: LiveActive,
    now: datetime,
    current_mono: float,
) -> None:
    """Start refueling, raise fuel once, and apply one material ETA delay."""
    if not live.fuel_stop_pending or live.fuel_stop_active:
        return

    live.fuel_before_pct = live.item.vehicle.fuel_level_pct
    live.fuel_stop_started_at = now
    live.fuel_stop_end_mono = (
        current_mono + live.fuel_stop_duration_seconds
    )

    refuel(
        live.item.vehicle,
        target_fuel_pct=live.fuel_refuel_to_pct,
    )

    live.fuel_stop_pending = False
    live.fuel_stop_active = True

    start_event = _fuel_stop_event(
        live=live,
        now=now,
        event_type="FUEL_STOP_STARTED",
        severity="WARNING",
    )
    live.item.events.append(start_event)

    previous_eta = live.item.shipment.estimated_arrival
    live.item.shipment.estimated_arrival = (
        previous_eta
        + timedelta(seconds=live.fuel_stop_duration_seconds)
    )
    eta_event = maybe_make_eta_updated_event(
        time=now,
        shipment=live.item.shipment,
        vehicle=live.item.vehicle,
        previous_eta=previous_eta,
        new_eta=live.item.shipment.estimated_arrival,
        threshold_minutes=1.0,
        cause_code="LOW_FUEL_REFUEL",
    )
    if eta_event is not None:
        live.item.events.append(eta_event)


def end_live_fuel_stop_if_needed(
    *,
    live: LiveActive,
    now: datetime,
    current_mono: float,
) -> None:
    """End the stop once its monotonic duration has elapsed."""
    if (
        not live.fuel_stop_active
        or live.fuel_stop_end_mono is None
        or current_mono < live.fuel_stop_end_mono
    ):
        return

    end_event = _fuel_stop_event(
        live=live,
        now=now,
        event_type="FUEL_STOP_ENDED",
        severity="INFO",
    )
    live.item.events.append(end_event)
    live.fuel_stop_active = False
    live.fuel_stop_completed = True


def tick_live_fuel_stop(
    *,
    live: LiveActive,
    now: datetime,
    movement_interval_seconds: float,
) -> TimedFleetTelemetrySample:
    """Emit one stationary refuel observation without route/odometer movement."""
    vehicle = live.item.vehicle
    vehicle.speed_kmh = 0.0
    vehicle.engine_rpm = 0
    vehicle.idle_time_sec += int(movement_interval_seconds)

    sample = TimedFleetTelemetrySample(
        time=now,
        row=make_fleet_telemetry_row(
            vehicle=vehicle,
            shipment=live.item.shipment,
            origin_lat=live.item.origin.profile.lat,
            origin_lon=live.item.origin.profile.lon,
            destination_lat=live.item.destination.profile.lat,
            destination_lon=live.item.destination.profile.lon,
            cargo_temp_c=live.current_cargo_temp_c,
            at_fuel_stop=True,
        ),
    )
    live.item.telemetry_samples.append(sample)
    return sample



def configure_live_reefer_demo(
    *,
    live: LiveActive,
    current_mono: float,
    start_delay_seconds: int,
    duration_seconds: int,
    excursion_temp_c: float,
    recovery_temp_c: float,
) -> None:
    """Configure a deterministic moving reefer temperature excursion."""
    if start_delay_seconds < 0:
        raise ValueError("reefer-start-delay cannot be negative")
    if duration_seconds <= 0:
        raise ValueError("reefer-duration must be positive")

    live.reefer_demo = True
    live.reefer_start_delay_seconds = start_delay_seconds
    live.reefer_duration_seconds = duration_seconds
    live.reefer_excursion_temp_c = excursion_temp_c
    live.reefer_recovery_temp_c = recovery_temp_c
    live.reefer_start_mono = current_mono + start_delay_seconds
    live.reefer_end_mono = live.reefer_start_mono + duration_seconds
    live.current_cargo_temp_c = recovery_temp_c


def reefer_is_active(*, live: LiveActive, current_mono: float) -> bool:
    return (
        live.reefer_demo
        and live.reefer_start_mono is not None
        and live.reefer_end_mono is not None
        and live.reefer_start_mono <= current_mono < live.reefer_end_mono
    )


def _make_reefer_event(
    *,
    live: LiveActive,
    now: datetime,
    event_type: str,
    severity: str,
):
    disruption = Disruption(
        disruption_id=(
            f"LIVE-REEFER-{live.item.shipment.run_id}-"
            f"{live.item.shipment.shipment_id}"
        ),
        disruption_type=DisruptionType.REEFER,
        cause_code="REEFER_TEMP_EXCURSION",
        severity=severity,
        start_time=live.reefer_started_at or now,
        duration_minutes=live.reefer_duration_seconds / 60.0,
        speed_factor=1.0,
        delay_minutes=0.0,
        vehicle_id=live.item.vehicle.profile.vehicle_id,
    )
    event = make_disruption_event(
        time=now,
        disruption=disruption,
        shipment=live.item.shipment,
        vehicle=live.item.vehicle,
        event_type=event_type,
    )
    event.detail.update(
        {
            "cargo_temp_c": live.current_cargo_temp_c,
            "peak_temp_c": live.reefer_excursion_temp_c,
            "recovery_temp_c": live.reefer_recovery_temp_c,
            "min_temp_c": 1.0,
            "max_temp_c": 8.0,
        }
    )
    return event


def apply_live_reefer_state(
    *,
    live: LiveActive,
    now: datetime,
    current_mono: float,
) -> bool:
    """Update cargo temperature and emit start/end events once."""
    if not live.reefer_demo:
        return False

    active = reefer_is_active(live=live, current_mono=current_mono)

    if active:
        live.current_cargo_temp_c = live.reefer_excursion_temp_c
        if not live.reefer_started:
            live.reefer_started = True
            live.reefer_started_at = now
            live.item.events.append(
                _make_reefer_event(
                    live=live,
                    now=now,
                    event_type="CARGO_EXCEPTION_STARTED",
                    severity="CRITICAL",
                )
            )
        return True

    # Recovery after the active window.
    if (
        live.reefer_started
        and not live.reefer_ended
        and live.reefer_end_mono is not None
        and current_mono >= live.reefer_end_mono
    ):
        live.current_cargo_temp_c = live.reefer_recovery_temp_c
        live.reefer_ended = True
        live.item.events.append(
            _make_reefer_event(
                live=live,
                now=now,
                event_type="CARGO_EXCEPTION_ENDED",
                severity="INFO",
            )
        )
    elif not live.reefer_started:
        live.current_cargo_temp_c = live.reefer_recovery_temp_c

    return False



def finalize_live_simulation_run(
    conn,
    *,
    run_id: int,
    simulation_start: datetime,
    status: str,
) -> datetime:
    """Persist the actual wall-clock end of a true-live run."""
    ended_at = datetime.now(timezone.utc).replace(microsecond=0)

    # sc_simulation_runs requires end > start. Preserve semantic truth while
    # allowing an immediately stopped smoke run to satisfy the database check.
    if ended_at <= simulation_start:
        ended_at = simulation_start + timedelta(seconds=1)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sc_simulation_runs
            SET
                status = %s,
                simulation_end = %s
            WHERE run_id = %s
            """,
            (status, ended_at, run_id),
        )
    conn.commit()
    return ended_at


def main() -> None:
    args = parse_args()
    if args.shipment_interval <= 0 or args.movement_interval <= 0:
        raise ValueError("intervals must be positive")
    if args.traffic_start_delay < 0:
        raise ValueError("traffic-start-delay cannot be negative")
    if args.traffic_duration <= 0:
        raise ValueError("traffic-duration must be positive")
    if not 0 < args.traffic_speed_factor <= 1.0:
        raise ValueError("traffic-speed-factor must be in (0, 1]")
    if args.weather_start_delay < 0:
        raise ValueError("weather-start-delay cannot be negative")
    if args.weather_duration <= 0:
        raise ValueError("weather-duration must be positive")
    if not 0 < args.weather_speed_factor <= 1.0:
        raise ValueError("weather-speed-factor must be in (0, 1]")
    if args.mechanical_start_delay < 0:
        raise ValueError("mechanical-start-delay cannot be negative")
    if args.mechanical_duration <= 0:
        raise ValueError("mechanical-duration must be positive")
    if not 0 < args.fuel_trigger_pct < 100:
        raise ValueError("fuel-trigger-pct must be between 0 and 100")
    if not args.fuel_trigger_pct < args.fuel_refuel_to_pct <= 100:
        raise ValueError("fuel-refuel-to-pct must be above trigger and <= 100")
    if not args.fuel_trigger_pct < args.fuel_demo_start_pct <= 100:
        raise ValueError("fuel-demo-start-pct must be above trigger and <= 100")
    if args.fuel_stop_duration <= 0:
        raise ValueError("fuel-stop-duration must be positive")
    if args.reefer_start_delay < 0:
        raise ValueError("reefer-start-delay cannot be negative")
    if args.reefer_duration <= 0:
        raise ValueError("reefer-duration must be positive")

    stop = ShutdownFlag()
    stop.install("Supply Chain V3 Streamer")

    conn = psycopg2.connect(DB_URL)
    writer = SupplyChainWriter(conn, batch_size=5000)
    run_id = None

    try:
        with conn.cursor() as cur:
            routes = load_routes(cur)
            warehouses = load_warehouses(cur)
            profiles = load_vehicle_profiles(cur)
            cargo = load_general_cargo(cur)

        vehicle_states = initialize_vehicle_states(profiles, warehouses)
        now = datetime.now(timezone.utc).replace(microsecond=0)

        run_id = writer.create_simulation_run(
            SimulationRunRecord(
                generator_name="supply_chain_live",
                model_version="3.0.0",
                seed=args.seed,
                simulation_start=now,
                simulation_end=now + timedelta(days=3650),
                configuration_version="v3-live-tick-instrumented",
                status="STARTED",
                metadata_json={
                    "purpose": "true-wall-clock-live-stream",
                    "instrumented": True,
                    "shipment_interval_seconds": args.shipment_interval,
                    "movement_interval_seconds": args.movement_interval,
                    "traffic_demo": args.traffic_demo,
                    "weather_demo": args.weather_demo,
                    "mechanical_demo": args.mechanical_demo,
                    "fuel_demo": args.fuel_demo,
                    "reefer_demo": args.reefer_demo,
                    "mixed_demo": args.mixed_demo,
                },
            )
        )

        availability = initialize_vehicle_availability(
            vehicle_profiles=profiles,
            start_time=now,
        )
        rng = random.Random(args.seed)
        active = {}
        traffic_demo_assigned = False
        weather_demo_assigned = False
        mechanical_demo_assigned = False
        fuel_demo_assigned = False
        reefer_demo_assigned = False
        mixed_demo_assignment_index = 0
        next_shipment_mono = perf_counter()

        print(
            "[Supply Chain V3 Streamer] TRUE LIVE mode started "
            f"run_id={run_id} "
            "(monotonic scheduling + UTC persistence)"
        )

        previous_loop_wall = datetime.now(timezone.utc)
        previous_loop_mono = perf_counter()

        while stop.running:
            loop_start = perf_counter()
            stats = TimingStats()
            current_wall = datetime.now(timezone.utc)
            current_mono = perf_counter()

            wall_gap_s = (current_wall - previous_loop_wall).total_seconds()
            mono_gap_s = current_mono - previous_loop_mono

            # Diagnostic only: wall clock may jump because of OS/NTP correction.
            # Scheduling decisions below use monotonic time exclusively.
            if abs(wall_gap_s - mono_gap_s) > 2.0:
                print(
                    "[CLOCK ADJUSTMENT] "
                    f"wall_gap={wall_gap_s:.3f}s "
                    f"monotonic_gap={mono_gap_s:.3f}s"
                )

            previous_loop_wall = current_wall
            previous_loop_mono = current_mono

            now = current_wall.replace(microsecond=0)

            if current_mono >= next_shipment_mono:
                choice = choose_idle_vehicle_and_route(
                    rng,
                    vehicle_states,
                    active,
                    routes,
                )
                if choice is not None:
                    t0 = perf_counter()
                    vehicle, route = choice
                    shipment_id = writer.allocate_shipment_id()
                    live = start_live_shipment(
                        now=now,
                        run_id=run_id,
                        shipment_id=shipment_id,
                        vehicle=vehicle,
                        route=route,
                        cargo=cargo,
                        warehouses=warehouses,
                        movement_interval_seconds=args.movement_interval,
                        start_mono=current_mono,
                    )
                    if args.traffic_demo and not traffic_demo_assigned:
                        attach_demo_traffic(
                            live=live,
                            run_id=run_id,
                            departure=now,
                            start_delay_seconds=args.traffic_start_delay,
                            duration_seconds=args.traffic_duration,
                            speed_factor=args.traffic_speed_factor,
                        )
                        traffic_demo_assigned = True
                        print(
                            "[Supply Chain V3 Streamer] TRAFFIC PLANNED "
                            f"shipment_id={shipment_id} "
                            f"start={live.traffic.start_time.isoformat()} "
                            f"end={live.traffic.end_time.isoformat()} "
                            f"speed_factor={live.traffic.speed_factor:.2f}"
                        )

                    if args.weather_demo and not weather_demo_assigned:
                        attach_demo_weather(
                            live=live,
                            run_id=run_id,
                            departure=now,
                            start_delay_seconds=args.weather_start_delay,
                            duration_seconds=args.weather_duration,
                            weather_factor=args.weather_speed_factor,
                        )
                        weather_demo_assigned = True
                        print(
                            "[Supply Chain V3 Streamer] WEATHER PLANNED "
                            f"shipment_id={shipment_id} "
                            f"start={live.weather.start_time.isoformat()} "
                            f"end={live.weather.end_time.isoformat()} "
                            f"weather_factor={live.weather.speed_factor:.2f}"
                        )

                    if args.mechanical_demo and not mechanical_demo_assigned:
                        attach_demo_mechanical(
                            live=live,
                            run_id=run_id,
                            departure=now,
                            start_delay_seconds=args.mechanical_start_delay,
                            duration_seconds=args.mechanical_duration,
                        )
                        mechanical_demo_assigned = True
                        print(
                            "[Supply Chain V3 Streamer] MECHANICAL PLANNED "
                            f"shipment_id={shipment_id} "
                            f"start={live.mechanical.start_time.isoformat()} "
                            f"end={live.mechanical.end_time.isoformat()}"
                        )

                    if args.fuel_demo and not fuel_demo_assigned:
                        configure_live_fuel_demo(
                            live=live,
                            start_fuel_pct=args.fuel_demo_start_pct,
                            trigger_pct=args.fuel_trigger_pct,
                            refuel_to_pct=args.fuel_refuel_to_pct,
                            stop_duration_seconds=args.fuel_stop_duration,
                        )
                        fuel_demo_assigned = True
                        print(
                            "[Supply Chain V3 Streamer] FUEL DEMO ARMED "
                            f"shipment_id={shipment_id} "
                            f"start_fuel={live.item.vehicle.fuel_level_pct:.2f} "
                            f"trigger={live.fuel_trigger_pct:.2f} "
                            f"refuel_to={live.fuel_refuel_to_pct:.2f}"
                        )

                    if args.reefer_demo and not reefer_demo_assigned:
                        configure_live_reefer_demo(
                            live=live,
                            current_mono=current_mono,
                            start_delay_seconds=args.reefer_start_delay,
                            duration_seconds=args.reefer_duration,
                            excursion_temp_c=args.reefer_excursion_temp,
                            recovery_temp_c=args.reefer_recovery_temp,
                        )
                        reefer_demo_assigned = True
                        print(
                            "[Supply Chain V3 Streamer] REEFER PLANNED "
                            f"shipment_id={shipment_id} "
                            f"start_delay={args.reefer_start_delay}s "
                            f"duration={args.reefer_duration}s "
                            f"excursion_temp={args.reefer_excursion_temp:.2f}"
                        )

                    if args.mixed_demo and mixed_demo_assignment_index < 5:
                        mixed_kind = (
                            "traffic",
                            "weather",
                            "mechanical",
                            "fuel",
                            "reefer",
                        )[mixed_demo_assignment_index]

                        if mixed_kind == "traffic":
                            attach_demo_traffic(
                                live=live,
                                run_id=run_id,
                                departure=now,
                                start_delay_seconds=args.traffic_start_delay,
                                duration_seconds=args.traffic_duration,
                                speed_factor=args.traffic_speed_factor,
                            )
                        elif mixed_kind == "weather":
                            attach_demo_weather(
                                live=live,
                                run_id=run_id,
                                departure=now,
                                start_delay_seconds=args.weather_start_delay,
                                duration_seconds=args.weather_duration,
                                weather_factor=args.weather_speed_factor,
                            )
                        elif mixed_kind == "mechanical":
                            attach_demo_mechanical(
                                live=live,
                                run_id=run_id,
                                departure=now,
                                start_delay_seconds=args.mechanical_start_delay,
                                duration_seconds=args.mechanical_duration,
                            )
                        elif mixed_kind == "fuel":
                            configure_live_fuel_demo(
                                live=live,
                                start_fuel_pct=args.fuel_demo_start_pct,
                                trigger_pct=args.fuel_trigger_pct,
                                refuel_to_pct=args.fuel_refuel_to_pct,
                                stop_duration_seconds=args.fuel_stop_duration,
                            )
                        else:
                            configure_live_reefer_demo(
                                live=live,
                                current_mono=current_mono,
                                start_delay_seconds=args.reefer_start_delay,
                                duration_seconds=args.reefer_duration,
                                excursion_temp_c=args.reefer_excursion_temp,
                                recovery_temp_c=args.reefer_recovery_temp,
                            )

                        print(
                            "[Supply Chain V3 Streamer] MIXED ASSIGNMENT "
                            f"shipment_id={shipment_id} "
                            f"vehicle_id={vehicle.profile.vehicle_id} "
                            f"kind={mixed_kind.upper()}"
                        )
                        mixed_demo_assignment_index += 1

                    active[shipment_id] = live
                    writer.insert_shipments([live.item.shipment])
                    writer.insert_events(live.item.events)
                    stats.shipment_start_ms = (perf_counter() - t0) * 1000
                    print(
                        "[Supply Chain V3 Streamer] START "
                        f"shipment_id={shipment_id} "
                        f"vehicle_id={vehicle.profile.vehicle_id} "
                        f"route_id={route.route_id}"
                    )

                next_shipment_mono = current_mono + args.shipment_interval

            completed = []

            for shipment_id, live in list(active.items()):
                if current_mono < live.next_tick_mono:
                    continue

                lateness_s = max(
                    0.0,
                    current_mono - live.next_tick_mono,
                )

                before_events = len(live.item.events)
                before_samples = len(live.item.telemetry_samples)

                end_live_mechanical_if_needed(
                    live=live,
                    now=now,
                )
                end_live_fuel_stop_if_needed(
                    live=live,
                    now=now,
                    current_mono=current_mono,
                )
                reefer_active = apply_live_reefer_state(
                    live=live,
                    now=now,
                    current_mono=current_mono,
                )

                if live.fuel_stop_pending and not live.fuel_stop_active:
                    begin_live_fuel_stop(
                        live=live,
                        now=now,
                        current_mono=current_mono,
                    )

                mechanical_active = mechanical_is_active(
                    live=live,
                    now=now,
                )
                fuel_active = live.fuel_stop_active

                applied_traffic = None
                applied_weather = None

                if fuel_active:
                    t0 = perf_counter()
                    tick_live_fuel_stop(
                        live=live,
                        now=now,
                        movement_interval_seconds=args.movement_interval,
                    )
                    stats.tick_compute_ms += (perf_counter() - t0) * 1000
                elif mechanical_active:
                    begin_live_mechanical_if_needed(
                        live=live,
                        now=now,
                    )
                    t0 = perf_counter()
                    tick_live_mechanical_stop(
                        live=live,
                        now=now,
                        movement_interval_seconds=args.movement_interval,
                    )
                    stats.tick_compute_ms += (perf_counter() - t0) * 1000
                else:
                    applied_traffic, traffic_cause = apply_live_traffic_before_tick(
                        live=live,
                        now=now,
                    )
                    applied_weather, weather_cause = apply_live_weather_before_tick(
                        live=live,
                        now=now,
                    )

                    eta_cause_code = traffic_cause or weather_cause

                    t0 = perf_counter()
                    tick_concurrent_shipment(
                        item=live.item,
                        now=now,
                        movement_interval_seconds=args.movement_interval,
                        base_consumption_pct_per_100km=1.0,
                        eta_event_threshold_min=1.0,
                        eta_cause_code=eta_cause_code,
                        cargo_temp_c=live.current_cargo_temp_c,
                    )
                    stats.tick_compute_ms += (perf_counter() - t0) * 1000

                    clear_live_weather_after_tick(
                        live=live,
                        applied=applied_weather,
                    )
                    clear_live_traffic_after_tick(
                        live=live,
                        applied=applied_traffic,
                    )

                    if mark_fuel_stop_pending_if_needed(live=live):
                        print(
                            "[Supply Chain V3 Streamer] FUEL STOP PENDING "
                            f"shipment_id={shipment_id} "
                            f"fuel={live.item.vehicle.fuel_level_pct:.2f}"
                        )

                new_samples = live.item.telemetry_samples[before_samples:]
                new_events = live.item.events[before_events:]

                if len(new_samples) != 1:
                    raise RuntimeError(
                        "live tick must emit exactly one telemetry sample"
                    )

                t0 = perf_counter()
                writer.insert_fleet_telemetry(
                    (
                        sample.time,
                        sample.row,
                        run_id,
                    )
                    for sample in new_samples
                )
                stats.telemetry_insert_ms += (perf_counter() - t0) * 1000

                if new_events:
                    t0 = perf_counter()
                    writer.insert_events(new_events)
                    stats.event_insert_ms += (perf_counter() - t0) * 1000

                t0 = perf_counter()
                update_persisted_shipment(conn, live.item.shipment)
                stats.shipment_update_ms += (perf_counter() - t0) * 1000

                sample = new_samples[0]
                print(
                    "[Supply Chain V3 Streamer] TICK "
                    f"time={sample.time.isoformat()} "
                    f"shipment_id={shipment_id} "
                    f"vehicle_id={sample.row.vehicle_id} "
                    f"speed={sample.row.speed_kmh:.2f} "
                    f"traffic={'ON' if applied_traffic is not None else 'OFF'} "
                    f"weather={'ON' if applied_weather is not None else 'OFF'} "
                    f"mechanical={'ON' if mechanical_active else 'OFF'} "
                    f"fuel_stop={'ON' if fuel_active else 'OFF'} "
                    f"fuel={sample.row.fuel_level_pct:.2f} "
                    f"reefer={'ON' if reefer_active else 'OFF'} "
                    f"cargo_temp={(
                        f'{sample.row.cargo_temp_c:.2f}'
                        if sample.row.cargo_temp_c is not None
                        else 'N/A'
                    )} "
                    f"lateness={lateness_s:.3f}s"
                )

                live.next_tick_mono = current_mono + args.movement_interval

                if live.item.arrived:
                    vehicle = live.item.vehicle
                    begin_turnaround(vehicle)
                    release_vehicle(vehicle)
                    mark_vehicle_available(
                        availability=availability,
                        vehicle_id=vehicle.profile.vehicle_id,
                        available_at=now,
                    )
                    completed.append(shipment_id)

            for shipment_id in completed:
                active.pop(shipment_id, None)

            stats.loop_ms = (perf_counter() - loop_start) * 1000

            if stats.loop_ms >= args.timing_log_threshold_ms:
                print(
                    "[TIMING] "
                    f"loop={stats.loop_ms:.1f}ms "
                    f"start={stats.shipment_start_ms:.1f}ms "
                    f"tick={stats.tick_compute_ms:.1f}ms "
                    f"telemetry_db={stats.telemetry_insert_ms:.1f}ms "
                    f"event_db={stats.event_insert_ms:.1f}ms "
                    f"shipment_db={stats.shipment_update_ms:.1f}ms "
                    f"active={len(active)}"
                )

            time.sleep(1)

        ended_at = finalize_live_simulation_run(
            conn,
            run_id=run_id,
            simulation_start=now,
            status="COMPLETED",
        )
        print(
            "[Supply Chain V3 Streamer] RUN COMPLETED "
            f"run_id={run_id} simulation_end={ended_at.isoformat()}"
        )

    except Exception:
        if run_id is not None:
            try:
                finalize_live_simulation_run(
                    conn,
                    run_id=run_id,
                    simulation_start=now,
                    status="FAILED",
                )
            except Exception:
                conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
