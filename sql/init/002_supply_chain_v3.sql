-- 003_supply_chain_v3.sql
-- Supply Chain Generator v3 schema migration
--
-- IMPORTANT:
--   Review this file before running it.
--   This migration intentionally refuses to run while generated Supply Chain
--   v2 fact data still exists. The v3 lifecycle/event semantics are not
--   compatible with mixed v2/v3 operational rows.
--
-- Expected workflow:
--   1. Back up/export the current schema if desired.
--   2. Clear generated Supply Chain facts:
--        sc_events
--        sc_fleet_telemetry
--        sc_warehouse_env
--        sc_shipments
--      Preserve:
--        sc_vehicles
--        sc_warehouses
--   3. Run this migration.
--   4. Seed sc_routes and sc_cargo_profiles.
--   5. Run the 2-day v3 validation.
--
-- PostgreSQL / TimescaleDB:
--   Do not modify _timescaledb_internal objects directly.

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Safety guard: do not mix v2 and v3 generated operational data.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.sc_shipments LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.sc_events LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.sc_fleet_telemetry LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.sc_warehouse_env LIMIT 1)
    THEN
        RAISE EXCEPTION
            'Supply Chain v3 migration aborted: generated v2 Supply Chain data still exists. Clear sc_events, sc_fleet_telemetry, sc_warehouse_env, and sc_shipments before running this migration.';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 1. Simulation run metadata.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.sc_simulation_runs (
    run_id                 bigserial PRIMARY KEY,
    generator_name         text NOT NULL,
    model_version          text NOT NULL,
    seed                   bigint NOT NULL,
    simulation_start       timestamp with time zone NOT NULL,
    simulation_end         timestamp with time zone NOT NULL,
    generated_at           timestamp with time zone NOT NULL DEFAULT now(),
    configuration_version  text,
    status                 text NOT NULL,
    metadata_json          jsonb,

    CONSTRAINT sc_simulation_runs_time_chk
        CHECK (simulation_end > simulation_start),

    CONSTRAINT sc_simulation_runs_status_chk
        CHECK (
            status IN (
                'STARTED',
                'COMPLETED',
                'FAILED',
                'VALIDATION_FAILED'
            )
        )
);

-- ---------------------------------------------------------------------------
-- 2. Warehouse master/profile extensions.
-- ---------------------------------------------------------------------------

