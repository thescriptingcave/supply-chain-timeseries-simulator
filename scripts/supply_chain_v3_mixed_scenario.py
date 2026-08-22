"""Final mixed-scenario integration gate for Supply Chain Generator v3.

This is intentionally an integration orchestrator, not a new event engine.
It runs previously validated v3 capabilities in one simulation run so we can
prove they coexist in the same persisted dataset.

Run from repository root:

    uv run python -m scripts.supply_chain_v3_mixed_scenario
"""

from __future__ import annotations

import os
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
from generators.supply_chain.reefer_exception_engine import (
    ReeferShipmentPlan,
    TemperatureExcursion,
    run_reefer_exception_shipment,
)


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


def load_routes(cur, count: int = 3) -> list[RouteProfile]:
    cur.execute(
        """
        SELECT
            route_id,
            origin_wh_id,
            dest_wh_id,
            distance_km,
            nominal_speed_kmh,
            minimum_speed_kmh,
            maximum_speed_kmh,
            baseline_travel_min,
            congestion_sensitivity,
            weather_sensitivity,
            morning_peak_factor,
            evening_peak_factor,
            overnight_factor,
            demand_weight,
            disruption_probability
        FROM sc_routes
        WHERE active = true
        ORDER BY route_id
        LIMIT %s
        """,
        (count,),
    )
    rows = cur.fetchall()
    if len(rows) < count:
        raise RuntimeError(f"expected at least {count} active routes, found {len(rows)}")

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


