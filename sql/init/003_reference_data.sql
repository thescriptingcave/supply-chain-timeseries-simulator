-- supply_chain_v3_reference_data.sql
-- Initial reference/master data for Supply Chain Generator v3.
--
-- Run AFTER:
--   003_supply_chain_v3.sql
--
-- This seed preserves the four current warehouse identities and the route
-- distances already used by the v2 generator, while adding intentional v3
-- differences in warehouse, route, vehicle, and cargo behavior.
--
-- The profile factors below are synthetic modeling assumptions for v3.
-- They are configuration, not claims about real facilities or routes.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Guard: verify the expected warehouse IDs/names before seeding routes.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    bad_count integer;
BEGIN
    SELECT COUNT(*)
    INTO bad_count
    FROM (
        VALUES
            (1, 'Houston Distribution Hub'),
            (2, 'Los Angeles Port Warehouse'),
            (3, 'Phoenix Central DC'),
            (4, 'El Paso Border Facility')
    ) AS expected(warehouse_id, warehouse_name)
    LEFT JOIN public.sc_warehouses w
      ON w.warehouse_id = expected.warehouse_id
     AND w.warehouse_name = expected.warehouse_name
    WHERE w.warehouse_id IS NULL;

    IF bad_count > 0 THEN
        RAISE EXCEPTION
            'Supply Chain v3 reference seed aborted: sc_warehouses does not match the expected four warehouse IDs/names.';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. Warehouse operating profiles.
--
-- loading_capacity / unloading_capacity:
--     concurrent logical dock operations used by the simulation model
--
-- baseline_*_min:
--     baseline dwell components before congestion/cargo/priority factors
--
-- congestion_sensitivity:
--     relative responsiveness to workload; 1.0 = baseline sensitivity
-- ---------------------------------------------------------------------------

UPDATE public.sc_warehouses
SET
    loading_capacity = 6,
    unloading_capacity = 7,
    baseline_loading_min = 24.0,
    baseline_unloading_min = 22.0,
    congestion_sensitivity = 1.05,
    cold_storage_capable = true
WHERE warehouse_id = 1;  -- Houston Distribution Hub

UPDATE public.sc_warehouses
SET
    loading_capacity = 8,
    unloading_capacity = 8,
    baseline_loading_min = 28.0,
    baseline_unloading_min = 25.0,
    congestion_sensitivity = 1.20,
    cold_storage_capable = true
WHERE warehouse_id = 2;  -- Los Angeles Port Warehouse

UPDATE public.sc_warehouses
SET
    loading_capacity = 7,
    unloading_capacity = 7,
    baseline_loading_min = 20.0,
    baseline_unloading_min = 19.0,
    congestion_sensitivity = 0.90,
    cold_storage_capable = true
WHERE warehouse_id = 3;  -- Phoenix Central DC

UPDATE public.sc_warehouses
SET
    loading_capacity = 5,
    unloading_capacity = 5,
    baseline_loading_min = 26.0,
    baseline_unloading_min = 24.0,
    congestion_sensitivity = 1.10,
    cold_storage_capable = true
WHERE warehouse_id = 4;  -- El Paso Border Facility

-- ---------------------------------------------------------------------------
-- 3. Directional route profiles.
--
-- Existing v2 distance assumptions are preserved:
--   Houston <-> Los Angeles : 2200 km
--   Houston <-> Phoenix     : 1600 km
--   Houston <-> El Paso     : 1100 km
--   Los Angeles <-> Phoenix :  600 km
--   Los Angeles <-> El Paso : 1300 km
--   Phoenix <-> El Paso     :  550 km
--
-- v3 adds directional behavior. The factors intentionally differ by direction
-- so long-window analytics can reveal explainable route differences.
--
-- factor interpretation:
--   1.00 = baseline
--   >1.00 = stronger penalty/sensitivity
--   <1.00 = lower penalty/sensitivity
-- ---------------------------------------------------------------------------

