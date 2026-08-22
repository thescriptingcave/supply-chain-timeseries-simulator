-- Supply Chain V3 true-live reefer validation.
-- Replace :run_id with the live run id.

-- 1. Reefer causal events.
SELECT
    time,
    shipment_id,
    event_type,
    cause_code,
    severity,
    detail_json
FROM sc_events
WHERE run_id = :run_id
  AND cause_code = 'REEFER_TEMP_EXCURSION'
ORDER BY time, event_type;

-- 2. Cargo temperature before / during / after excursion.
WITH reefer_window AS (
    SELECT
        shipment_id,
        MIN(time) FILTER (
            WHERE event_type = 'CARGO_EXCEPTION_STARTED'
        ) AS started_at,
        MIN(time) FILTER (
            WHERE event_type = 'CARGO_EXCEPTION_ENDED'
        ) AS ended_at
    FROM sc_events
    WHERE run_id = :run_id
      AND cause_code = 'REEFER_TEMP_EXCURSION'
    GROUP BY shipment_id
),
samples AS (
    SELECT
        t.shipment_id,
        t.time,
        t.speed_kmh,
        t.cargo_temp_c,
        CASE
            WHEN t.time < w.started_at THEN 'BEFORE'
            WHEN w.ended_at IS NOT NULL
                 AND t.time >= w.ended_at THEN 'AFTER'
            ELSE 'DURING'
        END AS phase
    FROM sc_fleet_telemetry t
    JOIN reefer_window w USING (shipment_id)
    WHERE t.run_id = :run_id
)
SELECT
    phase,
    COUNT(*) AS samples,
    ROUND(AVG(speed_kmh), 2) AS avg_speed_kmh,
    ROUND(AVG(cargo_temp_c), 2) AS avg_cargo_temp_c,
    ROUND(MIN(cargo_temp_c), 2) AS min_cargo_temp_c,
    ROUND(MAX(cargo_temp_c), 2) AS max_cargo_temp_c
FROM samples
GROUP BY phase
ORDER BY CASE phase
    WHEN 'BEFORE' THEN 1
    WHEN 'DURING' THEN 2
    ELSE 3
END;

-- 3. During the excursion, speed should remain > 0 for a moving shipment.
WITH reefer_window AS (
    SELECT
        shipment_id,
        MIN(time) FILTER (WHERE event_type='CARGO_EXCEPTION_STARTED') AS started_at,
        MIN(time) FILTER (WHERE event_type='CARGO_EXCEPTION_ENDED') AS ended_at
    FROM sc_events
    WHERE run_id = :run_id
      AND cause_code = 'REEFER_TEMP_EXCURSION'
    GROUP BY shipment_id
)
SELECT
    COUNT(*) AS zero_speed_excursion_rows
FROM sc_fleet_telemetry t
JOIN reefer_window w USING (shipment_id)
WHERE t.run_id = :run_id
  AND t.time >= w.started_at
  AND t.time < w.ended_at
  AND t.speed_kmh = 0;

-- 4. Live invariants.
SELECT COUNT(*) AS future_telemetry_rows
FROM sc_fleet_telemetry
WHERE run_id = :run_id
  AND time > NOW() + INTERVAL '5 seconds';

SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS row_count
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;