ALTER TABLE public.sc_warehouses
    ADD COLUMN IF NOT EXISTS loading_capacity integer,
    ADD COLUMN IF NOT EXISTS unloading_capacity integer,
    ADD COLUMN IF NOT EXISTS baseline_loading_min numeric(6,2),
    ADD COLUMN IF NOT EXISTS baseline_unloading_min numeric(6,2),
    ADD COLUMN IF NOT EXISTS congestion_sensitivity numeric(5,3),
    ADD COLUMN IF NOT EXISTS cold_storage_capable boolean DEFAULT false;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_warehouses_loading_capacity_chk'
          AND conrelid = 'public.sc_warehouses'::regclass
    ) THEN
        ALTER TABLE public.sc_warehouses
            ADD CONSTRAINT sc_warehouses_loading_capacity_chk
            CHECK (loading_capacity IS NULL OR loading_capacity > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_warehouses_unloading_capacity_chk'
          AND conrelid = 'public.sc_warehouses'::regclass
    ) THEN
        ALTER TABLE public.sc_warehouses
            ADD CONSTRAINT sc_warehouses_unloading_capacity_chk
            CHECK (unloading_capacity IS NULL OR unloading_capacity > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_warehouses_loading_minutes_chk'
          AND conrelid = 'public.sc_warehouses'::regclass
    ) THEN
        ALTER TABLE public.sc_warehouses
            ADD CONSTRAINT sc_warehouses_loading_minutes_chk
            CHECK (
                baseline_loading_min IS NULL
                OR baseline_loading_min >= 0
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_warehouses_unloading_minutes_chk'
          AND conrelid = 'public.sc_warehouses'::regclass
    ) THEN
        ALTER TABLE public.sc_warehouses
            ADD CONSTRAINT sc_warehouses_unloading_minutes_chk
            CHECK (
                baseline_unloading_min IS NULL
                OR baseline_unloading_min >= 0
            );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. Directional route master data.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.sc_routes (
    route_id                 serial PRIMARY KEY,
    origin_wh_id             integer NOT NULL,
    dest_wh_id               integer NOT NULL,
    distance_km              numeric(8,2) NOT NULL,
    nominal_speed_kmh        numeric(6,2) NOT NULL,
    minimum_speed_kmh        numeric(6,2),
    maximum_speed_kmh        numeric(6,2),
    baseline_travel_min      numeric(8,2),
    congestion_sensitivity   numeric(5,3),
    weather_sensitivity      numeric(5,3),
    morning_peak_factor      numeric(5,3) NOT NULL DEFAULT 1.0,
    evening_peak_factor      numeric(5,3) NOT NULL DEFAULT 1.0,
    overnight_factor         numeric(5,3) NOT NULL DEFAULT 1.0,
    demand_weight            numeric(6,3) NOT NULL DEFAULT 1.0,
    disruption_probability   numeric(7,6),
    active                   boolean NOT NULL DEFAULT true,

    CONSTRAINT sc_routes_origin_fk
        FOREIGN KEY (origin_wh_id)
        REFERENCES public.sc_warehouses(warehouse_id),

    CONSTRAINT sc_routes_dest_fk
        FOREIGN KEY (dest_wh_id)
        REFERENCES public.sc_warehouses(warehouse_id),

    CONSTRAINT sc_routes_direction_uq
        UNIQUE (origin_wh_id, dest_wh_id),

    CONSTRAINT sc_routes_distinct_warehouses_chk
        CHECK (origin_wh_id <> dest_wh_id),

    CONSTRAINT sc_routes_distance_chk
        CHECK (distance_km > 0),

    CONSTRAINT sc_routes_nominal_speed_chk
        CHECK (nominal_speed_kmh > 0),

    CONSTRAINT sc_routes_speed_bounds_chk
        CHECK (
            minimum_speed_kmh IS NULL
            OR maximum_speed_kmh IS NULL
            OR minimum_speed_kmh <= maximum_speed_kmh
        ),

    CONSTRAINT sc_routes_demand_weight_chk
        CHECK (demand_weight > 0),

    CONSTRAINT sc_routes_disruption_probability_chk
        CHECK (
            disruption_probability IS NULL
            OR disruption_probability BETWEEN 0 AND 1
        )
);

-- ---------------------------------------------------------------------------
-- 4. Cargo profiles.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.sc_cargo_profiles (
    cargo_type             text PRIMARY KEY,
    requires_reefer        boolean NOT NULL DEFAULT false,
    target_temp_c          numeric(6,2),
    min_temp_c             numeric(6,2),
    max_temp_c             numeric(6,2),
    target_humidity_pct    numeric(6,2),
    handling_sensitivity   numeric(5,3) NOT NULL DEFAULT 1.0,
    loading_time_factor    numeric(5,3) NOT NULL DEFAULT 1.0,
    active                 boolean NOT NULL DEFAULT true,

    CONSTRAINT sc_cargo_profiles_temp_range_chk
        CHECK (
            min_temp_c IS NULL
            OR max_temp_c IS NULL
            OR min_temp_c <= max_temp_c
        ),

    CONSTRAINT sc_cargo_profiles_humidity_chk
        CHECK (
            target_humidity_pct IS NULL
            OR target_humidity_pct BETWEEN 0 AND 100
        ),

    CONSTRAINT sc_cargo_profiles_handling_chk
        CHECK (handling_sensitivity > 0),

    CONSTRAINT sc_cargo_profiles_loading_factor_chk
        CHECK (loading_time_factor > 0)
);

-- ---------------------------------------------------------------------------
-- 5. Vehicle persistent profile extensions.
-- ---------------------------------------------------------------------------

