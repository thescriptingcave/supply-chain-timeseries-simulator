"""Persist a production-profile historical dataset for Supply Chain Generator v3.

This runner uses the conservative production profile and the validated vehicle-availability scheduler. It is intended for the 30-day scale-validation gate before a larger historical run.

Run from repository root:

    uv run python -m scripts.generate_supply_chain_v3_historical --days 365 --seed 42
"""

from __future__ import annotations

import argparse
import os
import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import psycopg2

from generators.supply_chain.cargo_exceptions import ReeferTemperaturePolicy
from generators.supply_chain.concurrent_contention import (
    ContendedShipmentPlan,
    run_concurrent_fleet_with_contention,
)
from generators.supply_chain.concurrent_disruptions import (
    DisruptedShipmentPlan,
    run_disruption_aware_fleet,
)
from generators.supply_chain.context import SimulationContext
from generators.supply_chain.db_writer import SupplyChainWriter
from generators.supply_chain.disruptions import (
    mechanical_disruption,
    traffic_disruption,
    weather_disruption,
)
from generators.supply_chain.fuel_stop import FuelStopPolicy
from generators.supply_chain.fuel_stop_engine import (
    FuelStopShipmentPlan,
    run_fuel_stop_shipment,
)
from generators.supply_chain.mechanical_disruption import (
    MechanicalShipmentPlan,
    run_mechanical_disruption_shipment,
)
from generators.supply_chain.models import (
    CargoProfile,
    Priority,
    RouteProfile,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.persistence import SimulationRunRecord
from generators.supply_chain.production_planner import (
    build_event_plan,
    planned_shipment_count,
)
from generators.supply_chain.reefer_exception_engine import (
    ReeferShipmentPlan,
    TemperatureExcursion,
    run_reefer_exception_shipment,
)
from generators.supply_chain.run_config import production_profile
from generators.supply_chain.vehicle_scheduler import (
    choose_available_vehicle,
    initialize_vehicle_availability,
    mark_vehicle_available,
)


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_routes(cur) -> list[RouteProfile]:
    cur.execute(
        """
        SELECT
            route_id, origin_wh_id, dest_wh_id, distance_km,
            nominal_speed_kmh, minimum_speed_kmh, maximum_speed_kmh,
            baseline_travel_min, congestion_sensitivity, weather_sensitivity,
            morning_peak_factor, evening_peak_factor, overnight_factor,
            demand_weight, disruption_probability
        FROM sc_routes
        WHERE active = true
        ORDER BY route_id
        """
    )
    rows = cur.fetchall()
    if not rows:
        raise RuntimeError("no active routes found")

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
    rows = cur.fetchall()
    if len(rows) < 2:
        raise RuntimeError("at least two warehouses are required")

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
        for r in rows
    }


def load_vehicle_profiles(cur) -> list[VehicleProfile]:
    cur.execute(
        """
        SELECT
            vehicle_id, vehicle_reg, vehicle_type, max_payload_kg,
            fuel_type, fleet_operator, year_manufactured,
            fuel_efficiency_factor, reliability_factor, condition_factor,
            cruise_speed_factor, maintenance_risk_factor, reefer_capable
        FROM sc_vehicles
        ORDER BY vehicle_id
        """
    )
    rows = cur.fetchall()
    if not rows:
        raise RuntimeError("no vehicles found")

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
        for r in rows
    ]


def load_cargo_profiles(cur) -> tuple[CargoProfile, CargoProfile]:
    cur.execute(
        """
        SELECT
            cargo_type, requires_reefer, target_temp_c, min_temp_c,
            max_temp_c, target_humidity_pct, handling_sensitivity,
            loading_time_factor
        FROM sc_cargo_profiles
        WHERE active = true
        ORDER BY cargo_type
        """
    )
    rows = cur.fetchall()

    general = next((r for r in rows if not r[1]), None)
    reefer = next((r for r in rows if r[1]), None)
    if general is None or reefer is None:
        raise RuntimeError("both general and reefer cargo profiles are required")

    def make(r) -> CargoProfile:
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

    return make(general), make(reefer)


