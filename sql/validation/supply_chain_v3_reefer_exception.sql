-- Supply Chain v3 reefer exception validation.
-- Replace :run_id with the run id printed by the integration runner.

-- 1. Event chronology.
SELECT
    time,
    event_type,
    cause_code,
    severity,
    detail_json
FROM sc_events
WHERE run_id = :run_id
ORDER BY time, event_id;

-- 2. Reefer exception boundary events.
SELECT
    event_type,
    COUNT(*) AS event_count
FROM sc_events
WHERE run_id = :run_id
  AND cause_code = 'REEFER_TEMP_EXCURSION'
GROUP BY event_type
ORDER BY event_type;

-- Expected:
-- CARGO_EXCEPTION_STARTED = 1
-- CARGO_EXCEPTION_ENDED   = 1

-- 3. Temperature before/during/after the excursion.
WITH bounds AS (
    SELECT
        MIN(time) FILTER (
            WHERE event_type = 'CARGO_EXCEPTION_STARTED'
        ) AS exception_start,
        MIN(time) FILTER (
            WHERE event_type = 'CARGO_EXCEPTION_ENDED'
        ) AS exception_end
    FROM sc_events
    WHERE run_id = :run_id
      AND cause_code = 'REEFER_TEMP_EXCURSION'
),
phased AS (
    SELECT
        CASE
            WHEN t.time < b.exception_start THEN 'BEFORE'
            WHEN t.time < b.exception_end THEN 'DURING'
            ELSE 'AFTER'
        END AS phase,
        t.cargo_temp_c,
        t.speed_kmh
    FROM sc_fleet_telemetry t
    CROSS JOIN bounds b
    WHERE t.run_id = :run_id
)
SELECT
    phase,
    COUNT(*) AS samples,
    ROUND(AVG(cargo_temp_c), 2) AS avg_cargo_temp_c,
    ROUND(MIN(cargo_temp_c), 2) AS min_cargo_temp_c,
    ROUND(MAX(cargo_temp_c), 2) AS max_cargo_temp_c,
    ROUND(AVG(speed_kmh), 2) AS avg_speed_kmh
FROM phased
GROUP BY phase
ORDER BY
    CASE phase
        WHEN 'BEFORE' THEN 1
        WHEN 'DURING' THEN 2
        ELSE 3
    END;

-- Expected:
-- BEFORE/AFTER near target temperature.
-- DURING above the allowed maximum.
-- Vehicle speed remains > 0 during the exception.

-- 4. No stopped vehicle samples during cargo exception.
WITH bounds AS (
    SELECT
        MIN(time) FILTER (
            WHERE event_type = 'CARGO_EXCEPTION_STARTED'
        ) AS exception_start,
        MIN(time) FILTER (
            WHERE event_type = 'CARGO_EXCEPTION_ENDED'
        ) AS exception_end
    FROM sc_events
    WHERE run_id = :run_id
      AND cause_code = 'REEFER_TEMP_EXCURSION'
)
SELECT COUNT(*) AS stopped_excursion_samples
FROM sc_fleet_telemetry t
CROSS JOIN bounds b
WHERE t.run_id = :run_id
  AND t.time >= b.exception_start
  AND t.time < b.exception_end
  AND t.speed_kmh <= 0;

-- Expected: 0

-- 5. No duplicate telemetry timestamps.
SELECT COUNT(*) AS duplicate_timestamp_groups
FROM (
    SELECT time, COUNT(*) AS rows_at_time
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
    GROUP BY time
    HAVING COUNT(*) > 1
) d;

-- Expected: 0
