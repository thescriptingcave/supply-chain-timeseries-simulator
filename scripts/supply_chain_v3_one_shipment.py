"""One-shipment TimescaleDB integration gate for Supply Chain v3.

Run from the repository root:

    uv run python -m scripts.supply_chain_v3_one_shipment

This intentionally generates exactly one shipment and its fleet telemetry.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg2

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.db_writer import SupplyChainWriter
from generators.supply_chain.engine import execute_single_shipment
from generators.supply_chain.models import (
    CargoProfile,
    Priority,
    RouteProfile,
    RouteState,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.persistence import SimulationRunRecord


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


def load_route(cur, route_id: int) -> RouteProfile:
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
        WHERE route_id = %s
          AND active = true
        """,
        (route_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"route_id={route_id} not found")

    return RouteProfile(
        route_id=row[0],
        origin_wh_id=row[1],
        dest_wh_id=row[2],
        distance_km=float(row[3]),
        nominal_speed_kmh=float(row[4]),
        minimum_speed_kmh=float(row[5]),
        maximum_speed_kmh=float(row[6]),
        baseline_travel_min=float(row[7]),
        congestion_sensitivity=float(row[8]),
        weather_sensitivity=float(row[9]),
        morning_peak_factor=float(row[10]),
        evening_peak_factor=float(row[11]),
        overnight_factor=float(row[12]),
        demand_weight=float(row[13]),
        disruption_probability=float(row[14]),
    )


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
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"warehouse_id={warehouse_id} not found")

    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=row[0],
            warehouse_name=row[1],
            lat=float(row[2]),
            lon=float(row[3]),
            timezone=row[4],
            loading_capacity=row[5],
            unloading_capacity=row[6],
            baseline_loading_min=float(row[7]),
            baseline_unloading_min=float(row[8]),
            congestion_sensitivity=float(row[9]),
            cold_storage_capable=row[10],
        )
    )


def load_vehicle(cur, origin_wh_id: int) -> VehicleState:
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
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("no vehicles found")

    profile = VehicleProfile(
        vehicle_id=row[0],
        vehicle_reg=row[1],
        vehicle_type=row[2],
        max_payload_kg=float(row[3]) if row[3] is not None else None,
        fuel_type=row[4],
        fleet_operator=row[5],
        year_manufactured=row[6],
        fuel_efficiency_factor=float(row[7]),
        reliability_factor=float(row[8]),
        condition_factor=float(row[9]),
        cruise_speed_factor=float(row[10]),
        maintenance_risk_factor=float(row[11]),
        reefer_capable=row[12],
    )

    return VehicleState(
        profile=profile,
        current_warehouse_id=origin_wh_id,
        lat=0.0,
        lon=0.0,
        fuel_level_pct=95.0,
        odometer_km=100000.0,
    )


def load_cargo(cur, cargo_type: str) -> CargoProfile:
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
        WHERE cargo_type = %s
          AND active = true
        """,
        (cargo_type,),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"cargo_type={cargo_type} not found")

    return CargoProfile(
        cargo_type=row[0],
        requires_reefer=row[1],
        target_temp_c=float(row[2]) if row[2] is not None else None,
        min_temp_c=float(row[3]) if row[3] is not None else None,
        max_temp_c=float(row[4]) if row[4] is not None else None,
        target_humidity_pct=float(row[5]) if row[5] is not None else None,
        handling_sensitivity=float(row[6]),
        loading_time_factor=float(row[7]),
    )


def main() -> None:
    start = datetime.now(timezone.utc).replace(microsecond=0)
    end = start + timedelta(days=2)

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
                    "purpose": "one-shipment-integration-gate",
                    "movement_interval_seconds": 600,
                },
            )
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT route_id
                FROM sc_routes
                WHERE active = true
                ORDER BY route_id
                LIMIT 1
                """
            )
            route_row = cur.fetchone()
            if route_row is None:
                raise RuntimeError("no active routes found")

            route = load_route(cur, route_row[0])
            origin = load_warehouse(cur, route.origin_wh_id)
            destination = load_warehouse(cur, route.dest_wh_id)
            vehicle = load_vehicle(cur, route.origin_wh_id)
            cargo = load_cargo(cur, "GENERAL_FREIGHT")

        # Make the runtime vehicle position consistent with the selected origin.
        vehicle.lat = origin.profile.lat
        vehicle.lon = origin.profile.lon

        shipment_id = writer.allocate_shipment_id()

        context = SimulationContext(
            simulation_start=start,
            simulation_end=end,
            seed=42,
            run_id=run_id,
        )

        result = execute_single_shipment(
            context=context,
            route=route,
            route_state=RouteState(profile=route),
            vehicles=[vehicle],
            origin_warehouse=origin,
            destination_warehouse=destination,
            cargo=cargo,
            priority=Priority.STANDARD,
            shipment_id=shipment_id,
            movement_interval_seconds=600.0,
        )

        inserted_shipments = writer.insert_shipments([result.shipment])

        fleet_samples = (
            (sample.time, sample.row, run_id)
            for sample in result.telemetry_samples
        )
        inserted_telemetry = writer.insert_fleet_telemetry(fleet_samples)
        inserted_events = writer.insert_events(result.events)

        writer.update_simulation_run_status(run_id, "COMPLETED")

        print(
            "[Supply Chain v3] One-shipment integration passed: "
            f"run_id={run_id}, "
            f"shipment_id={shipment_id}, "
            f"shipments={inserted_shipments}, "
            f"telemetry_rows={inserted_telemetry}, events={inserted_events}"
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