def fresh_vehicle(
    profile: VehicleProfile,
    origin: WarehouseState,
    *,
    fuel_pct: float = 95.0,
) -> VehicleState:
    return VehicleState(
        profile=profile,
        current_warehouse_id=origin.profile.warehouse_id,
        lat=origin.profile.lat,
        lon=origin.profile.lon,
        fuel_level_pct=fuel_pct,
        odometer_km=100000.0 + (profile.vehicle_id * 1000.0),
    )


def runtime_warehouse(
    source: WarehouseState,
    *,
    loading_capacity: int | None = None,
    unloading_capacity: int | None = None,
) -> WarehouseState:
    return WarehouseState(
        profile=replace(
            source.profile,
            loading_capacity=(
                loading_capacity
                if loading_capacity is not None
                else source.profile.loading_capacity
            ),
            unloading_capacity=(
                unloading_capacity
                if unloading_capacity is not None
                else source.profile.unloading_capacity
            ),
        )
    )


def build_production_categories(
    *,
    shipment_count: int,
    vehicle_count: int,
    seed: int,
    days: int,
) -> list[str]:
    """Convert the seeded planner into an inspectable exclusive workload mix."""
    config = production_profile(days=days, seed=seed)
    rng = random.Random(seed)

    totals = {
        "traffic": 0,
        "weather": 0,
        "mechanical": 0,
        "reefer": 0,
    }

    for i in range(shipment_count):
        plan = build_event_plan(
            rng=rng,
            config=config,
            requires_reefer=(i % 4 == 0),
        )
        totals["traffic"] += int(plan.traffic)
        totals["weather"] += int(plan.weather)
        totals["mechanical"] += int(plan.mechanical)
        totals["reefer"] += int(plan.reefer_excursion)

    categories: list[str] = []

    # Keep a small deterministic contention sample in the 30-day scale run.
    # This is not representative frequency; it preserves warehouse analytics.
    # The contention cohort runs concurrently, so it cannot exceed the
    # physical fleet size. At long horizons, a percentage-only calculation
    # would incorrectly create dozens of simultaneous contention shipments.
    contention_count = min(
        max(3, round(shipment_count * 0.02)),
        vehicle_count,
        shipment_count,
    )
    categories.extend(["contention"] * contention_count)

    remaining = shipment_count - len(categories)

    # Use the seeded production probabilities as the primary event mix.
    # This 30-day run is still a scale-validation gate, so ensure every
    # implemented event family appears at least once even if the seeded
    # production draw happens to produce zero occurrences for a rare event.
    for name in ("traffic", "weather", "mechanical", "reefer"):
        planned = max(1, totals[name])
        take = min(planned, remaining)
        categories.extend([name] * take)
        remaining -= take

    # Fuel stops are state-driven, so use a conservative explicit planning rate.
    fuel_count = min(max(1, round(shipment_count * 0.03)), remaining)
    categories.extend(["fuel"] * fuel_count)
    remaining -= fuel_count

    categories.extend(["normal"] * remaining)

    if len(categories) != shipment_count:
        raise RuntimeError("production workload planning produced wrong count")

    return categories


