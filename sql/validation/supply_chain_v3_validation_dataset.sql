-- Supply Chain v3 2-day validation dataset.
-- Replace :run_id with the printed run id.

-- 1. Run status.
SELECT run_id, status, simulation_start, simulation_end, metadata_json
FROM sc_simulation_runs
WHERE run_id = :run_id;

-- 2. Shipment completion.
SELECT lifecycle_status, COUNT(*) AS shipments
FROM sc_shipments
WHERE run_id = :run_id
GROUP BY lifecycle_status
ORDER BY lifecycle_status;

-- 3. Causal event distribution.
SELECT cause_code, COUNT(*) AS events
FROM sc_events
WHERE run_id = :run_id
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
    ROUND(MIN(fuel_level_pct), 2) AS min_fuel_pct,
    ROUND(MAX(cargo_temp_c), 2) AS max_cargo_temp_c
FROM sc_fleet_telemetry
WHERE run_id = :run_id;

-- 5. Duplicate timestamp invariant.
SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS rows_at_time
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;

-- Expected: 0.

-- 6. Warehouse contention.
SELECT
    MAX(queue_depth) AS max_queue_depth,
    MAX(congestion_factor) AS max_congestion_factor,
    MAX(
        CASE operating_state
            WHEN 'NORMAL' THEN 1
            WHEN 'BUSY' THEN 2
            WHEN 'CONGESTED' THEN 3
        END
    ) AS max_state_level
FROM sc_warehouse_operations
WHERE run_id = :run_id;

-- 7. Event chronology by shipment.
SELECT
    shipment_id,
    MIN(time) AS first_event,
    MAX(time) AS last_event,
    COUNT(*) AS event_count
FROM sc_events
WHERE run_id = :run_id
GROUP BY shipment_id
ORDER BY shipment_id;
