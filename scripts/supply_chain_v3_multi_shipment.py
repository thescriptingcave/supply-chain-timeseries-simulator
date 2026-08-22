"""Small persisted multi-shipment integration run for Supply Chain v3.

Run from repository root:

    uv run python -m scripts.supply_chain_v3_multi_shipment
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg2

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.db_writer import SupplyChainWriter
from generators.supply_chain.models import CargoProfile, Priority, RouteProfile, VehicleProfile, VehicleState, WarehouseProfile, WarehouseState
from generators.supply_chain.multi_shipment import execute_sequential_shipments
from generators.supply_chain.persistence import SimulationRunRecord


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


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

    return [
        RouteProfile(
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
        for row in cur.fetchall()
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

    warehouses = {}
    for row in cur.fetchall():
        warehouses[row[0]] = WarehouseState(
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
    return warehouses


def load_vehicle(cur, origin_wh_id: int, origin_lat: float, origin_lon: float) -> VehicleState:
    cur.execute(
        """
        SELECT
            vehicle_id, vehicle_reg, vehicle_type, max_payload_kg,
            fuel_type, fleet_operator, year_manufactured,
            fuel_efficiency_factor, reliability_factor, condition_factor,
            cruise_speed_factor, maintenance_risk_factor, reefer_capable
        FROM sc_vehicles
        ORDER BY vehicle_id
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("no vehicles found")

    return VehicleState(
        profile=VehicleProfile(
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
        ),
        current_warehouse_id=origin_wh_id,
        lat=origin_lat,
        lon=origin_lon,
        fuel_level_pct=95.0,
        odometer_km=100000.0,
    )


def load_cargo(cur) -> CargoProfile:
    cur.execute(
        """
        SELECT
            cargo_type, requires_reefer, target_temp_c, min_temp_c, max_temp_c,
            target_humidity_pct, handling_sensitivity, loading_time_factor
        FROM sc_cargo_profiles
        WHERE cargo_type = 'GENERAL_FREIGHT'
          AND active = true
        """
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("GENERAL_FREIGHT cargo profile not found")

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
    end = start + timedelta(days=5)

    conn = psycopg2.connect(DB_URL)
    run_id = None

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
                    "purpose": "multi-shipment-integration-gate",
                    "shipment_count": 4,
                    "mode": "sequential",
                },
            )
        )

        with conn.cursor() as cur:
            routes = load_routes(cur)
            warehouses = load_warehouses(cur)
            cargo = load_cargo(cur)

        # Deterministic start: warehouse 1.
        origin = warehouses[1]
        vehicle = load_vehicle(
            conn.cursor(),
            origin_wh_id=1,
            origin_lat=origin.profile.lat,
            origin_lon=origin.profile.lon,
        )

        shipment_ids = [writer.allocate_shipment_id() for _ in range(4)]

        context = SimulationContext(
            simulation_start=start,
            simulation_end=end,
            seed=42,
            run_id=run_id,
        )

        result = execute_sequential_shipments(
            context=context,
            routes=routes,
            warehouses=warehouses,
            vehicles=[vehicle],
            cargo=cargo,
            shipment_ids=shipment_ids,
            priority=Priority.STANDARD,
            movement_interval_seconds=600.0,
            base_consumption_pct_per_100km=1.5,
        )

        writer.insert_shipments(
            shipment_result.shipment
            for shipment_result in result.shipments
        )

        writer.insert_fleet_telemetry(
            (
                sample.time,
                sample.row,
                run_id,
            )
            for shipment_result in result.shipments
            for sample in shipment_result.telemetry_samples
        )

        writer.insert_events(
            event
            for shipment_result in result.shipments
            for event in shipment_result.events
        )

        writer.update_simulation_run_status(run_id, "COMPLETED")

        print(
            "[Supply Chain v3] Multi-shipment integration passed: "
            f"run_id={run_id}, shipments={len(result.shipments)}, "
            f"telemetry_rows={result.total_telemetry_rows}, "
            f"events={result.total_events}, "
            f"final_vehicle_warehouse={vehicle.current_warehouse_id}, "
            f"final_fuel={vehicle.fuel_level_pct:.2f}, "
            f"final_odometer={vehicle.odometer_km:.2f}"
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
