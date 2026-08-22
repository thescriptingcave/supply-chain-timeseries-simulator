-- Validate persisted Supply Chain v3 events for a run.
-- Replace :run_id with the desired run id if needed.

SELECT
    event_type,
    COUNT(*) AS events
FROM sc_events
WHERE run_id = :run_id
GROUP BY event_type
ORDER BY event_type;

SELECT
    event_type,
    time,
    shipment_id,
    vehicle_id,
    route_id,
    cause_code,
    severity,
    detail_json
FROM sc_events
WHERE run_id = :run_id
ORDER BY time, event_id;

-- Core event chronology violations. Expected: 0
WITH event_times AS (
    SELECT
        shipment_id,
        MIN(time) FILTER (WHERE event_type = 'DEPARTURE') AS departure_time,
        MIN(time) FILTER (WHERE event_type = 'ARRIVAL') AS arrival_time,
        MIN(time) FILTER (WHERE event_type = 'DELIVERY') AS delivery_time
    FROM sc_events
    WHERE run_id = :run_id
    GROUP BY shipment_id
)
SELECT COUNT(*) AS invalid_event_chronology
FROM event_times
WHERE departure_time IS NULL
   OR arrival_time IS NULL
   OR delivery_time IS NULL
   OR NOT (
       departure_time < arrival_time
       AND arrival_time <= delivery_time
   );
