-- Final mixed-scenario validation for Supply Chain v3.
-- Replace :run_id with the run id printed by the integration runner.

-- 1. Run status.
SELECT
    run_id,
    status,
    simulation_start,
    simulation_end,
    metadata_json
FROM sc_simulation_runs
WHERE run_id = :run_id;

-- 2. All shipments should be delivered.
SELECT
    lifecycle_status,
    COUNT(*) AS shipment_count
FROM sc_shipments
WHERE run_id = :run_id
GROUP BY lifecycle_status
ORDER BY lifecycle_status;

-- 3. Required causal event families must all exist.
SELECT
    cause_code,
    COUNT(*) AS event_count
FROM sc_events
WHERE run_id = :run_id
  AND cause_code IN (
      'TRAFFIC_CONGESTION',
      'HEAVY_RAIN',
      'MECHANICAL_BREAKDOWN',
      'LOW_FUEL_REFUEL',
      'REEFER_TEMP_EXCURSION'
  )
GROUP BY cause_code
ORDER BY cause_code;

-- 4. Warehouse contention must exist.
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

-- Expected: max_queue_depth > 0, max_state_level = 3.

-- 5. Mechanical stop must have zero-speed samples.
SELECT COUNT(*) AS zero_speed_samples
FROM sc_fleet_telemetry
WHERE run_id = :run_id
  AND speed_kmh = 0;

-- Expected: > 0.

-- 6. Reefer excursion must exist in telemetry.
SELECT
    MAX(cargo_temp_c) AS max_cargo_temp_c,
    COUNT(*) FILTER (WHERE cargo_temp_c > 8.0) AS excursion_samples
FROM sc_fleet_telemetry
WHERE run_id = :run_id;

-- Expected: max_cargo_temp_c >= 12, excursion_samples > 0.

-- 7. No duplicate telemetry timestamps within the same vehicle.
SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS row_count
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;

-- Expected: 0.

-- 8. Basic row counts.
SELECT
    (SELECT COUNT(*) FROM sc_shipments WHERE run_id = :run_id) AS shipments,
    (SELECT COUNT(*) FROM sc_fleet_telemetry WHERE run_id = :run_id) AS telemetry_rows,
    (SELECT COUNT(*) FROM sc_events WHERE run_id = :run_id) AS events,
    (SELECT COUNT(*) FROM sc_warehouse_operations WHERE run_id = :run_id) AS warehouse_rows;
