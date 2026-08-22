-- Supply Chain V3 mixed true-live validation.
-- Replace :run_id with the mixed live run id.

-- 1. Count each causal disruption/event family.
SELECT
    cause_code,
    COUNT(*) AS event_count,
    COUNT(DISTINCT shipment_id) AS shipments_affected
FROM sc_events
WHERE run_id = 40 
  AND cause_code IN (
      'TRAFFIC_CONGESTION',
      'HEAVY_RAIN',
      'MECHANICAL_BREAKDOWN',
      'LOW_FUEL_REFUEL',
      'REEFER_TEMP_EXCURSION'
  )
GROUP BY cause_code
ORDER BY cause_code;

-- 2. Show the complete causal event sequence.
SELECT
    time,
    shipment_id,
    vehicle_id,
    event_type,
    cause_code,
    severity
FROM sc_events
WHERE run_id = 40 
  AND cause_code IN (
      'TRAFFIC_CONGESTION',
      'HEAVY_RAIN',
      'MECHANICAL_BREAKDOWN',
      'LOW_FUEL_REFUEL',
      'REEFER_TEMP_EXCURSION'
  )
ORDER BY time, shipment_id, event_type;

-- 3. Per-shipment telemetry summary for the five mixed-demo shipments.
WITH affected AS (
    SELECT DISTINCT shipment_id
    FROM sc_events 
    WHERE run_id = 40
      AND cause_code IN (
          'TRAFFIC_CONGESTION',
          'HEAVY_RAIN',
          'MECHANICAL_BREAKDOWN',
          'LOW_FUEL_REFUEL',
          'REEFER_TEMP_EXCURSION'
      )
)
SELECT
    t.shipment_id,
    MIN(t.time) AS first_sample,
    MAX(t.time) AS last_sample,
    COUNT(*) AS telemetry_rows,
    ROUND(MIN(t.speed_kmh), 2) AS min_speed_kmh,
    ROUND(MAX(t.speed_kmh), 2) AS max_speed_kmh,
    ROUND(MIN(t.fuel_level_pct), 2) AS min_fuel_pct,
    ROUND(MAX(t.fuel_level_pct), 2) AS max_fuel_pct,
    ROUND(MIN(t.cargo_temp_c), 2) AS min_cargo_temp_c,
    ROUND(MAX(t.cargo_temp_c), 2) AS max_cargo_temp_c
FROM sc_fleet_telemetry t
JOIN affected a USING (shipment_id)
WHERE t.run_id = 40 
GROUP BY t.shipment_id
ORDER BY t.shipment_id;

-- 4. Mechanical stop invariant: odometer does not move while breakdown is active.
WITH mech AS (
    SELECT
        shipment_id,
        MIN(time) FILTER (WHERE event_type='DISRUPTION_STARTED') AS started_at,
        MIN(time) FILTER (WHERE event_type='DISRUPTION_ENDED') AS ended_at
    FROM sc_events
    WHERE run_id = 40 
      AND cause_code='MECHANICAL_BREAKDOWN'
    GROUP BY shipment_id
)
SELECT
    ROUND(MAX(t.odometer_km) - MIN(t.odometer_km), 3)
        AS mechanical_odometer_delta_km
FROM sc_fleet_telemetry t
JOIN mech m USING (shipment_id)
WHERE t.run_id = 40 
  AND t.time >= m.started_at
  AND t.time < m.ended_at;

-- 5. Fuel-stop invariant: odometer does not move while refueling.
WITH fuel AS (
    SELECT
        shipment_id,
        MIN(time) FILTER (WHERE event_type='FUEL_STOP_STARTED') AS started_at,
        MIN(time) FILTER (WHERE event_type='FUEL_STOP_ENDED') AS ended_at
    FROM sc_events
    WHERE run_id = 40 
      AND cause_code='LOW_FUEL_REFUEL'
    GROUP BY shipment_id
)
SELECT
    ROUND(MAX(t.odometer_km) - MIN(t.odometer_km), 3)
        AS fuel_stop_odometer_delta_km
FROM sc_fleet_telemetry t
JOIN fuel f USING (shipment_id)
WHERE t.run_id = 40 
  AND t.time >= f.started_at
  AND t.time < f.ended_at;

-- 6. Live invariants.
SELECT COUNT(*) AS future_telemetry_rows
FROM sc_fleet_telemetry
WHERE run_id = 40
  AND time > NOW() + INTERVAL '5 seconds';
 
SELECT COUNT(*) AS duplicate_vehicle_timestamp_groups
FROM (
    SELECT vehicle_id, time, COUNT(*) AS row_count
    FROM sc_fleet_telemetry
    WHERE run_id = 40 
    GROUP BY vehicle_id, time
    HAVING COUNT(*) > 1
) d;
