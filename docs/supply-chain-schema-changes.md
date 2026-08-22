# Supply Chain v3 — Schema Changes

## 1. Purpose

This document maps the Supply Chain v3 domain and simulation design onto PostgreSQL and TimescaleDB.

It defines:

- which current tables remain,
- which columns retain or change semantics,
- which columns should be added,
- which new configuration/metadata tables are required,
- how events should evolve,
- what remains runtime-only,
- how TimescaleDB hypertables and continuous aggregates are affected,
- and how the project should migrate from the current synthetic v2 dataset to v3.

This document is a design specification. It is not yet a migration script.

Primary inputs:

```text
requirements.md
shipment-lifecycle.md
domain-model.md
simulation-rules.md
current PostgreSQL/TimescaleDB schema
```

---

# 2. Schema Design Principles

## 2.1 Preserve Useful Existing Tables

Supply Chain v3 SHOULD evolve the current schema rather than replace every table.

The existing model already has useful separation among:

```text
sc_warehouses
sc_vehicles
sc_shipments
sc_events
sc_fleet_telemetry
sc_warehouse_env
```

That structure remains valid.

---

## 2.2 Business Truth Versus Runtime State

Only state that provides business truth, analytics value, traceability, or validation value should be persisted.

Runtime-only simulation details should remain in Python unless there is a clear analytical requirement.

Example runtime-only candidates:

```text
temporary route speed multiplier
queue position
internal event timer
recoverable delay cache
short-lived RNG state
```

---

## 2.3 Preserve Time-Series Separation

High-frequency measurements remain separate from transactional/reference data.

```text
Reference/configuration:
    sc_warehouses
    sc_vehicles
    sc_routes
    sc_cargo_profiles

Transactional:
    sc_shipments
    sc_events
    sc_simulation_runs

Time series:
    sc_fleet_telemetry
    sc_warehouse_env
```

---

## 2.4 Avoid Storing Easily Derivable Values

Where practical, do not persist fields that can be reliably derived from authoritative columns.

Examples:

```text
late_delivery_pct
moving_utilization_pct
delay_minutes
```

These belong in SQL queries, views, or aggregates unless a later performance requirement justifies persistence.

---

# 3. Current Supply Chain Schema

The current database includes these primary objects:

```text
sc_warehouses
sc_vehicles
sc_shipments
sc_events
sc_fleet_telemetry
sc_warehouse_env
```

The current shipment table contains:

```text
shipment_id
vehicle_id
origin_wh_id
dest_wh_id
cargo_type
scheduled_departure
scheduled_arrival
actual_departure
actual_arrival
status
priority
```

The current fleet telemetry table contains:

```text
time
vehicle_id
shipment_id
lat
lon
speed_kmh
heading_deg
altitude_m
engine_rpm
fuel_level_pct
coolant_temp_c
cargo_temp_c
cargo_humidity_pct
door_open
harsh_braking
harsh_acceleration
idle_time_sec
odometer_km
geofence_zone
```

The current warehouse telemetry table contains:

```text
time
warehouse_id
zone
temp_c
humidity_pct
co2_ppm
occupancy_count
energy_kwh
door_events
```

---

# 4. Proposed v3 Schema Overview

```text
sc_simulation_runs          NEW
sc_warehouses               ALTER
sc_routes                   NEW
sc_vehicles                 ALTER
sc_cargo_profiles           NEW
sc_shipments                ALTER
sc_events                   ALTER
sc_fleet_telemetry          SMALL ALTER
sc_warehouse_env            SMALL ALTER / semantics update
```

Optional future configuration tables are discussed separately.

---

# 5. New Table: sc_simulation_runs

## 5.1 Purpose

`sc_simulation_runs` records how a generated dataset was produced.

This supports:

- reproducibility,
- QA traceability,
- debugging,
- version comparison,
- seed tracking.

---

## 5.2 Proposed Columns

```sql
CREATE TABLE sc_simulation_runs (
    run_id              bigserial PRIMARY KEY,
    generator_name      text NOT NULL,
    model_version       text NOT NULL,
    seed                bigint NOT NULL,
    simulation_start    timestamptz NOT NULL,
    simulation_end      timestamptz NOT NULL,
    generated_at        timestamptz NOT NULL DEFAULT now(),
    configuration_version text,
    status              text NOT NULL,
    metadata_json       jsonb
);
```