def load_warehouse(cur, warehouse_id: int) -> WarehouseState:
    cur.execute(
        """
        SELECT
            warehouse_id,
            warehouse_name,
            lat,
            lon,
            timezone,
            loading_capacity,
            unloading_capacity,
            baseline_loading_min,
            baseline_unloading_min,
            congestion_sensitivity,
            cold_storage_capable
        FROM sc_warehouses
        WHERE warehouse_id = %s
        """,
        (warehouse_id,),
    )
    r = cur.fetchone()
    if r is None:
        raise RuntimeError(f"warehouse_id={warehouse_id} not found")

    return WarehouseState(
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


def clone_runtime_warehouse(
    warehouse: WarehouseState,
    *,
    loading_capacity: int | None = None,
    unloading_capacity: int | None = None,
) -> WarehouseState:
    profile = replace(
        warehouse.profile,
        loading_capacity=(
            loading_capacity
            if loading_capacity is not None
            else warehouse.profile.loading_capacity
        ),
        unloading_capacity=(
            unloading_capacity
            if unloading_capacity is not None
            else warehouse.profile.unloading_capacity
        ),
    )
    return WarehouseState(profile=profile)


def load_vehicles(cur, count: int = 6) -> list[VehicleProfile]:
    cur.execute(
        """
        SELECT
            vehicle_id,
            vehicle_reg,
            vehicle_type,
            max_payload_kg,
            fuel_type,
            fleet_operator,
            year_manufactured,
            fuel_efficiency_factor,
            reliability_factor,
            condition_factor,
            cruise_speed_factor,
            maintenance_risk_factor,
            reefer_capable
        FROM sc_vehicles
        ORDER BY vehicle_id
        LIMIT %s
        """,
        (count,),
    )
    rows = cur.fetchall()
    if len(rows) < count:
        raise RuntimeError(f"expected at least {count} vehicles, found {len(rows)}")

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


def load_reefer_vehicle_profile(cur) -> VehicleProfile:
    cur.execute(
        """
        SELECT
            vehicle_id,
            vehicle_reg,
            vehicle_type,
            max_payload_kg,
            fuel_type,
            fleet_operator,
            year_manufactured,
            fuel_efficiency_factor,
            reliability_factor,
            condition_factor,
            cruise_speed_factor,
            maintenance_risk_factor,
            reefer_capable
        FROM sc_vehicles
        WHERE reefer_capable = true
        ORDER BY vehicle_id
        LIMIT 1
        """
    )
    r = cur.fetchone()
    if r is None:
        raise RuntimeError("no reefer-capable vehicle found")

    return VehicleProfile(
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


def state_for(profile: VehicleProfile, warehouse: WarehouseState, fuel: float = 95.0) -> VehicleState:
    return VehicleState(
        profile=profile,
        current_warehouse_id=warehouse.profile.warehouse_id,
        lat=warehouse.profile.lat,
        lon=warehouse.profile.lon,
        fuel_level_pct=fuel,
        odometer_km=100000.0 + profile.vehicle_id * 1000.0,
    )


def load_general_cargo(cur) -> CargoProfile:
    cur.execute(
        """
        SELECT
            cargo_type,
            requires_reefer,
            target_temp_c,
            min_temp_c,
            max_temp_c,
            target_humidity_pct,
            handling_sensitivity,
            loading_time_factor
        FROM sc_cargo_profiles
        WHERE cargo_type = 'GENERAL_FREIGHT'
          AND active = true
        """
    )
    r = cur.fetchone()
    if r is None:
        raise RuntimeError("GENERAL_FREIGHT cargo profile not found")

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


def load_reefer_cargo(cur) -> CargoProfile:
    cur.execute(
        """
        SELECT
            cargo_type,
            requires_reefer,
            target_temp_c,
            min_temp_c,
            max_temp_c,
            target_humidity_pct,
            handling_sensitivity,
            loading_time_factor
        FROM sc_cargo_profiles
        WHERE requires_reefer = true
          AND active = true
        ORDER BY cargo_type
        LIMIT 1
        """
    )
    r = cur.fetchone()
    if r is None:
        raise RuntimeError("no active reefer cargo profile found")

    return CargoProfile(
        cargo_type=r[0],
        requires_reefer=r[1],
        target_temp_c=float(r[2]) if r[2] is not None else 4.0,
        min_temp_c=float(r[3]) if r[3] is not None else 1.0,
        max_temp_c=float(r[4]) if r[4] is not None else 8.0,
        target_humidity_pct=float(r[5]) if r[5] is not None else 60.0,
        handling_sensitivity=float(r[6]),
        loading_time_factor=float(r[7]),
    )


def main() -> None:
    start = datetime.now(timezone.utc).replace(microsecond=0)
    end = start + timedelta(days=5)

    conn = psycopg2.connect(DB_URL)
    run_id: int | None = None

    try:
        writer = SupplyChainWriter(conn, batch_size=5000)

        run_id = writer.create_simulation_run(
            SimulationRunRecord(
                generator_name="supply_chain",
                model_version="3.0.0",
                seed=42,
                simulation_start=start,
                simulation_end=end,
                configuration_version="v3-default",
                status="STARTED",
                metadata_json={
                    "purpose": "v3-final-mixed-scenario-gate",
                    "capabilities": [
                        "warehouse_contention",
                        "traffic",
                        "weather",
                        "mechanical",
                        "fuel_stop",
                        "reefer_exception",
                    ],
                },
            )
        )

        with conn.cursor() as cur:
            routes = load_routes(cur, count=3)
            vehicle_profiles = load_vehicles(cur, count=6)
            reefer_profile = load_reefer_vehicle_profile(cur)
            general_cargo = load_general_cargo(cur)
            reefer_cargo = load_reefer_cargo(cur)

        # Cache all warehouses touched by selected routes.
        warehouse_ids = {
            route.origin_wh_id for route in routes
        } | {
            route.dest_wh_id for route in routes
        }

        warehouses: dict[int, WarehouseState] = {}
        with conn.cursor() as cur:
            for warehouse_id in warehouse_ids:
                warehouses[warehouse_id] = load_warehouse(cur, warehouse_id)

        # Allocate seven persisted shipments:
        # 3 warehouse-contention, then one each for traffic, weather,
        # mechanical, fuel stop, and reefer.
        shipment_ids = [
            writer.allocate_shipment_id()
            for _ in range(7)
        ]

        all_shipments = []
        all_telemetry = []
        all_events = []
        all_warehouse_samples = []

        # 1) Warehouse contention: three vehicles on same route, runtime capacity=1.
        contention_route = routes[0]
        contention_origin = clone_runtime_warehouse(
            warehouses[contention_route.origin_wh_id],
            loading_capacity=1,
        )
        contention_dest = clone_runtime_warehouse(
            warehouses[contention_route.dest_wh_id],
            unloading_capacity=1,
        )
        contention_vehicles = [
            state_for(vehicle_profiles[i], contention_origin)
            for i in range(3)
        ]
        contention_result = run_concurrent_fleet_with_contention(
            context=SimulationContext(
                simulation_start=start,
                simulation_end=end,
                seed=42,
                run_id=run_id,
            ),
            plans=[
                ContendedShipmentPlan(
                    shipment_id=shipment_ids[i],
                    vehicle_id=contention_vehicles[i].profile.vehicle_id,
                    route=contention_route,
                    cargo=general_cargo,
                    priority=Priority.STANDARD,
                )
                for i in range(3)
            ],
            vehicles=contention_vehicles,
            warehouses={
                contention_origin.profile.warehouse_id: contention_origin,
                contention_dest.profile.warehouse_id: contention_dest,
            },
            movement_interval_seconds=600.0,
            warehouse_tick_seconds=60.0,
            base_consumption_pct_per_100km=1.0,
        )
        for item in contention_result.shipments:
            all_shipments.append(item.shipment)
            all_telemetry.extend(item.telemetry_samples)
            all_events.extend(item.events)
        all_warehouse_samples.extend(contention_result.warehouse_samples)

        # 2) Traffic.
        traffic_route = routes[1]
        traffic_origin = warehouses[traffic_route.origin_wh_id]
        traffic_dest = warehouses[traffic_route.dest_wh_id]
        traffic_vehicle = state_for(vehicle_profiles[3], traffic_origin)
        traffic_result = run_disruption_aware_fleet(
            context=SimulationContext(
                simulation_start=start,
                simulation_end=end,
                seed=42,
                run_id=run_id,
            ),
            plans=[
                DisruptedShipmentPlan(
                    shipment_id=shipment_ids[3],
                    vehicle_id=traffic_vehicle.profile.vehicle_id,
                    route=traffic_route,
                    cargo=general_cargo,
                )
            ],
            vehicles=[traffic_vehicle],
            warehouses={
                traffic_origin.profile.warehouse_id: traffic_origin,
                traffic_dest.profile.warehouse_id: traffic_dest,
            },
            disruptions=[
                traffic_disruption(
                    disruption_id=f"MIXED-TRAFFIC-{run_id}",
                    start_time=start + timedelta(minutes=30),
                    duration_minutes=60,
                    speed_factor=0.50,
                    route_id=traffic_route.route_id,
                )
            ],
            movement_interval_seconds=600.0,
            base_consumption_pct_per_100km=1.0,
            eta_event_threshold_min=1.0,
        )
        traffic_item = traffic_result.shipments[0]
        all_shipments.append(traffic_item.shipment)
        all_telemetry.extend(traffic_item.telemetry_samples)
        all_events.extend(traffic_item.events)

        # 3) Weather.
        weather_route = routes[2]
        weather_origin = warehouses[weather_route.origin_wh_id]
        weather_dest = warehouses[weather_route.dest_wh_id]
        weather_vehicle = state_for(vehicle_profiles[4], weather_origin)
        weather_result = run_disruption_aware_fleet(
            context=SimulationContext(
                simulation_start=start,
                simulation_end=end,
                seed=42,
                run_id=run_id,
            ),
            plans=[
                DisruptedShipmentPlan(
                    shipment_id=shipment_ids[4],
                    vehicle_id=weather_vehicle.profile.vehicle_id,
                    route=weather_route,
                    cargo=general_cargo,
                )
            ],
            vehicles=[weather_vehicle],
            warehouses={
                weather_origin.profile.warehouse_id: weather_origin,
                weather_dest.profile.warehouse_id: weather_dest,
            },
            disruptions=[
                weather_disruption(
                    disruption_id=f"MIXED-RAIN-{run_id}",
                    start_time=start + timedelta(minutes=30),
                    duration_minutes=60,
                    weather_factor=0.70,
                    route_id=weather_route.route_id,
                )
            ],
            movement_interval_seconds=600.0,
            base_consumption_pct_per_100km=1.0,
            eta_event_threshold_min=1.0,
        )
        weather_item = weather_result.shipments[0]
        all_shipments.append(weather_item.shipment)
        all_telemetry.extend(weather_item.telemetry_samples)
        all_events.extend(weather_item.events)

        # 4) Mechanical.
        mech_vehicle = state_for(vehicle_profiles[5], contention_origin)
        mech_result = run_mechanical_disruption_shipment(
            context=SimulationContext(
                simulation_start=start,
                simulation_end=end,
                seed=42,
                run_id=run_id,
            ),
            plan=MechanicalShipmentPlan(
                shipment_id=shipment_ids[5],
                vehicle_id=mech_vehicle.profile.vehicle_id,
                route=contention_route,
                cargo=general_cargo,
            ),
            vehicle=mech_vehicle,
            origin=contention_origin,
            destination=contention_dest,
            disruption=__import__(
                "generators.supply_chain.disruptions",
                fromlist=["mechanical_disruption"],
            ).mechanical_disruption(
                disruption_id=f"MIXED-MECH-{run_id}",
                start_time=start + timedelta(minutes=30),
                duration_minutes=60,
                vehicle_id=mech_vehicle.profile.vehicle_id,
            ),
            movement_interval_seconds=600.0,
            base_consumption_pct_per_100km=1.0,
            eta_event_threshold_min=1.0,
        )
        all_shipments.append(mech_result.shipment)
        all_telemetry.extend(mech_result.telemetry_samples)
        all_events.extend(mech_result.events)

        # 5) Fuel stop.
        fuel_vehicle = state_for(vehicle_profiles[0], traffic_origin, fuel=26.0)
        fuel_result = run_fuel_stop_shipment(
            context=SimulationContext(
                simulation_start=start,
                simulation_end=end,
                seed=42,
                run_id=run_id,
            ),
            plan=FuelStopShipmentPlan(
                shipment_id=shipment_ids[6],
                vehicle_id=fuel_vehicle.profile.vehicle_id,
                route=traffic_route,
                cargo=general_cargo,
            ),
            vehicle=fuel_vehicle,
            origin=traffic_origin,
            destination=traffic_dest,
            policy=FuelStopPolicy(
                trigger_pct=25.0,
                refuel_to_pct=90.0,
                stop_duration_minutes=20.0,
            ),
            movement_interval_seconds=600.0,
            base_consumption_pct_per_100km=2.5,
            eta_event_threshold_min=1.0,
        )
        all_shipments.append(fuel_result.shipment)
        all_telemetry.extend(fuel_result.telemetry_samples)
        all_events.extend(fuel_result.events)

        # 6) Reefer exception is persisted under same run using a fresh shipment id.
        reefer_shipment_id = writer.allocate_shipment_id()
        reefer_origin = contention_origin
        reefer_dest = contention_dest
        reefer_vehicle = state_for(reefer_profile, reefer_origin)
        reefer_result = run_reefer_exception_shipment(
            context=SimulationContext(
                simulation_start=start,
                simulation_end=end,
                seed=42,
                run_id=run_id,
            ),
            plan=ReeferShipmentPlan(
                shipment_id=reefer_shipment_id,
                vehicle_id=reefer_vehicle.profile.vehicle_id,
                route=contention_route,
                cargo=reefer_cargo,
            ),
            vehicle=reefer_vehicle,
            origin=reefer_origin,
            destination=reefer_dest,
            policy=ReeferTemperaturePolicy(
                min_temp_c=reefer_cargo.min_temp_c or 1.0,
                max_temp_c=reefer_cargo.max_temp_c or 8.0,
                recovery_temp_c=reefer_cargo.target_temp_c or 4.0,
            ),
            excursion=TemperatureExcursion(
                start_time=start + timedelta(minutes=30),
                end_time=start + timedelta(minutes=90),
                excursion_temp_c=12.0,
            ),
            normal_cargo_temp_c=reefer_cargo.target_temp_c or 4.0,
            movement_interval_seconds=600.0,
            base_consumption_pct_per_100km=1.0,
            eta_event_threshold_min=1.0,
        )
        all_shipments.append(reefer_result.shipment)
        all_telemetry.extend(reefer_result.telemetry_samples)
        all_events.extend(reefer_result.events)

        # Persist everything under one run.
        writer.insert_shipments(all_shipments)
        writer.insert_fleet_telemetry(
            (
                sample.time,
                sample.row,
                run_id,
            )
            for sample in all_telemetry
        )
        writer.insert_events(all_events)
        writer.insert_warehouse_operations(
            (
                sample.time,
                sample.row,
                run_id,
            )
            for sample in all_warehouse_samples
        )
        writer.update_simulation_run_status(run_id, "COMPLETED")

        counts = {
            "TRAFFIC_CONGESTION": 0,
            "HEAVY_RAIN": 0,
            "MECHANICAL_BREAKDOWN": 0,
            "LOW_FUEL_REFUEL": 0,
            "REEFER_TEMP_EXCURSION": 0,
        }
        for event in all_events:
            if event.cause_code in counts:
                counts[event.cause_code] += 1

        print(
            "[Supply Chain v3] Final mixed integration passed: "
            f"run_id={run_id}, "
            f"shipments={len(all_shipments)}, "
            f"fleet_telemetry_rows={len(all_telemetry)}, "
            f"warehouse_rows={len(all_warehouse_samples)}, "
            f"events={len(all_events)}, "
            f"traffic_events={counts['TRAFFIC_CONGESTION']}, "
            f"weather_events={counts['HEAVY_RAIN']}, "
            f"mechanical_events={counts['MECHANICAL_BREAKDOWN']}, "
            f"fuel_events={counts['LOW_FUEL_REFUEL']}, "
            f"reefer_events={counts['REEFER_TEMP_EXCURSION']}"
        )

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
