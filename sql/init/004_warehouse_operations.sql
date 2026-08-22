-- 004_supply_chain_v3_warehouse_operations.sql
-- Separate warehouse operational telemetry from environmental telemetry.
--
-- sc_warehouse_env remains focused on:
--   temperature, humidity, CO2, occupancy, energy, door activity.
--
-- sc_warehouse_operations becomes the authoritative time-series source for:
--   loading activity, unloading activity, queue depth, congestion, operating state.

BEGIN;

CREATE TABLE IF NOT EXISTS public.sc_warehouse_operations (
    time                    timestamp with time zone NOT NULL,
    warehouse_id            integer NOT NULL,
    loading_bays_active     integer NOT NULL,
    unloading_bays_active   integer NOT NULL,
    queue_depth             integer NOT NULL,
    congestion_factor       numeric(6,3) NOT NULL,
    operating_state         text NOT NULL,
    run_id                  bigint,

    CONSTRAINT sc_warehouse_operations_warehouse_fk
        FOREIGN KEY (warehouse_id)
        REFERENCES public.sc_warehouses(warehouse_id),

    CONSTRAINT sc_warehouse_operations_run_fk
        FOREIGN KEY (run_id)
        REFERENCES public.sc_simulation_runs(run_id),

    CONSTRAINT sc_warehouse_operations_loading_chk
        CHECK (loading_bays_active >= 0),

    CONSTRAINT sc_warehouse_operations_unloading_chk
        CHECK (unloading_bays_active >= 0),

    CONSTRAINT sc_warehouse_operations_queue_chk
        CHECK (queue_depth >= 0),

    CONSTRAINT sc_warehouse_operations_congestion_chk
        CHECK (congestion_factor > 0),

    CONSTRAINT sc_warehouse_operations_state_chk
        CHECK (operating_state IN ('NORMAL', 'BUSY', 'CONGESTED'))
);

-- Convert to a TimescaleDB hypertable.
-- No standalone primary/unique key is used because TimescaleDB requires
-- partition columns to participate in unique constraints.
SELECT create_hypertable(
    'public.sc_warehouse_operations',
    'time',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS sc_warehouse_operations_time_idx
    ON public.sc_warehouse_operations ("time" DESC);

CREATE INDEX IF NOT EXISTS sc_warehouse_operations_warehouse_time_idx
    ON public.sc_warehouse_operations (warehouse_id, "time" DESC);

CREATE INDEX IF NOT EXISTS sc_warehouse_operations_run_idx
    ON public.sc_warehouse_operations (run_id);

COMMENT ON TABLE public.sc_warehouse_operations IS
    'Supply Chain v3 warehouse operational telemetry. Authoritative source for loading/unloading activity, queue depth, congestion, and operating state.';

COMMENT ON COLUMN public.sc_warehouse_operations.operating_state IS
    'Operational state derived from warehouse workload: NORMAL, BUSY, or CONGESTED.';

COMMIT;
