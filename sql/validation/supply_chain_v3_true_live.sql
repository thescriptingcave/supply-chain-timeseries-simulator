-- Supply Chain V3 true-live validation.
-- Replace :run_id with the new live run id.

-- 1. No future-dated telemetry. Expected: 0.
SELECT COUNT(*) AS future_telemetry_rows
FROM sc_fleet_telemetry
WHERE run_id = :run_id
  AND time > NOW() + INTERVAL '5 seconds';

-- 2. Duplicate vehicle/time invariant. Expected: 0.
SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS row_count
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;

-- 3. Observe live cadence.
SELECT
    time,
    vehicle_id,
    shipment_id,
    speed_kmh,
    fuel_level_pct,
    odometer_km
FROM sc_fleet_telemetry
WHERE run_id = :run_id
ORDER BY time DESC, vehicle_id
LIMIT 30;

-- 4. Shipment lifecycle should remain IN_TRANSIT until actual arrival.
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

-- 5. Event chronology.
SELECT
    time,
    shipment_id,
    event_type,
    cause_code,
    severity
FROM sc_events
WHERE run_id = :run_id
ORDER BY time, shipment_id;
