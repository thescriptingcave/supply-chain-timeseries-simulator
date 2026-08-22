-- Replace 15 below if the integration prints a different run_id.

-- 1. Fuel-stop event chronology.
SELECT
    time,
    event_type,
    cause_code,
    severity,
    detail_json
FROM sc_events
WHERE run_id = 15
ORDER BY time, event_id;

-- 2. Fuel-stop causal event counts.
SELECT
    event_type,
    COUNT(*) AS event_count
FROM sc_events
WHERE run_id = 15
  AND cause_code = 'LOW_FUEL_REFUEL'
GROUP BY event_type
ORDER BY event_type;

-- 3. Fuel behavior around the stop.
WITH bounds AS (
    SELECT
        MIN(time) FILTER (
            WHERE event_type = 'FUEL_STOP_STARTED'
        ) AS stop_start,
        MIN(time) FILTER (
            WHERE event_type = 'FUEL_STOP_ENDED'
        ) AS stop_end
    FROM sc_events
    WHERE run_id = 15
)
SELECT
    t.time,
    t.speed_kmh,
    t.fuel_level_pct,
    t.odometer_km
FROM sc_fleet_telemetry t
CROSS JOIN bounds b
WHERE t.run_id = 15
  AND t.time >= b.stop_start - INTERVAL '20 minutes'
  AND t.time <= b.stop_end + INTERVAL '20 minutes'
ORDER BY t.time;

-- 4. Duplicate telemetry timestamps. Expected: 0.
SELECT COUNT(*) AS duplicate_timestamp_groups
FROM (
    SELECT time, COUNT(*) AS rows_at_time
    FROM sc_fleet_telemetry
    WHERE run_id = 15
    GROUP BY time
    HAVING COUNT(*) > 1
) d;
