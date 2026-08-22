-- Supply Chain v3 one-shipment integration validation
-- Replace :run_id with the run_id printed by the integration runner if your
-- SQL client does not support named variables.

-- 1. Run status
SELECT
    run_id,
    generator_name,
    model_version,
    seed,
    status,
    simulation_start,
    simulation_end
FROM sc_simulation_runs
WHERE run_id = :run_id;

-- 2. Shipment lifecycle/timestamps
SELECT
    shipment_id,
    run_id,
    vehicle_id,
    route_id,
    origin_wh_id,
    dest_wh_id,
    lifecycle_status,
    scheduled_departure,
    scheduled_arrival,
    estimated_arrival,
    actual_departure,
    actual_arrival,
    delivery_completed_at
FROM sc_shipments
WHERE run_id = :run_id;

-- 3. Fleet telemetry summary
SELECT
    COUNT(*) AS telemetry_rows,
    MIN(time) AS first_sample,
    MAX(time) AS last_sample,
    MIN(fuel_level_pct) AS min_fuel,
    MAX(fuel_level_pct) AS max_fuel,
    MIN(odometer_km) AS min_odometer,
    MAX(odometer_km) AS max_odometer
FROM sc_fleet_telemetry
WHERE run_id = :run_id;

-- 4. Referential integrity: every telemetry row must match the run shipment
SELECT COUNT(*) AS invalid_telemetry_refs
FROM sc_fleet_telemetry t
LEFT JOIN sc_shipments s
  ON s.shipment_id = t.shipment_id
 AND s.run_id = t.run_id
WHERE t.run_id = :run_id
  AND s.shipment_id IS NULL;

-- Expected: 0

-- 5. Premature actual arrival invariant
SELECT COUNT(*) AS premature_actual_arrivals
FROM sc_shipments
WHERE run_id = :run_id
  AND lifecycle_status IN ('PLANNED', 'READY', 'IN_TRANSIT')
  AND actual_arrival IS NOT NULL;

-- Expected: 0

-- 6. Delivery chronology
SELECT COUNT(*) AS invalid_delivery_chronology
FROM sc_shipments
WHERE run_id = :run_id
  AND (
      actual_departure IS NULL
      OR actual_arrival IS NULL
      OR delivery_completed_at IS NULL
      OR actual_arrival <= actual_departure
      OR delivery_completed_at < actual_arrival
  );

-- Expected: 0

-- 7. Fuel should not increase during this no-refuel integration case
WITH ordered AS (
    SELECT
        time,
        fuel_level_pct,
        LAG(fuel_level_pct) OVER (ORDER BY time) AS previous_fuel
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
)
SELECT COUNT(*) AS fuel_increases
FROM ordered
WHERE previous_fuel IS NOT NULL
  AND fuel_level_pct > previous_fuel;

-- Expected: 0

-- 8. Odometer should not decrease
WITH ordered AS (
    SELECT
        time,
        odometer_km,
        LAG(odometer_km) OVER (ORDER BY time) AS previous_odometer
    FROM sc_fleet_telemetry
    WHERE run_id = :run_id
)
SELECT COUNT(*) AS odometer_decreases
FROM ordered
WHERE previous_odometer IS NOT NULL
  AND odometer_km < previous_odometer;

-- Expected: 0