Suggested `status` values:

```text
STARTED
COMPLETED
FAILED
VALIDATION_FAILED
```

---

## 5.3 Validation

```text
simulation_end > simulation_start
```

---

# 6. sc_warehouses Changes

## 6.1 Existing Columns to Preserve

```text
warehouse_id
warehouse_name
lat
lon
timezone
capacity_pallets
wh_type
```

These remain useful master/reference attributes.

---

## 6.2 Proposed New Profile Columns

Recommended additions:

```text
loading_capacity
unloading_capacity
baseline_loading_min
baseline_unloading_min
congestion_sensitivity
cold_storage_capable
```

Possible DDL:

```sql
ALTER TABLE sc_warehouses
    ADD COLUMN loading_capacity integer,
    ADD COLUMN unloading_capacity integer,
    ADD COLUMN baseline_loading_min numeric(6,2),
    ADD COLUMN baseline_unloading_min numeric(6,2),
    ADD COLUMN congestion_sensitivity numeric(5,3),
    ADD COLUMN cold_storage_capable boolean DEFAULT false;
```

---

## 6.3 What Not to Store Here

Do not store transient warehouse state such as:

```text
current queue depth
current congestion state
active loading count
```

in the master table unless a later real-time operational requirement needs current-state persistence.

Those values can be represented in simulation runtime state and reflected through events/telemetry.

---

# 7. New Table: sc_routes

## 7.1 Purpose

Route characteristics are currently embedded in Python distance dictionaries.

v3 requires directional, persistent, queryable route profiles.

---

## 7.2 Proposed Columns

```sql
CREATE TABLE sc_routes (
    route_id                  serial PRIMARY KEY,
    origin_wh_id              integer NOT NULL,
    dest_wh_id                integer NOT NULL,
    distance_km               numeric(8,2) NOT NULL,
    nominal_speed_kmh         numeric(6,2) NOT NULL,
    minimum_speed_kmh         numeric(6,2),
    maximum_speed_kmh         numeric(6,2),
    baseline_travel_min       numeric(8,2),
    congestion_sensitivity    numeric(5,3),
    weather_sensitivity       numeric(5,3),
    morning_peak_factor       numeric(5,3) DEFAULT 1.0,
    evening_peak_factor       numeric(5,3) DEFAULT 1.0,
    overnight_factor          numeric(5,3) DEFAULT 1.0,
    demand_weight             numeric(6,3) DEFAULT 1.0,
    disruption_probability    numeric(7,6),
    active                    boolean NOT NULL DEFAULT true,

    FOREIGN KEY (origin_wh_id)
        REFERENCES sc_warehouses(warehouse_id),

    FOREIGN KEY (dest_wh_id)
        REFERENCES sc_warehouses(warehouse_id),

    UNIQUE (origin_wh_id, dest_wh_id),

    CHECK (origin_wh_id <> dest_wh_id),
    CHECK (distance_km > 0)
);
```

---

## 7.3 Directionality

The unique key:

```text
(origin_wh_id, dest_wh_id)
```

makes:

```text
Houston → Phoenix
```

different from:

```text
Phoenix → Houston
```

This is intentional.

---

# 8. sc_vehicles Changes

## 8.1 Existing Columns to Preserve

```text
vehicle_id
vehicle_reg
vehicle_type
max_payload_kg
fuel_type
fleet_operator
year_manufactured
```

---

## 8.2 Proposed v3 Profile Columns

```text
fuel_efficiency_factor
reliability_factor
condition_factor
cruise_speed_factor
maintenance_risk_factor
reefer_capable
```

Possible DDL:

```sql
ALTER TABLE sc_vehicles
    ADD COLUMN fuel_efficiency_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN reliability_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN condition_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN cruise_speed_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN maintenance_risk_factor numeric(5,3) DEFAULT 1.0,
    ADD COLUMN reefer_capable boolean DEFAULT false;
```

---

## 8.3 Design Decision

