"""Persisted concurrent + warehouse-contention integration gate for Supply Chain v3.

Run from repository root:

    uv run python -m scripts.supply_chain_v3_concurrent_contention

This creates three shipments on the same route with three vehicles. Runtime
warehouse capacities are intentionally constrained to one loading bay at the
origin and one unloading bay at the destination so queueing is guaranteed.
Reference data in PostgreSQL is not modified.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import psycopg2

from generators.supply_chain.concurrent_contention import (
    ContendedShipmentPlan,
    run_concurrent_fleet_with_contention,
)
from generators.supply_chain.context import SimulationContext
from generators.supply_chain.db_writer import SupplyChainWriter
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


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


def load_route(cur) -> RouteProfile:
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
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("no active route found")

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


def constrained_runtime_warehouse(
    warehouse: WarehouseState,
    *,
    loading_capacity: int | None = None,
    unloading_capacity: int | None = None,
) -> WarehouseState:
    """Create a runtime-only capacity-constrained copy."""
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


def load_vehicles(
    cur,
    *,
    count: int,
    warehouse: WarehouseState,
) -> list[VehicleState]:
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
        raise RuntimeError(
            f"expected at least {count} vehicles, found {len(rows)}"
        )

    result: list[VehicleState] = []

    for row in rows:
        result.append(
            VehicleState(
                profile=VehicleProfile(
                    vehicle_id=row[0],
                    vehicle_reg=row[1],
                    vehicle_type=row[2],
                    max_payload_kg=(
                        float(row[3])
                        if row[3] is not None
                        else None
                    ),
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
                current_warehouse_id=warehouse.profile.warehouse_id,
                lat=warehouse.profile.lat,
                lon=warehouse.profile.lon,
                fuel_level_pct=95.0,
                odometer_km=100000.0 + (row[0] * 1000.0),
            )
        )

    return result


def load_cargo(cur) -> CargoProfile:
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
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("GENERAL_FREIGHT cargo profile not found")

    return CargoProfile(
        cargo_type=row[0],
        requires_reefer=row[1],
        target_temp_c=float(row[2]) if row[2] is not None else None,
        min_temp_c=float(row[3]) if row[3] is not None else None,
        max_temp_c=float(row[4]) if row[4] is not None else None,
        target_humidity_pct=(
            float(row[5])
            if row[5] is not None
            else None
        ),
        handling_sensitivity=float(row[6]),
        loading_time_factor=float(row[7]),
    )


def main() -> None:
    start = datetime.now(timezone.utc).replace(microsecond=0)
    end = start + timedelta(days=3)

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
                    "purpose": "concurrent-contention-integration-gate",
                    "vehicles": 3,
                    "runtime_origin_loading_capacity": 1,
                    "runtime_destination_unloading_capacity": 1,
                },
            )
        )

        with conn.cursor() as cur:
            route = load_route(cur)

            origin = load_warehouse(cur, route.origin_wh_id)
            destination = load_warehouse(cur, route.dest_wh_id)

            origin = constrained_runtime_warehouse(
                origin,
                loading_capacity=1,
            )
            destination = constrained_runtime_warehouse(
                destination,
                unloading_capacity=1,
            )

            cargo = load_cargo(cur)
            vehicles = load_vehicles(
                cur,
                count=3,
                warehouse=origin,
            )

        shipment_ids = [
            writer.allocate_shipment_id()
            for _ in range(3)
        ]

        plans = [
            ContendedShipmentPlan(
                shipment_id=shipment_id,
                vehicle_id=vehicle.profile.vehicle_id,
                route=route,
                cargo=cargo,
                priority=Priority.STANDARD,
            )
            for shipment_id, vehicle in zip(
                shipment_ids,
                vehicles,
                strict=True,
            )
        ]

        context = SimulationContext(
            simulation_start=start,
            simulation_end=end,
            seed=42,
            run_id=run_id,
        )

        result = run_concurrent_fleet_with_contention(
            context=context,
            plans=plans,
            vehicles=vehicles,
            warehouses={
                origin.profile.warehouse_id: origin,
                destination.profile.warehouse_id: destination,
            },
            movement_interval_seconds=600.0,
            warehouse_tick_seconds=60.0,
            base_consumption_pct_per_100km=1.0,
        )

        writer.insert_shipments(
            item.shipment
            for item in result.shipments
        )

        writer.insert_fleet_telemetry(
            (
                sample.time,
                sample.row,
                run_id,
            )
            for item in result.shipments
            for sample in item.telemetry_samples
        )

        writer.insert_events(
            event
            for item in result.shipments
            for event in item.events
        )

        warehouse_rows = writer.insert_warehouse_operations(
            (
                sample.time,
                sample.row,
                run_id,
            )
            for sample in result.warehouse_samples
        )

        writer.update_simulation_run_status(run_id, "COMPLETED")

        print(
            "[Supply Chain v3] Concurrent contention integration passed: "
            f"run_id={run_id}, "
            f"shipments={len(result.shipments)}, "
            f"fleet_telemetry_rows={result.fleet_telemetry_rows}, "
            f"warehouse_operation_rows={warehouse_rows}, "
            f"events={result.event_count}"
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
