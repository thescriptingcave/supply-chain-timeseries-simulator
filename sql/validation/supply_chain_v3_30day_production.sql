-- Supply Chain v3 30-day production-profile validation.
-- Replace :run_id with the printed run id.

-- 1. Run status and metadata.
SELECT
    run_id,
    status,
    simulation_start,
    simulation_end,
    metadata_json
FROM sc_simulation_runs
WHERE run_id = 23;

-- 2. Shipment terminal states.
SELECT
    lifecycle_status,
    COUNT(*) AS shipments
FROM sc_shipments
WHERE run_id = 23
GROUP BY lifecycle_status
ORDER BY lifecycle_status;

-- 3. Event-family distribution.
SELECT
    cause_code,
    COUNT(*) AS events
FROM sc_events
WHERE run_id = 23
  AND cause_code IS NOT NULL
GROUP BY cause_code
ORDER BY cause_code;

-- 4. Telemetry summary.
SELECT
    COUNT(*) AS telemetry_rows,
    COUNT(DISTINCT vehicle_id) AS vehicles,
    MIN(time) AS first_sample,
    MAX(time) AS last_sample,
    ROUND(AVG(speed_kmh), 2) AS avg_speed_kmh,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY speed_kmh)::numeric, 2) AS median_speed_kmh,
    ROUND(MIN(fuel_level_pct), 2) AS min_fuel_pct,
    ROUND(MAX(cargo_temp_c), 2) AS max_cargo_temp_c
FROM sc_fleet_telemetry
WHERE run_id = 23;

-- 5. Vehicle/timestamp uniqueness invariant. Expected: 0.
SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS rows_at_time
    FROM sc_fleet_telemetry
    WHERE run_id = 23
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;

-- 6. Warehouse pressure.
SELECT
    MAX(queue_depth) AS max_queue_depth,
    ROUND(MAX(congestion_factor), 3) AS max_congestion_factor,
    COUNT(*) FILTER (WHERE operating_state = 'CONGESTED') AS congested_samples
FROM sc_warehouse_operations
WHERE run_id = 23;

-- 7. Per-vehicle workload.
SELECT
    vehicle_id,
    COUNT(DISTINCT shipment_id) AS shipments,
    COUNT(*) AS telemetry_rows,
    MIN(time) AS first_sample,
    MAX(time) AS last_sample
FROM sc_fleet_telemetry
WHERE run_id = 23
GROUP BY vehicle_id
ORDER BY vehicle_id;

-- 8. Shipment duration distribution.
SELECT
    ROUND(AVG(EXTRACT(EPOCH FROM (actual_arrival - actual_departure)) / 3600.0)::numeric, 2) AS avg_trip_hours,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (actual_arrival - actual_departure)) / 3600.0
    )::numeric, 2) AS median_trip_hours,
    ROUND(MAX(EXTRACT(EPOCH FROM (actual_arrival - actual_departure)) / 3600.0)::numeric, 2) AS max_trip_hours
FROM sc_shipments
WHERE run_id = 23
  AND actual_departure IS NOT NULL
  AND actual_arrival IS NOT NULL;