These are stable vehicle profile attributes.

Do not store transient current-state fields such as:

```text
current fuel
current warehouse
current speed
```

in `sc_vehicles`.

Those belong in telemetry/runtime state.

---

# 9. New Table: sc_cargo_profiles

## 9.1 Purpose

Cargo behavior should no longer depend on scattered Python string comparisons.

---

## 9.2 Proposed Columns

```sql
CREATE TABLE sc_cargo_profiles (
    cargo_type              text PRIMARY KEY,
    requires_reefer         boolean NOT NULL DEFAULT false,
    target_temp_c           numeric(6,2),
    min_temp_c              numeric(6,2),
    max_temp_c              numeric(6,2),
    target_humidity_pct     numeric(6,2),
    handling_sensitivity    numeric(5,3) DEFAULT 1.0,
    loading_time_factor     numeric(5,3) DEFAULT 1.0,
    active                  boolean NOT NULL DEFAULT true
);
```

Example rows:

```text
FROZEN_FOOD
FRESH_PRODUCE
PHARMA
GENERAL_FREIGHT
CONSUMER_GOODS
ELECTRONICS
FUEL
CHEMICALS
LIQUID_BULK
```

---

# 10. sc_shipments — Major v3 Change

This is the most important schema change.

---

## 10.1 Existing Columns to Preserve

```text
shipment_id
vehicle_id
origin_wh_id
dest_wh_id
cargo_type
scheduled_departure
scheduled_arrival
actual_departure
actual_arrival
priority
```

---

## 10.2 Current status Problem

The existing `status` column currently mixes lifecycle and delivery performance:

```text
DELIVERED
DELAYED
IN_TRANSIT
```

v3 separates those concepts.

---

## 10.3 Rename status to lifecycle_status

Recommended migration:

```sql
ALTER TABLE sc_shipments
    RENAME COLUMN status TO lifecycle_status;
```

New allowed values:

```text
PLANNED
READY
IN_TRANSIT
ARRIVED
DELIVERED
```

---

## 10.4 Add route_id

```sql
ALTER TABLE sc_shipments
    ADD COLUMN route_id integer
        REFERENCES sc_routes(route_id);
```

This makes the directional route explicit.

---

## 10.5 Add estimated_arrival

```sql
ALTER TABLE sc_shipments
    ADD COLUMN estimated_arrival timestamptz;
```

Semantics:

```text
dynamic ETA
```

This field may change while the shipment is active.

---

## 10.6 Add delivery_completed_at

```sql
ALTER TABLE sc_shipments
    ADD COLUMN delivery_completed_at timestamptz;
```

This supports the new distinction:

```text
ARRIVED
vs
DELIVERED
```

---

## 10.7 Add simulation run lineage

Recommended:

```sql
ALTER TABLE sc_shipments
    ADD COLUMN run_id bigint
        REFERENCES sc_simulation_runs(run_id);
```

This allows a shipment to be traced to the exact generator run.

---

## 10.8 Proposed v3 sc_shipments Shape

Conceptually:

```sql
sc_shipments (
    shipment_id,
    run_id,
    vehicle_id,
    route_id,
    origin_wh_id,
    dest_wh_id,
    cargo_type,
    priority,

    scheduled_departure,
    scheduled_arrival,
    estimated_arrival,

    actual_departure,
    actual_arrival,
    delivery_completed_at,

    lifecycle_status
)
```

---

# 11. Should performance_status Be Stored?

Recommendation:

> Do not persist it initially.

For active shipments it can be derived using:

```text
estimated_arrival
scheduled_arrival
AT_RISK threshold
```

For completed shipments:

```text
actual_arrival
scheduled_arrival
```

Example:

```sql
CASE
    WHEN lifecycle_status IN ('PLANNED', 'READY', 'IN_TRANSIT')
         AND estimated_arrival > scheduled_arrival
        THEN 'LATE'

    WHEN lifecycle_status IN ('PLANNED', 'READY', 'IN_TRANSIT')
         AND estimated_arrival > scheduled_arrival - INTERVAL '15 minutes'
        THEN 'AT_RISK'

    WHEN lifecycle_status IN ('ARRIVED', 'DELIVERED')
         AND actual_arrival > scheduled_arrival
        THEN 'LATE'

    ELSE 'ON_TIME'
END
```

