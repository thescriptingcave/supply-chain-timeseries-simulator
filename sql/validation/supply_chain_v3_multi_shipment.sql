-- Supply Chain v3 multi-shipment integration validation.
-- Replace :run_id with the printed run id.

-- Shipment chain
SELECT
    shipment_id,
    vehicle_id,
    origin_wh_id,
    dest_wh_id,
    lifecycle_status,
    scheduled_departure,
    actual_departure,
    actual_arrival,
    delivery_completed_at
FROM sc_shipments
WHERE run_id = :run_id
ORDER BY scheduled_departure;

-- Overlap check. Expected: 0
WITH ordered AS (
    SELECT
        shipment_id,
        vehicle_id,
        actual_departure,
        delivery_completed_at,
        LAG(delivery_completed_at) OVER (
            PARTITION BY vehicle_id
            ORDER BY actual_departure
        ) AS previous_delivery
    FROM sc_shipments
    WHERE run_id = :run_id
)
SELECT COUNT(*) AS overlapping_shipments
FROM ordered
WHERE previous_delivery IS NOT NULL
  AND actual_departure < previous_delivery;

-- Route continuity check. Expected: 0
WITH ordered AS (
    SELECT
        shipment_id,
        vehicle_id,
        origin_wh_id,
        dest_wh_id,
        LAG(dest_wh_id) OVER (
            PARTITION BY vehicle_id
            ORDER BY actual_departure
        ) AS previous_destination
    FROM sc_shipments
    WHERE run_id = :run_id
)
SELECT COUNT(*) AS route_continuity_violations
FROM ordered
WHERE previous_destination IS NOT NULL
  AND origin_wh_id <> previous_destination;

-- Telemetry continuity by shipment
SELECT
    shipment_id,
    COUNT(*) AS telemetry_rows,
    MIN(fuel_level_pct) AS min_fuel,
    MAX(fuel_level_pct) AS max_fuel,
    MIN(odometer_km) AS min_odometer,
    MAX(odometer_km) AS max_odometer
FROM sc_fleet_telemetry
WHERE run_id = :run_id
GROUP BY shipment_id
ORDER BY shipment_id;

-- Event chronology violations. Expected: 0
WITH event_times AS (
    SELECT
        shipment_id,
        MIN(time) FILTER (WHERE event_type='DEPARTURE') AS departure_time,
        MIN(time) FILTER (WHERE event_type='ARRIVAL') AS arrival_time,
        MIN(time) FILTER (WHERE event_type='DELIVERY') AS delivery_time
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
