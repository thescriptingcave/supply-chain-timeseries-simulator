-- Supply Chain V3 monotonic-scheduler validation.
-- Replace :run_id with the new live run id.

-- 1. Future-dated telemetry must remain zero.
SELECT COUNT(*) AS future_telemetry_rows
FROM sc_fleet_telemetry
WHERE run_id = :run_id
  AND time > NOW() + INTERVAL '5 seconds';

-- 2. Duplicate vehicle/time groups must remain zero.
SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS row_count
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;

-- 3. Cadence distribution.
WITH samples AS (
    SELECT
        vehicle_id,
        shipment_id,
        time,
        LAG(time) OVER (
            PARTITION BY vehicle_id, shipment_id
            ORDER BY time
        ) AS previous_time
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
)
SELECT
    EXTRACT(EPOCH FROM (time - previous_time))::integer
        AS seconds_between_samples,
    COUNT(*) AS intervals
FROM samples
WHERE previous_time IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- 4. Active lifecycle check.
SELECT
    shipment_id,
    vehicle_id,
    lifecycle_status,
    actual_departure,
    actual_arrival,
    estimated_arrival
FROM sc_shipments
WHERE run_id = :run_id
ORDER BY shipment_id;