def main() -> None:
    args = parse_args()
    config = production_profile(days=args.days, seed=args.seed)
    config.validate()

    conn = psycopg2.connect(DB_URL)
    run_id: int | None = None

    try:
        writer = SupplyChainWriter(conn, batch_size=5000)

        with conn.cursor() as cur:
            routes = load_routes(cur)
            warehouses = load_warehouses(cur)
            vehicle_profiles = load_vehicle_profiles(cur)
            general_cargo, reefer_cargo = load_cargo_profiles(cur)

        reefer_profiles = [p for p in vehicle_profiles if p.reefer_capable]
        non_reefer_profiles = [p for p in vehicle_profiles if not p.reefer_capable]
        if not reefer_profiles:
            raise RuntimeError("at least one reefer-capable vehicle is required")
        if len(vehicle_profiles) < 3:
            raise RuntimeError("at least three vehicles are required")

        shipment_count = planned_shipment_count(
            vehicle_count=len(vehicle_profiles),
            config=config,
        )
        categories = build_production_categories(
            shipment_count=shipment_count,
            vehicle_count=len(vehicle_profiles),
            seed=args.seed,
            days=args.days,
        )

        start = datetime.now(timezone.utc).replace(microsecond=0)
        end = start + timedelta(days=args.days + 2)

        availability = initialize_vehicle_availability(
            vehicle_profiles=vehicle_profiles,
            start_time=start,
        )

        def release_vehicle(shipment) -> None:
            completion_time = (
                shipment.delivery_completed_at
                or shipment.actual_arrival
            )
            if completion_time is None:
                raise RuntimeError(
                    "shipment completed without terminal timestamp"
                )
            mark_vehicle_available(
                availability=availability,
                vehicle_id=shipment.vehicle_id,
                available_at=completion_time,
            )

        run_id = writer.create_simulation_run(
            SimulationRunRecord(
                generator_name="supply_chain",
                model_version="3.0.0",
                seed=args.seed,
                simulation_start=start,
                simulation_end=end,
                configuration_version="v3-production",
                status="STARTED",
                metadata_json={
                    "purpose": "v3-historical-production",
                    "requested_days": args.days,
                    "profile": "production",
                    "planned_shipments": shipment_count,
                    "categories": categories,
                },
            )
        )

        all_shipments = []
        all_telemetry = []
        all_events = []
        all_warehouse_samples = []

        shipment_ids = [
            writer.allocate_shipment_id()
            for _ in range(shipment_count)
        ]

        # Spread starting times across the requested validation horizon.
        spacing_minutes = max(
            10,
            int((args.days * 24 * 60) / max(1, shipment_count)),
        )

        index = 0

        # Initial contention cohort: shared warehouse contention.
        contention_count = 0
        for category in categories:
            if category == "contention":
                contention_count += 1
            else:
                break

        if contention_count > 0:
            route = routes[0]
            origin = runtime_warehouse(
                warehouses[route.origin_wh_id],
                loading_capacity=1,
            )
            destination = runtime_warehouse(
                warehouses[route.dest_wh_id],
                unloading_capacity=1,
            )
            contention_start = start
            if contention_count > len(vehicle_profiles):
                raise RuntimeError("contention cohort exceeds fleet size")
            contention_vehicles = [
                fresh_vehicle(vehicle_profiles[i], origin)
                for i in range(contention_count)
            ]

            result = run_concurrent_fleet_with_contention(
                context=SimulationContext(
                    simulation_start=contention_start,
                    simulation_end=end,
                    seed=args.seed,
                    run_id=run_id,
                ),
                plans=[
                    ContendedShipmentPlan(
                        shipment_id=shipment_ids[i],
                        vehicle_id=contention_vehicles[i].profile.vehicle_id,
                        route=route,
                        cargo=general_cargo,
                        priority=Priority.STANDARD,
                    )
                    for i in range(contention_count)
                ],
                vehicles=contention_vehicles,
                warehouses={
                    origin.profile.warehouse_id: origin,
                    destination.profile.warehouse_id: destination,
                },
                movement_interval_seconds=config.movement_interval_seconds,
                warehouse_tick_seconds=config.warehouse_tick_seconds,
                base_consumption_pct_per_100km=(
                    config.base_consumption_pct_per_100km
                ),
            )

            for item in result.shipments:
                all_shipments.append(item.shipment)
                all_telemetry.extend(item.telemetry_samples)
                all_events.extend(item.events)
                release_vehicle(item.shipment)
            all_warehouse_samples.extend(result.warehouse_samples)
            index = contention_count

        for i in range(index, shipment_count):
            category = categories[i]
            route = routes[i % len(routes)]
            origin = warehouses[route.origin_wh_id]
            destination = warehouses[route.dest_wh_id]
            requested_departure = start + timedelta(
                minutes=i * spacing_minutes
            )
            requires_reefer = category == "reefer"

            profile, shipment_start = choose_available_vehicle(
                vehicle_profiles=vehicle_profiles,
                availability=availability,
                requested_departure=requested_departure,
                requires_reefer=requires_reefer,
            )

            # Keep single-shipment engine windows comfortably inside simulation_end.
            context = SimulationContext(
                simulation_start=shipment_start,
                simulation_end=end,
                seed=args.seed + i,
                run_id=run_id,
            )

            if category == "reefer":
                vehicle = fresh_vehicle(profile, origin)

                result = run_reefer_exception_shipment(
                    context=context,
                    plan=ReeferShipmentPlan(
                        shipment_id=shipment_ids[i],
                        vehicle_id=profile.vehicle_id,
                        route=route,
                        cargo=reefer_cargo,
                    ),
                    vehicle=vehicle,
                    origin=origin,
                    destination=destination,
                    policy=ReeferTemperaturePolicy(
                        min_temp_c=reefer_cargo.min_temp_c or 1.0,
                        max_temp_c=reefer_cargo.max_temp_c or 8.0,
                        recovery_temp_c=reefer_cargo.target_temp_c or 4.0,
                    ),
                    excursion=TemperatureExcursion(
                        start_time=shipment_start + timedelta(minutes=30),
                        end_time=shipment_start + timedelta(minutes=90),
                        excursion_temp_c=12.0,
                    ),
                    normal_cargo_temp_c=reefer_cargo.target_temp_c or 4.0,
                    movement_interval_seconds=config.movement_interval_seconds,
                    base_consumption_pct_per_100km=(
                        config.base_consumption_pct_per_100km
                    ),
                )
                all_shipments.append(result.shipment)
                all_telemetry.extend(result.telemetry_samples)
                all_events.extend(result.events)
                release_vehicle(result.shipment)
                continue

            vehicle = fresh_vehicle(profile, origin)

            if category in {"traffic", "weather"}:
                disruptions = []
                if category == "traffic":
                    disruptions.append(
                        traffic_disruption(
                            disruption_id=f"VAL-TRAFFIC-{run_id}-{i}",
                            start_time=shipment_start + timedelta(minutes=30),
                            duration_minutes=60,
                            speed_factor=0.50,
                            route_id=route.route_id,
                        )
                    )
                else:
                    disruptions.append(
                        weather_disruption(
                            disruption_id=f"VAL-RAIN-{run_id}-{i}",
                            start_time=shipment_start + timedelta(minutes=30),
                            duration_minutes=60,
                            weather_factor=0.70,
                            route_id=route.route_id,
                        )
                    )

                result = run_disruption_aware_fleet(
                    context=context,
                    plans=[
                        DisruptedShipmentPlan(
                            shipment_id=shipment_ids[i],
                            vehicle_id=profile.vehicle_id,
                            route=route,
                            cargo=general_cargo,
                        )
                    ],
                    vehicles=[vehicle],
                    warehouses={
                        origin.profile.warehouse_id: origin,
                        destination.profile.warehouse_id: destination,
                    },
                    disruptions=disruptions,
                    movement_interval_seconds=config.movement_interval_seconds,
                    base_consumption_pct_per_100km=(
                        config.base_consumption_pct_per_100km
                    ),
                    eta_event_threshold_min=1.0,
                )
                item = result.shipments[0]
                all_shipments.append(item.shipment)
                all_telemetry.extend(item.telemetry_samples)
                all_events.extend(item.events)
                release_vehicle(item.shipment)
                continue

            if category == "mechanical":
                result = run_mechanical_disruption_shipment(
                    context=context,
                    plan=MechanicalShipmentPlan(
                        shipment_id=shipment_ids[i],
                        vehicle_id=profile.vehicle_id,
                        route=route,
                        cargo=general_cargo,
                    ),
                    vehicle=vehicle,
                    origin=origin,
                    destination=destination,
                    disruption=mechanical_disruption(
                        disruption_id=f"VAL-MECH-{run_id}-{i}",
                        start_time=shipment_start + timedelta(minutes=30),
                        duration_minutes=60,
                        vehicle_id=profile.vehicle_id,
                    ),
                    movement_interval_seconds=config.movement_interval_seconds,
                    base_consumption_pct_per_100km=(
                        config.base_consumption_pct_per_100km
                    ),
                    eta_event_threshold_min=1.0,
                )
                all_shipments.append(result.shipment)
                all_telemetry.extend(result.telemetry_samples)
                all_events.extend(result.events)
                release_vehicle(result.shipment)
                continue

            if category == "fuel":
                fuel_vehicle = fresh_vehicle(profile, origin, fuel_pct=26.0)
                result = run_fuel_stop_shipment(
                    context=context,
                    plan=FuelStopShipmentPlan(
                        shipment_id=shipment_ids[i],
                        vehicle_id=profile.vehicle_id,
                        route=route,
                        cargo=general_cargo,
                    ),
                    vehicle=fuel_vehicle,
                    origin=origin,
                    destination=destination,
                    policy=FuelStopPolicy(
                        trigger_pct=config.fuel_trigger_pct,
                        refuel_to_pct=config.fuel_refill_pct,
                        stop_duration_minutes=config.fuel_stop_minutes,
                    ),
                    movement_interval_seconds=config.movement_interval_seconds,
                    base_consumption_pct_per_100km=2.5,
                    eta_event_threshold_min=1.0,
                )
                all_shipments.append(result.shipment)
                all_telemetry.extend(result.telemetry_samples)
                all_events.extend(result.events)
                release_vehicle(result.shipment)
                continue

            # Normal shipment uses disruption-aware runner with no disruptions.
            result = run_disruption_aware_fleet(
                context=context,
                plans=[
                    DisruptedShipmentPlan(
                        shipment_id=shipment_ids[i],
                        vehicle_id=profile.vehicle_id,
                        route=route,
                        cargo=general_cargo,
                    )
                ],
                vehicles=[vehicle],
                warehouses={
                    origin.profile.warehouse_id: origin,
                    destination.profile.warehouse_id: destination,
                },
                disruptions=[],
                movement_interval_seconds=config.movement_interval_seconds,
                base_consumption_pct_per_100km=(
                    config.base_consumption_pct_per_100km
                ),
                eta_event_threshold_min=1.0,
            )
            item = result.shipments[0]
            all_shipments.append(item.shipment)
            all_telemetry.extend(item.telemetry_samples)
            all_events.extend(item.events)
            release_vehicle(item.shipment)

        writer.insert_shipments(all_shipments)
        writer.insert_fleet_telemetry(
            (sample.time, sample.row, run_id)
            for sample in all_telemetry
        )
        writer.insert_events(all_events)

        if all_warehouse_samples:
            writer.insert_warehouse_operations(
                (sample.time, sample.row, run_id)
                for sample in all_warehouse_samples
            )

        writer.update_simulation_run_status(run_id, "COMPLETED")

        causal_counts: dict[str, int] = {}
        for event in all_events:
            if event.cause_code:
                causal_counts[event.cause_code] = (
                    causal_counts.get(event.cause_code, 0) + 1
                )

        category_counts = {
            name: categories.count(name)
            for name in sorted(set(categories))
        }

        print("[Supply Chain v3] Historical production dataset passed")
        print(f"  run_id:             {run_id}")
        print(f"  shipments:          {len(all_shipments)}")
        print(f"  telemetry rows:     {len(all_telemetry)}")
        print(f"  warehouse rows:     {len(all_warehouse_samples)}")
        print(f"  events:             {len(all_events)}")
        print(f"  categories:         {category_counts}")
        print(f"  causal event counts:{causal_counts}")

    except Exception:
        if run_id is not None:
            try:
                SupplyChainWriter(conn).update_simulation_run_status(
                    run_id,
                    "FAILED",
                )
            except Exception:
                conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