The exact threshold will come from configuration.

Persisting a derivable status risks disagreement between:

```text
timestamps
and
stored label
```

---

# 12. Should delay_minutes Be Stored?

Recommendation:

> No.

For completed shipments:

```sql
EXTRACT(
    EPOCH FROM (actual_arrival - scheduled_arrival)
) / 60.0
```

already gives delay severity.

For active shipments:

```text
estimated_arrival - scheduled_arrival
```

provides ETA variance.

Use SQL/views when needed.

---

# 13. sc_events — Expand Event Context

The existing event table already provides a good general structure:

```text
time
event_id
shipment_id
event_type
location_lat
location_lon
warehouse_id
detail_json
severity
```

v3 should preserve it and add enough relational context for efficient analytics.

---

## 13.1 Add vehicle_id

```sql
ALTER TABLE sc_events
    ADD COLUMN vehicle_id integer
        REFERENCES sc_vehicles(vehicle_id);
```

---

## 13.2 Add route_id

```sql
ALTER TABLE sc_events
    ADD COLUMN route_id integer
        REFERENCES sc_routes(route_id);
```

---

## 13.3 Add run_id

```sql
ALTER TABLE sc_events
    ADD COLUMN run_id bigint
        REFERENCES sc_simulation_runs(run_id);
```

---

## 13.4 Add cause_code

Recommended:

```sql
ALTER TABLE sc_events
    ADD COLUMN cause_code text;
```

Example values:

```text
TRAFFIC_CONGESTION
TRAFFIC_INCIDENT
HEAVY_RAIN
WAREHOUSE_QUEUE
LOW_FUEL
MECHANICAL_DEGRADATION
REEFER_FAULT
```

`event_type` tells us:

> What happened?

`cause_code` tells us:

> Why?

Example:

```text
event_type = ETA_UPDATED
cause_code = TRAFFIC_CONGESTION
```

---

## 13.5 Keep detail_json

`detail_json` remains useful for event-specific attributes.

Examples:

```json
{
  "old_eta": "...",
  "new_eta": "...",
  "delta_minutes": 22.4
}
```

or:

```json
{
  "speed_factor": 0.58,
  "expected_duration_minutes": 35
}
```

This is preferable to adding dozens of nullable event-specific columns.

---

# 14. Event ID

The current text `event_id` is acceptable.

Recommendation:

- retain it,
- make it NOT NULL,
- add uniqueness.

Conceptually:

```sql
ALTER TABLE sc_events
    ALTER COLUMN event_id SET NOT NULL;

CREATE UNIQUE INDEX ...
```

Exact implementation will depend on whether event IDs are deterministic under seeded replay.

---

# 15. sc_fleet_telemetry — Preserve Core Shape

The existing fleet telemetry schema is already broad enough for v3.

Core fields remain useful:

```text
time
vehicle_id
shipment_id
lat
lon
speed_kmh
heading_deg
altitude_m
engine_rpm
fuel_level_pct
coolant_temp_c
cargo_temp_c
cargo_humidity_pct
door_open
harsh_braking
harsh_acceleration
idle_time_sec
odometer_km
geofence_zone
```

---

# 16. Fleet Telemetry Proposed Additions

## 16.1 run_id

Recommended:

```sql
ALTER TABLE sc_fleet_telemetry
    ADD COLUMN run_id bigint
        REFERENCES sc_simulation_runs(run_id);
```

This makes telemetry lineage explicit.

---

## 16.2 Optional operating_state

Potentially useful:

```text
PARKED
LOADING
URBAN
HIGHWAY
FUEL_STOP
UNLOADING
TURNAROUND
OUT_OF_SERVICE
```

However:

> Do not add this until architecture/analytics confirm that `geofence_zone`, lifecycle, and event joins are insufficient.

Initial recommendation: **defer persisted `operating_state`**.

Keep it runtime-only unless clearly needed.

---

# 17. Geofence Semantics

Retain `geofence_zone`, but change its meaning from primarily speed-derived classification to location/domain-derived classification.