INSERT INTO public.sc_routes (
    origin_wh_id,
    dest_wh_id,
    distance_km,
    nominal_speed_kmh,
    minimum_speed_kmh,
    maximum_speed_kmh,
    baseline_travel_min,
    congestion_sensitivity,
    weather_sensitivity,
    morning_peak_factor,
    evening_peak_factor,
    overnight_factor,
    demand_weight,
    disruption_probability,
    active
)
VALUES
    -- Houston -> Los Angeles
    (1, 2, 2200, 82, 35, 100, 1610, 1.08, 1.00, 1.08, 1.12, 0.96, 1.10, 0.012, true),

    -- Houston -> Phoenix
    (1, 3, 1600, 84, 40, 100, 1145, 1.02, 1.08, 1.06, 1.08, 0.96, 1.15, 0.010, true),

    -- Houston -> El Paso
    (1, 4, 1100, 85, 40, 100,  790, 0.95, 1.08, 1.03, 1.05, 0.95, 0.90, 0.009, true),

    -- Los Angeles -> Houston
    (2, 1, 2200, 80, 30, 100, 1650, 1.22, 1.00, 1.20, 1.28, 0.94, 1.05, 0.014, true),

    -- Los Angeles -> Phoenix
    (2, 3,  600, 78, 30,  95,  470, 1.28, 0.92, 1.25, 1.30, 0.93, 1.30, 0.016, true),

    -- Los Angeles -> El Paso
    (2, 4, 1300, 80, 30,  98,  990, 1.20, 0.96, 1.18, 1.24, 0.94, 1.00, 0.014, true),

    -- Phoenix -> Houston
    (3, 1, 1600, 85, 40, 102, 1130, 0.94, 1.12, 1.03, 1.05, 0.96, 1.20, 0.009, true),

    -- Phoenix -> Los Angeles
    (3, 2,  600, 80, 30,  96,  455, 1.12, 0.92, 1.10, 1.18, 0.94, 1.25, 0.012, true),

    -- Phoenix -> El Paso
    (3, 4,  550, 86, 40, 102,  400, 0.88, 1.10, 1.02, 1.04, 0.96, 0.95, 0.008, true),

    -- El Paso -> Houston
    (4, 1, 1100, 84, 40, 100,  800, 0.92, 1.08, 1.03, 1.04, 0.96, 0.95, 0.009, true),

    -- El Paso -> Los Angeles
    (4, 2, 1300, 81, 35,  98,  975, 1.10, 0.96, 1.12, 1.18, 0.94, 0.85, 0.012, true),

    -- El Paso -> Phoenix
    (4, 3,  550, 85, 40, 100,  405, 0.90, 1.10, 1.02, 1.04, 0.96, 0.90, 0.008, true)

ON CONFLICT (origin_wh_id, dest_wh_id)
DO UPDATE SET
    distance_km = EXCLUDED.distance_km,
    nominal_speed_kmh = EXCLUDED.nominal_speed_kmh,
    minimum_speed_kmh = EXCLUDED.minimum_speed_kmh,
    maximum_speed_kmh = EXCLUDED.maximum_speed_kmh,
    baseline_travel_min = EXCLUDED.baseline_travel_min,
    congestion_sensitivity = EXCLUDED.congestion_sensitivity,
    weather_sensitivity = EXCLUDED.weather_sensitivity,
    morning_peak_factor = EXCLUDED.morning_peak_factor,
    evening_peak_factor = EXCLUDED.evening_peak_factor,
    overnight_factor = EXCLUDED.overnight_factor,
    demand_weight = EXCLUDED.demand_weight,
    disruption_probability = EXCLUDED.disruption_probability,
    active = EXCLUDED.active;

-- ---------------------------------------------------------------------------
-- 4. Cargo profiles.
--
-- These nine cargo names exactly cover the v2 generator's cargo vocabulary.
-- Temperature values are synthetic model settings used to create internally
-- consistent telemetry; they are not regulatory specifications.
-- ---------------------------------------------------------------------------

INSERT INTO public.sc_cargo_profiles (
    cargo_type,
    requires_reefer,
    target_temp_c,
    min_temp_c,
    max_temp_c,
    target_humidity_pct,
    handling_sensitivity,
    loading_time_factor,
    active
)
VALUES
    ('FROZEN_FOOD',   true,  -18.0, -22.0, -15.0, 65.0, 1.25, 1.20, true),
    ('FRESH_PRODUCE', true,    4.0,   1.0,   8.0, 78.0, 1.20, 1.15, true),
    ('PHARMA',        true,    5.0,   2.0,   8.0, 55.0, 1.40, 1.25, true),

    ('GENERAL_FREIGHT', false, NULL, NULL, NULL, 50.0, 1.00, 1.00, true),
    ('CONSUMER_GOODS', false, NULL, NULL, NULL, 50.0, 1.00, 1.00, true),
    ('ELECTRONICS',    false, NULL, NULL, NULL, 45.0, 1.15, 1.10, true),

    ('FUEL',         false, NULL, NULL, NULL, NULL, 1.30, 1.20, true),
    ('CHEMICALS',    false, NULL, NULL, NULL, NULL, 1.35, 1.25, true),
    ('LIQUID_BULK',  false, NULL, NULL, NULL, NULL, 1.20, 1.15, true)

ON CONFLICT (cargo_type)
DO UPDATE SET
    requires_reefer = EXCLUDED.requires_reefer,
    target_temp_c = EXCLUDED.target_temp_c,
    min_temp_c = EXCLUDED.min_temp_c,
    max_temp_c = EXCLUDED.max_temp_c,
    target_humidity_pct = EXCLUDED.target_humidity_pct,
    handling_sensitivity = EXCLUDED.handling_sensitivity,
    loading_time_factor = EXCLUDED.loading_time_factor,
    active = EXCLUDED.active;

