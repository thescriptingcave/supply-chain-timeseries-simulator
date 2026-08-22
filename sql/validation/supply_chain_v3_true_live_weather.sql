-- Supply Chain V3 true-live weather validation.
-- Replace :run_id with the live run id.

-- 1. Weather causal event chain.
SELECT
    time,
    shipment_id,
    event_type,
    cause_code,
    severity,
    detail_json
FROM sc_events
WHERE run_id = 32 
  AND cause_code = 'HEAVY_RAIN'
ORDER BY time, event_type;

-- 2. Speed before / during / after weather.
WITH weather_window AS (
    SELECT
        shipment_id,
        MIN(time) FILTER (
            WHERE event_type = 'DISRUPTION_STARTED'
        ) AS started_at,
        MIN(time) FILTER (
            WHERE event_type = 'DISRUPTION_ENDED'
        ) AS ended_at
    FROM sc_events
    WHERE run_id = 32 
      AND cause_code = 'HEAVY_RAIN'
    GROUP BY shipment_id
),
samples AS (
    SELECT
        t.shipment_id,
        t.time,
        t.speed_kmh,
        CASE
            WHEN t.time < w.started_at THEN 'BEFORE'
            WHEN w.ended_at IS NOT NULL AND t.time >= w.ended_at THEN 'AFTER'
            ELSE 'DURING'
        END AS phase
    FROM sc_fleet_telemetry t
    JOIN weather_window w USING (shipment_id)
    WHERE t.run_id = 32 
)
SELECT
    phase,
    COUNT(*) AS samples,
    ROUND(AVG(speed_kmh), 2) AS avg_speed_kmh,
    ROUND(MIN(speed_kmh), 2) AS min_speed_kmh,
    ROUND(MAX(speed_kmh), 2) AS max_speed_kmh
FROM samples
GROUP BY phase
ORDER BY CASE phase
    WHEN 'BEFORE' THEN 1
    WHEN 'DURING' THEN 2
    ELSE 3
END;

-- 3. Live invariants.
SELECT COUNT(*) AS future_telemetry_rows
FROM sc_fleet_telemetry
WHERE run_id = 32 
  AND time > NOW() + INTERVAL '5 seconds';

SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS row_count
    FROM sc_fleet_telemetry
    WHERE run_id = 32 
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;
