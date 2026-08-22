-- Representative Supply Chain V3 analytics.

-- Latest telemetry for each vehicle in a selected run.
-- Replace 41 with a run_id from sc_simulation_runs.
SELECT DISTINCT ON (vehicle_id)
    vehicle_id,
    shipment_id,
    time,
    speed_kmh,
    fuel_level_pct,
    cargo_temp_c
FROM sc_fleet_telemetry
WHERE run_id = 41
ORDER BY vehicle_id, time DESC;

-- Disruption coverage by cause.
SELECT
    cause_code,
    COUNT(*) AS event_count,
    COUNT(DISTINCT shipment_id) AS shipments_affected
FROM sc_events
WHERE cause_code IS NOT NULL
GROUP BY cause_code
ORDER BY event_count DESC;

-- Five-minute fleet speed profile using TimescaleDB.
SELECT
    time_bucket('5 minutes', time) AS bucket,
    vehicle_id,
    AVG(speed_kmh) AS avg_speed_kmh,
    MAX(speed_kmh) AS max_speed_kmh
FROM sc_fleet_telemetry
GROUP BY bucket, vehicle_id
ORDER BY bucket, vehicle_id;