-- ---------------------------------------------------------------------------
-- 5. Vehicle profile initialization.
--
-- Keep vehicle_type as the authoritative capability category already present
-- in sc_vehicles.  v3 adds stable per-vehicle differences without changing
-- identity, registration, operator, or vehicle type.
--
-- The formulas are deterministic by vehicle_id so repeated seed execution is
-- idempotent and profile differences remain stable.
-- ---------------------------------------------------------------------------

UPDATE public.sc_vehicles
SET
    reefer_capable =
        CASE
            WHEN upper(coalesce(vehicle_type, '')) = 'REEFER' THEN true
            ELSE false
        END,

    fuel_efficiency_factor =
        CASE (vehicle_id % 4)
            WHEN 0 THEN 0.94
            WHEN 1 THEN 1.02
            WHEN 2 THEN 0.98
            ELSE 1.06
        END,

    reliability_factor =
        CASE (vehicle_id % 5)
            WHEN 0 THEN 0.90
            WHEN 1 THEN 1.05
            WHEN 2 THEN 0.97
            WHEN 3 THEN 1.08
            ELSE 1.00
        END,

    condition_factor =
        CASE
            WHEN year_manufactured IS NULL THEN 1.00
            WHEN year_manufactured >= 2023 THEN 1.06
            WHEN year_manufactured >= 2020 THEN 1.00
            WHEN year_manufactured >= 2017 THEN 0.95
            ELSE 0.90
        END,

    cruise_speed_factor =
        CASE (vehicle_id % 3)
            WHEN 0 THEN 0.98
            WHEN 1 THEN 1.02
            ELSE 1.00
        END,

    maintenance_risk_factor =
        CASE (vehicle_id % 5)
            WHEN 0 THEN 1.15
            WHEN 1 THEN 0.92
            WHEN 2 THEN 1.04
            WHEN 3 THEN 0.88
            ELSE 1.00
        END;

-- ---------------------------------------------------------------------------
-- 6. Validate cargo FK now that reference rows exist.
-- ---------------------------------------------------------------------------

ALTER TABLE public.sc_shipments
    VALIDATE CONSTRAINT sc_shipments_cargo_fk;

-- ---------------------------------------------------------------------------
-- 7. Seed verification.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    route_count integer;
    cargo_count integer;
    vehicle_count integer;
    profiled_vehicle_count integer;
BEGIN
    SELECT COUNT(*)
    INTO route_count
    FROM public.sc_routes
    WHERE active;

    IF route_count <> 12 THEN
        RAISE EXCEPTION
            'Expected 12 active directional routes after seed; found %.',
            route_count;
    END IF;

    SELECT COUNT(*)
    INTO cargo_count
    FROM public.sc_cargo_profiles
    WHERE active;

    IF cargo_count <> 9 THEN
        RAISE EXCEPTION
            'Expected 9 active cargo profiles after seed; found %.',
            cargo_count;
    END IF;

    SELECT COUNT(*)
    INTO vehicle_count
    FROM public.sc_vehicles;

    SELECT COUNT(*)
    INTO profiled_vehicle_count
    FROM public.sc_vehicles
    WHERE fuel_efficiency_factor IS NOT NULL
      AND reliability_factor IS NOT NULL
      AND condition_factor IS NOT NULL
      AND cruise_speed_factor IS NOT NULL
      AND maintenance_risk_factor IS NOT NULL
      AND reefer_capable IS NOT NULL;

    IF profiled_vehicle_count <> vehicle_count THEN
        RAISE EXCEPTION
            'Not all vehicles received v3 profiles: % of % profiled.',
            profiled_vehicle_count,
            vehicle_count;
    END IF;
END
$$;

COMMIT;

-- ---------------------------------------------------------------------------
-- Post-seed inspection queries
-- ---------------------------------------------------------------------------
--
-- Warehouses:
-- SELECT
--     warehouse_id,
--     warehouse_name,
--     loading_capacity,
--     unloading_capacity,
--     baseline_loading_min,
--     baseline_unloading_min,
--     congestion_sensitivity,
--     cold_storage_capable
-- FROM public.sc_warehouses
-- ORDER BY warehouse_id;
--
-- Routes:
-- SELECT
--     route_id,
--     origin_wh_id,
--     dest_wh_id,
--     distance_km,
--     nominal_speed_kmh,
--     congestion_sensitivity,
--     demand_weight,
--     disruption_probability
-- FROM public.sc_routes
-- ORDER BY origin_wh_id, dest_wh_id;
--
-- Vehicles:
-- SELECT
--     vehicle_id,
--     vehicle_reg,
--     vehicle_type,
--     year_manufactured,
--     fuel_efficiency_factor,
--     reliability_factor,
--     condition_factor,
--     cruise_speed_factor,
--     maintenance_risk_factor,
--     reefer_capable
-- FROM public.sc_vehicles
-- ORDER BY vehicle_id;
--
-- Cargo:
-- SELECT *
-- FROM public.sc_cargo_profiles
-- ORDER BY cargo_type;