Expected values may include:

```text
ORIGIN_WAREHOUSE
DESTINATION_WAREHOUSE
URBAN
HIGHWAY
FUEL_STOP
```

No schema change is required for this semantic improvement.

---

# 18. sc_warehouse_env — Preserve Table

The current table remains suitable as a TimescaleDB hypertable.

Existing columns:

```text
time
warehouse_id
zone
temp_c
humidity_pct
co2_ppm
occupancy_count
energy_kwh
door_events
```

The primary v3 change is **how values are generated**, not necessarily the table structure.

Warehouse environmental telemetry should become coupled to:

```text
facility activity
occupancy
door activity
cold-storage load
warehouse congestion
```

---

# 19. sc_warehouse_env Proposed Addition

Add run lineage:

```sql
ALTER TABLE sc_warehouse_env
    ADD COLUMN run_id bigint
        REFERENCES sc_simulation_runs(run_id);
```

---

# 20. Should Warehouse Congestion Be Persisted in sc_warehouse_env?

Possible column:

```text
operating_state
```

Recommendation:

> Probably yes, but only if we want direct Grafana/SQL analysis of congestion versus dwell.

A useful field might be:

```sql
operating_state text
```

with:

```text
NORMAL
BUSY
CONGESTED
```

This has substantial analytical value and is hard to reconstruct perfectly from telemetry alone.

Proposed:

```sql
ALTER TABLE sc_warehouse_env
    ADD COLUMN operating_state text;
```

---

# 21. New Table Versus JSON for Delay Attribution

We discussed delay contributors:

```text
traffic
weather
fuel
mechanical
warehouse
destination dwell
```

Two designs are possible.

### Option A — Dedicated sc_delay_contributions table

Pros:

```text
easy SQL
clean relational analytics
explicit attribution
```

Cons:

```text
more schema
more persistence complexity
potential duplication with events
```

### Option B — Use sc_events + detail_json

Pros:

```text
uses existing event model
less schema
flexible
```

Cons:

```text
some analytical queries require JSON extraction
```

### Decision

For v3:

> Use `sc_events` + `cause_code` + `detail_json`.

Do not create `sc_delay_contributions` yet.

A dedicated table can be reconsidered if analytics demonstrate a real need.

---

# 22. New Route and Cargo Master Data Are Relational Objects

This is an important design distinction.

`sc_routes` and `sc_cargo_profiles` are ordinary PostgreSQL reference/configuration tables.

They are **not TimescaleDB hypertables** because they do not represent high-frequency time-series measurements.

---

# 23. TimescaleDB Object Classification

v3 should deliberately distinguish object types.

## Ordinary PostgreSQL tables

```text
sc_simulation_runs
sc_warehouses
sc_routes
sc_vehicles
sc_cargo_profiles
sc_shipments
sc_events
```

`sc_events` contains timestamps, but it does not necessarily need to become a hypertable unless event volume/query patterns justify it.

---

## TimescaleDB hypertables

Keep:

```text
sc_fleet_telemetry
sc_warehouse_env
```

These are high-volume time-series measurements and benefit directly from chunking and continuous aggregation.

---

## TimescaleDB continuous aggregates

Current/known analytical objects include fleet and warehouse aggregates such as:

```text
sc_fleet_daily
sc_fleet_5min
sc_warehouse_hourly
```

These are database/platform-specific objects and must be reviewed whenever base telemetry semantics change.

---

# 24. sc_fleet_5min Impact

The existing 5-minute continuous aggregate remains conceptually valuable.

It currently supports metrics such as:

```text
sample_count
avg/max speed
avg/max RPM
fuel
cargo temperature
harsh braking
harsh acceleration
door samples
idle time
odometer
```

Most of those remain valid in v3.

---

## 24.1 Rebuild Required After v3 Regeneration

Because v3 changes the meaning and statistical behavior of fleet telemetry:

```text
old synthetic rows
```

must not remain mixed with:

```text
v3 rows
```

The aggregate should be refreshed/rebuilt after the new v3 dataset is generated.

---

## 24.2 run_id in Continuous Aggregate?

Recommendation:

> Do not include `run_id` in the primary production-style `sc_fleet_5min` if the database is reset between synthetic runs.

If multiple simulation runs are intentionally retained concurrently, then `run_id` must become part of grouping/filtering.

For the current project workflow, we generally clear generated data before the authoritative regeneration, so run lineage in raw rows is sufficient.

---

# 25. sc_fleet_daily Impact

The existing daily continuous aggregate groups fleet telemetry by:

```text
day bucket
vehicle_id
```

and calculates metrics including:

```text
trips_count
avg/max speed
idle
harsh events
fuel
```

The object remains conceptually valid.

However, its definition SHOULD be reviewed after v3 because:

- idle semantics will improve,
- shipment lifecycle changes may change trip counting assumptions,
- fuel stops become explicit.

Do not automatically preserve the exact current definition just because the object already exists.

---

# 26. sc_warehouse_hourly Impact

The existing hourly aggregate remains useful.

Its current measures include:

```text
temperature
humidity
CO2
peak occupancy
energy
door events
```

If `operating_state` is added to raw warehouse telemetry, the continuous aggregate may optionally include:

```text
congestion sample count
minutes congested
```

This is a later design choice, not required for the first v3 generation.

---

# 27. Index Strategy

The exact indexes will be implemented later, but the schema should support expected business queries.

Recommended indexes on transactional tables:

```text
sc_shipments(vehicle_id)
sc_shipments(route_id)
sc_shipments(origin_wh_id)
sc_shipments(dest_wh_id)
sc_shipments(lifecycle_status)
sc_shipments(scheduled_departure)
sc_shipments(actual_arrival)
sc_shipments(run_id)

sc_events(shipment_id)
sc_events(vehicle_id)
sc_events(route_id)
sc_events(event_type)
sc_events(cause_code)
sc_events(time)
```

Do not create indexes blindly; validate actual plans after implementation.

---

# 28. Constraints

v3 should use database constraints for structural invariants where feasible.

Examples:

```sql
CHECK (scheduled_arrival > scheduled_departure)
```

Possible lifecycle-related constraints are more complex because they depend on multiple nullable fields.

Conceptually:

```text
IN_TRANSIT → actual_departure NOT NULL, actual_arrival NULL
ARRIVED    → actual_arrival NOT NULL
DELIVERED  → delivery_completed_at NOT NULL
```

These may be enforced through:

- CHECK constraints,
- application/domain validation,
- acceptance tests,

or a combination.

Do not force highly complex database constraints if they make the schema brittle, but critical invariants must be enforced somewhere authoritative.

---

# 29. Foreign Keys

Preserve current relationships:

```text
sc_shipments.vehicle_id      → sc_vehicles
sc_shipments.origin_wh_id    → sc_warehouses
sc_shipments.dest_wh_id      → sc_warehouses

sc_fleet_telemetry.vehicle_id → sc_vehicles
sc_fleet_telemetry.shipment_id → sc_shipments

sc_events.shipment_id        → sc_shipments
sc_events.warehouse_id       → sc_warehouses

sc_warehouse_env.warehouse_id → sc_warehouses
```

Add:

```text
sc_shipments.route_id        → sc_routes
sc_shipments.run_id          → sc_simulation_runs

sc_events.vehicle_id         → sc_vehicles
sc_events.route_id           → sc_routes
sc_events.run_id             → sc_simulation_runs

sc_fleet_telemetry.run_id    → sc_simulation_runs
sc_warehouse_env.run_id      → sc_simulation_runs
```

---

# 30. Cargo Foreign Key

Recommended:

```text
sc_shipments.cargo_type
    → sc_cargo_profiles.cargo_type
```

This prevents invalid cargo-type strings.

The migration must first ensure all current cargo values exist in the profile table.

---

# 31. Lifecycle Status Constraint

Recommended values:

```text
PLANNED
READY
IN_TRANSIT
ARRIVED
DELIVERED
```

Possible implementation:

```sql
CHECK (
    lifecycle_status IN (
        'PLANNED',
        'READY',
        'IN_TRANSIT',
        'ARRIVED',
        'DELIVERED'
    )
)
```