ALTER TABLE public.sc_vehicles
    ADD COLUMN IF NOT EXISTS fuel_efficiency_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS reliability_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS condition_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS cruise_speed_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS maintenance_risk_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS reefer_capable boolean DEFAULT false;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_vehicles_profile_factors_chk'
          AND conrelid = 'public.sc_vehicles'::regclass
    ) THEN
        ALTER TABLE public.sc_vehicles
            ADD CONSTRAINT sc_vehicles_profile_factors_chk
            CHECK (
                fuel_efficiency_factor > 0
                AND reliability_factor > 0
                AND condition_factor > 0
                AND cruise_speed_factor > 0
                AND maintenance_risk_factor > 0
            );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 6. Shipments: lifecycle/ETA/route/run lineage.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sc_shipments'
          AND column_name = 'status'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'sc_shipments'
          AND column_name = 'lifecycle_status'
    )
    THEN
        ALTER TABLE public.sc_shipments
            RENAME COLUMN status TO lifecycle_status;
    END IF;
END
$$;

ALTER TABLE public.sc_shipments
    ADD COLUMN IF NOT EXISTS run_id bigint,
    ADD COLUMN IF NOT EXISTS route_id integer,
    ADD COLUMN IF NOT EXISTS estimated_arrival timestamp with time zone,
    ADD COLUMN IF NOT EXISTS delivery_completed_at timestamp with time zone;

ALTER TABLE public.sc_shipments
    ALTER COLUMN lifecycle_status SET DEFAULT 'PLANNED';

-- Empty-table migration guard above makes this safe.
UPDATE public.sc_shipments
SET lifecycle_status = 'PLANNED'
WHERE lifecycle_status IS NULL;

