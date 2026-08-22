-- Supply Chain v3 concurrent-contention integration validation.
-- Replace :run_id with the run id printed by the integration runner.

-- 1. Shipments and staggered departure/delivery times.
SELECT
    shipment_id,
    vehicle_id,
    route_id,
    origin_wh_id,
    dest_wh_id,
    lifecycle_status,
    scheduled_departure,
    actual_departure,
    actual_arrival,
    delivery_completed_at
FROM sc_shipments
WHERE run_id = :run_id
ORDER BY actual_departure, shipment_id;

-- 2. Loading contention should stagger actual departures.
SELECT
    COUNT(DISTINCT actual_departure) AS distinct_departure_times,
    COUNT(*) AS shipment_count
FROM sc_shipments
WHERE run_id = :run_id;

-- Expected: distinct_departure_times > 1

-- 3. All shipments must be delivered.
SELECT COUNT(*) AS not_delivered
FROM sc_shipments
WHERE run_id = :run_id
  AND lifecycle_status <> 'DELIVERED';

-- Expected: 0

-- 4. Warehouse queue/congestion telemetry.
SELECT
    warehouse_id,
    COUNT(*) AS samples,
    MAX(queue_depth) AS max_queue_depth,
    MAX(loading_bays_active) AS max_loading_active,
    MAX(unloading_bays_active) AS max_unloading_active,
    MAX(congestion_factor) AS max_congestion_factor
FROM sc_warehouse_operations
WHERE run_id = :run_id
GROUP BY warehouse_id
ORDER BY warehouse_id;

-- 5. We expect at least one queued sample.
SELECT COUNT(*) AS queued_samples
FROM sc_warehouse_operations
WHERE run_id = :run_id
  AND queue_depth > 0;

-- Expected: > 0

-- 6. Runtime capacity must be respected.
SELECT COUNT(*) AS capacity_violations
FROM sc_warehouse_operations
WHERE run_id = :run_id
  AND (
      loading_bays_active > 1
      OR unloading_bays_active > 1
  );

-- Expected: 0

-- 7. Event chronology.
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

-- Expected: 0

-- 8. Fleet telemetry remains tied to valid persisted shipments.
SELECT COUNT(*) AS invalid_fleet_refs
FROM sc_fleet_telemetry t
LEFT JOIN sc_shipments s
  ON s.run_id = t.run_id
 AND s.shipment_id = t.shipment_id
WHERE t.run_id = :run_id
  AND s.shipment_id IS NULL;

-- Expected: 0