A PostgreSQL ENUM is intentionally not recommended initially because text + CHECK is easier to evolve during the learning project.

---

# 32. Priority Constraint

Recommended:

```sql
CHECK (
    priority IN (
        'STANDARD',
        'EXPEDITED',
        'CRITICAL'
    )
)
```

Again, use text + CHECK unless later architecture provides a stronger reason for an ENUM/reference table.

---

# 33. Event Type and cause_code

Do not create PostgreSQL ENUMs for the event vocabulary at this stage.

Reason:

Event types are likely to evolve during v3 implementation.

Use:

```text
text
+
application validation
+
optional CHECK after vocabulary stabilizes
```

---

# 34. Simulation Run Lineage Strategy

There are two valid project workflows:

## Workflow A — Authoritative reset

```text
truncate generated data
run v3
validate
use one active dataset
```

This remains the recommended learning workflow.

## Workflow B — Multiple retained simulation runs

```text
run 41
run 42
run 43
```

coexist for comparison.

The proposed `run_id` schema supports both.

However, Grafana queries would need explicit run filtering under Workflow B.

For v3 implementation:

> Continue using authoritative reset as the default workflow.

---

# 35. Generated Data Reset Strategy

Before v3 validation/regeneration, clear generated facts:

```text
sc_events
sc_fleet_telemetry
sc_warehouse_env
sc_shipments
```

Preserve/reference or intentionally reseed:

```text
sc_vehicles
sc_warehouses
sc_routes
sc_cargo_profiles
```

Simulation metadata may either be preserved as history or cleared during early development.

---

# 36. Master Data Seeding

v3 will require deterministic master/configuration data for:

```text
warehouses
routes
vehicles
cargo profiles
```

This data should be seeded separately from high-volume telemetry generation.

The generator should not silently invent master records each time unless that behavior is explicitly part of configuration initialization.

---

# 37. Migration Strategy From Current Development Schema

Because all current operational data is synthetic, we do not need a production-style zero-downtime migration.

Recommended development migration:

```text
1. Back up schema definition
2. Add/alter v3 reference tables and columns
3. Seed route and cargo configuration
4. Preserve warehouse/vehicle master records
5. Clear generated v2 shipment/event/telemetry data
6. Validate schema
7. Run v3 2-day simulation
8. Validate data-quality invariants
9. Rebuild/refresh continuous aggregates
10. Run SQL/Grafana validation
11. Clear test data
12. Generate authoritative 365-day v3 dataset
13. Refresh/rebuild continuous aggregates
```

---

# 38. No Need for Backward Compatibility With v2 Synthetic Rows

Important project decision:

> v3 does not need to support mixed v2 and v3 generated records.

The current data is synthetic and can be regenerated.

This greatly simplifies:

- lifecycle semantics,
- status changes,
- event model changes,
- route assignment,
- telemetry interpretation.

---

# 39. Recommended Migration Artifact

During implementation, create an explicit SQL migration file rather than manually applying scattered `ALTER TABLE` statements.

Suggested project location:

```text
sql/
migrations/
    003_supply_chain_v3.sql
```

The exact repository structure will be finalized in `architecture.md`.

---

# 40. Proposed v3 Table Relationship Diagram

```text
sc_simulation_runs
      │
      ├──────────────┬────────────────────┐
      │              │                    │
      ▼              ▼                    ▼
sc_shipments   sc_fleet_telemetry   sc_warehouse_env
      │              │
      │              │
      ▼              ▼
 sc_events       sc_vehicles
      │
      │
      ├──────────── sc_routes
      │                 │
      │                 ├── origin warehouse
      │                 └── destination warehouse
      │
      ├──────────── sc_cargo_profiles
      │
      └──────────── sc_vehicles

sc_warehouses
      ▲     ▲
      │     │
      └─ sc_routes ─┘
```

---

# 41. Proposed Table Classification

