-- Supply Chain v3 deterministic traffic disruption validation.
-- Replace :run_id with the printed run id.

-- 1. Shipment timing.
SELECT
    shipment_id,
    route_id,
    scheduled_departure,
    actual_departure,
    scheduled_arrival,
    estimated_arrival,
    actual_arrival,
    lifecycle_status
FROM sc_shipments
WHERE run_id = :run_id;

-- 2. Persisted traffic-causal events in chronological order.
SELECT
    time,
    event_type,
    cause_code,
    severity,
    shipment_id,
    vehicle_id,
    route_id,
    detail_json
FROM sc_events
WHERE run_id = :run_id
ORDER BY time, event_id;

-- 3. Required traffic boundary events. Expected: one each.
SELECT
    event_type,
    COUNT(*) AS event_count
FROM sc_events
WHERE run_id = :run_id
  AND cause_code = 'TRAFFIC_CONGESTION'
  AND event_type IN (
      'DISRUPTION_STARTED',
      'DISRUPTION_ENDED'
  )
GROUP BY event_type
ORDER BY event_type;

-- 4. At least one traffic-caused ETA update.
SELECT COUNT(*) AS traffic_eta_updates
FROM sc_events
WHERE run_id = :run_id
  AND event_type = 'ETA_UPDATED'
  AND cause_code = 'TRAFFIC_CONGESTION';

-- Expected: > 0

-- 5. Compare speed before, during and after the disruption window using the
-- persisted boundary-event timestamps.
WITH bounds AS (
    SELECT
        MIN(time) FILTER (
            WHERE event_type = 'DISRUPTION_STARTED'
        ) AS disruption_start,
        MIN(time) FILTER (
            WHERE event_type = 'DISRUPTION_ENDED'
        ) AS disruption_end
    FROM sc_events
    WHERE run_id = :run_id
      AND cause_code = 'TRAFFIC_CONGESTION'
)
SELECT
    CASE
        WHEN t.time < b.disruption_start THEN 'BEFORE'
        WHEN t.time < b.disruption_end THEN 'DURING'
        ELSE 'AFTER'
    END AS phase,
    COUNT(*) AS samples,
    ROUND(AVG(t.speed_kmh), 2) AS avg_speed_kmh
FROM sc_fleet_telemetry t
CROSS JOIN bounds b
WHERE t.run_id = :run_id
GROUP BY phase
ORDER BY
    CASE phase
        WHEN 'BEFORE' THEN 1
        WHEN 'DURING' THEN 2
        ELSE 3
    END;

-- Expected: DURING average speed lower than BEFORE/AFTER.

-- 6. Event chronology. Expected: 0.
WITH event_times AS (
    SELECT
        MIN(time) FILTER (
            WHERE event_type = 'DEPARTURE'
        ) AS departure_time,
        MIN(time) FILTER (
            WHERE event_type = 'DISRUPTION_STARTED'
        ) AS disruption_start,
        MIN(time) FILTER (
            WHERE event_type = 'DISRUPTION_ENDED'
        ) AS disruption_end,
        MIN(time) FILTER (
            WHERE event_type = 'ARRIVAL'
        ) AS arrival_time
    FROM sc_events
    WHERE run_id = :run_id
)
SELECT COUNT(*) AS invalid_disruption_chronology
FROM event_times
WHERE departure_time IS NULL
   OR disruption_start IS NULL
   OR disruption_end IS NULL
   OR arrival_time IS NULL
   OR NOT (
       departure_time <= disruption_start
       AND disruption_start < disruption_end
       AND disruption_end <= arrival_time
   );

-- 7. Traffic cause codes should never be missing from disruption events.
SELECT COUNT(*) AS missing_traffic_cause_codes
FROM sc_events
WHERE run_id = :run_id
  AND event_type IN (
      'DISRUPTION_STARTED',
      'DISRUPTION_ENDED'
  )
  AND cause_code IS NULL;

-- Expected: 0