ALTER TABLE public.sc_shipments
    ALTER COLUMN lifecycle_status SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_run_fk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_run_fk
            FOREIGN KEY (run_id)
            REFERENCES public.sc_simulation_runs(run_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_route_fk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_route_fk
            FOREIGN KEY (route_id)
            REFERENCES public.sc_routes(route_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_cargo_fk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_cargo_fk
            FOREIGN KEY (cargo_type)
            REFERENCES public.sc_cargo_profiles(cargo_type)
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_lifecycle_status_chk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_lifecycle_status_chk
            CHECK (
                lifecycle_status IN (
                    'PLANNED',
                    'READY',
                    'IN_TRANSIT',
                    'ARRIVED',
                    'DELIVERED'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_priority_chk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_priority_chk
            CHECK (
                priority IN (
                    'STANDARD',
                    'EXPEDITED',
                    'CRITICAL'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_schedule_time_chk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_schedule_time_chk
            CHECK (
                scheduled_departure IS NULL
                OR scheduled_arrival IS NULL
                OR scheduled_arrival > scheduled_departure
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_actual_time_chk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_actual_time_chk
            CHECK (
                actual_arrival IS NULL
                OR actual_departure IS NULL
                OR actual_arrival > actual_departure
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_delivery_time_chk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_delivery_time_chk
            CHECK (
                delivery_completed_at IS NULL
                OR (
                    actual_arrival IS NOT NULL
                    AND delivery_completed_at >= actual_arrival
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_shipments_lifecycle_timestamp_chk'
          AND conrelid = 'public.sc_shipments'::regclass
    ) THEN
        ALTER TABLE public.sc_shipments
            ADD CONSTRAINT sc_shipments_lifecycle_timestamp_chk
            CHECK (
                (lifecycle_status IN ('PLANNED', 'READY')
                    AND actual_departure IS NULL
                    AND actual_arrival IS NULL
                    AND delivery_completed_at IS NULL)

                OR

                (lifecycle_status = 'IN_TRANSIT'
                    AND actual_departure IS NOT NULL
                    AND actual_arrival IS NULL
                    AND delivery_completed_at IS NULL)

                OR

                (lifecycle_status = 'ARRIVED'
                    AND actual_departure IS NOT NULL
                    AND actual_arrival IS NOT NULL
                    AND delivery_completed_at IS NULL)

                OR

                (lifecycle_status = 'DELIVERED'
                    AND actual_departure IS NOT NULL
                    AND actual_arrival IS NOT NULL
                    AND delivery_completed_at IS NOT NULL)
            );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 7. Events: add relational context and run lineage.
--    NOTE: sc_events is an existing TimescaleDB hypertable partitioned by time.
-- ---------------------------------------------------------------------------

ALTER TABLE public.sc_events
    ADD COLUMN IF NOT EXISTS vehicle_id integer,
    ADD COLUMN IF NOT EXISTS route_id integer,
    ADD COLUMN IF NOT EXISTS run_id bigint,
    ADD COLUMN IF NOT EXISTS cause_code text;

ALTER TABLE public.sc_events
    ALTER COLUMN event_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_events_vehicle_fk'
          AND conrelid = 'public.sc_events'::regclass
    ) THEN
        ALTER TABLE public.sc_events
            ADD CONSTRAINT sc_events_vehicle_fk
            FOREIGN KEY (vehicle_id)
            REFERENCES public.sc_vehicles(vehicle_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_events_route_fk'
          AND conrelid = 'public.sc_events'::regclass
    ) THEN
        ALTER TABLE public.sc_events
            ADD CONSTRAINT sc_events_route_fk
            FOREIGN KEY (route_id)
            REFERENCES public.sc_routes(route_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_events_run_fk'
          AND conrelid = 'public.sc_events'::regclass
    ) THEN
        ALTER TABLE public.sc_events
            ADD CONSTRAINT sc_events_run_fk
            FOREIGN KEY (run_id)
            REFERENCES public.sc_simulation_runs(run_id);
    END IF;
END
$$;

-- sc_events is already a TimescaleDB hypertable in the current database.
-- TimescaleDB requires every UNIQUE index on a hypertable to include the
-- partitioning column (`time`). We do not need database-enforced global
-- uniqueness for event_id in v3, so use a normal lookup index instead.
CREATE INDEX IF NOT EXISTS sc_events_event_id_idx
    ON public.sc_events (event_id);

-- ---------------------------------------------------------------------------
-- 8. Fleet telemetry: add simulation lineage.
--    sc_fleet_telemetry remains a TimescaleDB hypertable.
-- ---------------------------------------------------------------------------

ALTER TABLE public.sc_fleet_telemetry
    ADD COLUMN IF NOT EXISTS run_id bigint;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_fleet_telemetry_run_fk'
          AND conrelid = 'public.sc_fleet_telemetry'::regclass
    ) THEN
        ALTER TABLE public.sc_fleet_telemetry
            ADD CONSTRAINT sc_fleet_telemetry_run_fk
            FOREIGN KEY (run_id)
            REFERENCES public.sc_simulation_runs(run_id);
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 9. Warehouse telemetry: add lineage + operating state.
--    sc_warehouse_env remains a TimescaleDB hypertable.
-- ---------------------------------------------------------------------------

ALTER TABLE public.sc_warehouse_env
    ADD COLUMN IF NOT EXISTS run_id bigint,
    ADD COLUMN IF NOT EXISTS operating_state text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_warehouse_env_run_fk'
          AND conrelid = 'public.sc_warehouse_env'::regclass
    ) THEN
        ALTER TABLE public.sc_warehouse_env
            ADD CONSTRAINT sc_warehouse_env_run_fk
            FOREIGN KEY (run_id)
            REFERENCES public.sc_simulation_runs(run_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'sc_warehouse_env_operating_state_chk'
          AND conrelid = 'public.sc_warehouse_env'::regclass
    ) THEN
        ALTER TABLE public.sc_warehouse_env
            ADD CONSTRAINT sc_warehouse_env_operating_state_chk
            CHECK (
                operating_state IS NULL
                OR operating_state IN ('NORMAL', 'BUSY', 'CONGESTED')
            );
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 10. Transactional/reference indexes.
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS sc_shipments_vehicle_idx
    ON public.sc_shipments (vehicle_id);

CREATE INDEX IF NOT EXISTS sc_shipments_route_idx
    ON public.sc_shipments (route_id);

CREATE INDEX IF NOT EXISTS sc_shipments_origin_idx
    ON public.sc_shipments (origin_wh_id);

CREATE INDEX IF NOT EXISTS sc_shipments_dest_idx
    ON public.sc_shipments (dest_wh_id);

CREATE INDEX IF NOT EXISTS sc_shipments_lifecycle_idx
    ON public.sc_shipments (lifecycle_status);

CREATE INDEX IF NOT EXISTS sc_shipments_sched_dep_idx
    ON public.sc_shipments (scheduled_departure);

CREATE INDEX IF NOT EXISTS sc_shipments_actual_arrival_idx
    ON public.sc_shipments (actual_arrival);

CREATE INDEX IF NOT EXISTS sc_shipments_run_idx
    ON public.sc_shipments (run_id);

CREATE INDEX IF NOT EXISTS sc_events_time_idx
    ON public.sc_events ("time");

CREATE INDEX IF NOT EXISTS sc_events_shipment_idx
    ON public.sc_events (shipment_id);

CREATE INDEX IF NOT EXISTS sc_events_vehicle_idx
    ON public.sc_events (vehicle_id);

CREATE INDEX IF NOT EXISTS sc_events_route_idx
    ON public.sc_events (route_id);

CREATE INDEX IF NOT EXISTS sc_events_type_idx
    ON public.sc_events (event_type);

CREATE INDEX IF NOT EXISTS sc_events_cause_idx
    ON public.sc_events (cause_code);

-- ---------------------------------------------------------------------------
-- 11. Comments documenting semantics.
-- ---------------------------------------------------------------------------

COMMENT ON TABLE public.sc_simulation_runs IS
    'Model v3 generation metadata and deterministic seed lineage.';

COMMENT ON TABLE public.sc_routes IS
    'Directional Supply Chain route profiles. A->B and B->A are distinct routes.';

COMMENT ON TABLE public.sc_cargo_profiles IS
    'Supply Chain cargo handling/environmental profiles.';

COMMENT ON COLUMN public.sc_shipments.lifecycle_status IS
    'Operational lifecycle only: PLANNED, READY, IN_TRANSIT, ARRIVED, DELIVERED. Delivery performance is derived separately.';

COMMENT ON COLUMN public.sc_shipments.scheduled_arrival IS
    'Original planned service commitment; remains stable after execution begins.';

COMMENT ON COLUMN public.sc_shipments.estimated_arrival IS
    'Dynamic ETA derived from current simulation state.';

COMMENT ON COLUMN public.sc_shipments.actual_arrival IS
    'Observed simulated physical arrival; NULL until IN_TRANSIT -> ARRIVED.';

COMMENT ON COLUMN public.sc_shipments.delivery_completed_at IS
    'Destination handling/proof-of-delivery completion; populated at ARRIVED -> DELIVERED.';

COMMENT ON COLUMN public.sc_events.cause_code IS
    'Machine-readable causal code explaining why an operational event occurred.';

COMMENT ON COLUMN public.sc_warehouse_env.operating_state IS
    'Warehouse operating condition: NORMAL, BUSY, or CONGESTED.';

COMMIT;

-- ---------------------------------------------------------------------------
-- Post-migration notes
-- ---------------------------------------------------------------------------
--
-- 1. This migration does NOT seed sc_routes or sc_cargo_profiles.
-- 2. The cargo FK is added NOT VALID intentionally. Validate it after seed data:
--
--      ALTER TABLE public.sc_shipments
--          VALIDATE CONSTRAINT sc_shipments_cargo_fk;
--
-- 3. Review/rebuild/refesh TimescaleDB continuous aggregates after v3 data is
--    generated. Do not modify _timescaledb_internal tables directly.
-- 4. Existing v2 synthetic fact rows are intentionally not supported.