| Object | Type | v3 Action |
|---|---|---|
| `sc_simulation_runs` | PostgreSQL table | **NEW** |
| `sc_warehouses` | PostgreSQL table | ALTER |
| `sc_routes` | PostgreSQL table | **NEW** |
| `sc_vehicles` | PostgreSQL table | ALTER |
| `sc_cargo_profiles` | PostgreSQL table | **NEW** |
| `sc_shipments` | PostgreSQL table | **MAJOR ALTER** |
| `sc_events` | PostgreSQL table | ALTER |
| `sc_fleet_telemetry` | TimescaleDB hypertable | SMALL ALTER |
| `sc_warehouse_env` | TimescaleDB hypertable | SMALL ALTER |
| `sc_fleet_5min` | Continuous aggregate | REVIEW/REFRESH |
| `sc_fleet_daily` | Continuous aggregate view | REVIEW |
| `sc_warehouse_hourly` | Continuous aggregate view | REVIEW |

---

# 42. Important TimescaleDB Note

`sc_fleet_telemetry` and `sc_warehouse_env` are not ordinary PostgreSQL tables from an operational perspective once converted to hypertables.

TimescaleDB manages their physical rows through chunks.

Likewise:

```text
sc_fleet_5min
sc_fleet_daily
sc_warehouse_hourly
```

are analytical abstractions backed by TimescaleDB materialization.

When changing base telemetry columns or semantics:

> Do not manipulate `_timescaledb_internal` objects directly.

Changes should be made through the public hypertable/continuous-aggregate interfaces.

---

# 43. Schema Changes We Are Deliberately Not Making

v3 does NOT require new relational entities for:

```text
driver
customer
order
inventory
maintenance work order
fuel station
road segment
weather station
financial cost
```

Those remain outside the v3 boundary.

---

# 44. Open Schema Decisions

The following should be settled during architecture/implementation review:

1. Whether `operating_state` belongs in `sc_warehouse_env`.
2. Whether `run_id` should be present on every high-volume telemetry row or inferred by generation window.
3. Whether `SHIPMENT_READY` needs to be persisted as an event.
4. Whether lifecycle validation should use database CHECK constraints beyond basic timing rules.
5. Whether `event_id` should remain deterministic text or become an internal numeric primary key plus external event key.
6. Whether `sc_events` volume justifies conversion to a TimescaleDB hypertable later.

None of these blocks the core v3 design.

---

# 45. Recommended Decisions for Lock-In

The following should be considered locked unless implementation reveals a contradiction:

```text
1. Keep existing primary Supply Chain table separation.

2. Add sc_simulation_runs.

3. Add directional sc_routes.

4. Add sc_cargo_profiles.

5. Rename shipment status semantics to lifecycle_status.

6. Add estimated_arrival.

7. Add delivery_completed_at.

8. Add route_id to shipments.

9. Add run lineage.

10. Keep performance state derived initially.

11. Keep delay minutes derived.

12. Expand sc_events rather than creating a separate delay table.

13. Preserve sc_fleet_telemetry as a TimescaleDB hypertable.

14. Preserve sc_warehouse_env as a TimescaleDB hypertable.

15. Review continuous aggregate definitions after v3 behavior is implemented.

16. Do not retain mixed v2/v3 synthetic operational data.

17. Use ordinary PostgreSQL tables for route/cargo/configuration objects.

18. Do not touch TimescaleDB internal materialization tables directly.
```

---

# 46. Requirement Traceability

Examples:

```text
SC-FR-003
    → actual_arrival remains nullable until ARRIVED

SC-FR-004
    → estimated_arrival

SC-FR-012
    → sc_simulation_runs / run_id

SC-DR-005
    → sc_routes

SC-DR-008
    → expanded sc_warehouses

SC-DR-011
    → expanded sc_vehicles

SC-DR-020
    → sc_cargo_profiles

SC-FR-006 / 007
    → expanded sc_events

SC-AR-004
    → hypertable/bounded-memory design preserved
```

---

# 47. Next Artifact

The next document is:

```text
docs/model-v3/supply-chain/architecture.md
```

That document will define the Python/package structure and responsibilities for:

```text
configuration
simulation context/clock
domain entities
shipment planning
routing
warehouse behavior
vehicle behavior
cargo behavior
event handling
telemetry generation
validation
persistence
CLI/orchestration
```

It will also specify how the current single `generate_supply_chain.py` evolves into a modular v3 implementation without losing the working bounded-memory insertion model.
