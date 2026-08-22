# Supply Chain v3 — Domain Model

## 1. Purpose

This document defines the core domain entities, persistent state, relationships, and responsibilities for Supply Chain Generator v3.

It builds on:

```text
docs/model-v3/supply-chain/requirements.md
docs/model-v3/supply-chain/shipment-lifecycle.md
```

The domain model is intentionally separate from the database schema.

The purpose here is to define:

> What entities exist in the simulation, what state they own, and how they interact.

The later `schema-changes.md` document will determine which domain attributes must be persisted directly in PostgreSQL.

---

# 2. Domain Model Overview

Supply Chain v3 centers on seven core domain concepts:

```text
SimulationRun
     │
     ├── Warehouse
     ├── Route
     ├── Vehicle
     ├── CargoProfile
     ├── Shipment
     └── OperationalEvent
```

The primary operational relationship is:

```text
Warehouse
    │
    ├── origin
    │
Shipment ───── Vehicle
    │
    ├── destination
    │
    └── Route
```

Operational events modify state owned by these entities.

---

# 3. SimulationRun

## 3.1 Responsibility

`SimulationRun` represents one deterministic generation run.

It owns the top-level simulation context.

Required state:

```text
run_id
model_version
seed
simulation_start
simulation_end
generated_at
current_time
configuration_version
```

Potential runtime-only state:

```text
random_generator
event_queue
active_shipments
vehicle_registry
warehouse_registry
route_registry
```

---

## 3.2 Invariants

```text
simulation_start < simulation_end

current_time >= simulation_start
current_time <= simulation_end
```

The same:

```text
model_version
seed
configuration
simulation_start
simulation_end
```

should reproduce equivalent business behavior.

---

# 4. Warehouse

## 4.1 Responsibility

`Warehouse` represents a persistent logistics facility.

A warehouse is not merely a coordinate.

It owns facility characteristics and dynamic operating state.

---

## 4.2 Stable Profile

Suggested configuration attributes:

```text
warehouse_id
warehouse_name
latitude
longitude
warehouse_type
operating_hours
loading_capacity
unloading_capacity
cold_storage_capable
baseline_loading_minutes
baseline_unloading_minutes
congestion_sensitivity
```

---

## 4.3 Dynamic State

Suggested runtime state:

```text
operating_state
active_loading_count
active_unloading_count
queue_depth
current_congestion_factor
current_dwell_multiplier
```

Possible operating states:

```text
NORMAL
BUSY
CONGESTED
```

The final state vocabulary will be defined in `simulation-rules.md`.

---

## 4.4 Behavior

Warehouse state may influence:

```text
shipment readiness
loading dwell
departure delay
destination dwell
delivery completion
priority handling
cargo handling
```

A warehouse SHALL NOT directly set shipment lateness.

It influences operational timing, which may then affect ETA and final performance.

---

# 5. Route

## 5.1 Responsibility

`Route` represents a directional connection between two warehouses.

A route is directional:

```text
Houston → Phoenix
```

is a different domain object from:

```text
Phoenix → Houston
```

even when both use the same physical distance approximation.

---

## 5.2 Stable Profile

Suggested attributes:

```text
route_id
origin_warehouse_id
destination_warehouse_id
distance_km
nominal_speed_kmh
minimum_speed_kmh
maximum_speed_kmh
baseline_travel_minutes
congestion_sensitivity
weather_sensitivity
morning_peak_factor
evening_peak_factor
overnight_factor
disruption_probability
```

---

## 5.3 Dynamic State

Runtime state may include:

```text
traffic_state
weather_impact
temporary_speed_factor
active_disruptions
```

Potential traffic states:

```text
FREE_FLOW
MODERATE
HEAVY
INCIDENT
```

---

## 5.4 Behavior

Route state influences:

```text
vehicle target speed
remaining travel time
ETA
schedule recovery opportunity
```

Route state SHALL NOT rewrite the original shipment schedule.

---

# 6. Vehicle

## 6.1 Responsibility

`Vehicle` represents a persistent fleet asset.

It owns physical and operational state across shipments.

---

## 6.2 Stable Profile

Existing characteristics should be preserved where applicable:

```text
vehicle_id
vehicle_reg
vehicle_type
max_payload_kg
fuel_type
fleet_operator
year_manufactured
```

New v3 profile characteristics should include concepts such as:

```text
fuel_capacity_pct_or_equivalent
fuel_efficiency_factor
reliability_factor
condition_factor
acceleration_factor
cruise_speed_factor
maintenance_risk_factor
reefer_capable
```

Exact persisted fields will be decided later.

---

## 6.3 Dynamic State

Runtime state:

```text
current_warehouse_id
latitude
longitude
heading
speed_kmh
fuel_level_pct
odometer_km
engine_rpm
idle_time_sec
availability_state
active_shipment_id
condition_state
reefer_state
```

Possible availability states:

```text
AVAILABLE
RESERVED
LOADING
IN_TRANSIT
UNLOADING
TURNAROUND
OUT_OF_SERVICE
```

Not all states must be persisted.

---

## 6.4 Invariants

```text
0 <= fuel_level_pct <= 100
speed_kmh >= 0
odometer_km never decreases
at most one active shipment
```

If:

```text
active_shipment_id IS NOT NULL
```

the shipment SHALL reference the same vehicle.

---

# 7. CargoProfile

## 7.1 Responsibility

`CargoProfile` defines handling and environmental requirements for a cargo class.

This prevents cargo behavior from being encoded through ad hoc string comparisons throughout telemetry code.

---

## 7.2 Suggested Attributes

```text
cargo_type
requires_reefer
target_temp_c
min_temp_c
max_temp_c
target_humidity_pct
handling_sensitivity
loading_time_factor
priority_compatibility
```

Examples:

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

## 7.3 Behavior

Cargo profile influences:

```text
vehicle compatibility
warehouse compatibility
loading/unloading dwell
cargo telemetry
temperature excursion thresholds
```

---

# 8. Shipment

## 8.1 Responsibility

`Shipment` is the central business entity in Supply Chain v3.

It connects:

```text
vehicle
origin warehouse
destination warehouse
route
cargo
priority
schedule
lifecycle
ETA
business outcome
```

---

## 8.2 Identity and Assignment

Suggested state:

```text
shipment_id
vehicle_id
origin_warehouse_id
destination_warehouse_id
route_id
cargo_type
priority
```

---

## 8.3 Schedule State

```text
scheduled_departure
scheduled_arrival
estimated_arrival
actual_departure
actual_arrival
delivery_completed_at
```

The semantics are defined in `shipment-lifecycle.md`.

---

## 8.4 Lifecycle State

```text
PLANNED
READY
IN_TRANSIT
ARRIVED
DELIVERED
```

---

## 8.5 Performance State

Conceptually:

```text
ON_TIME
AT_RISK
LATE
```

Performance state MAY be derived rather than stored.

---

## 8.6 Runtime Execution State

Suggested runtime state:

```text
route_progress_pct
remaining_distance_km
current_eta
accumulated_delay_minutes
recoverable_buffer_minutes
origin_dwell_minutes
destination_dwell_minutes
active_delay_causes
```

---

## 8.7 Shipment Invariants

```text
scheduled_arrival > scheduled_departure

actual_departure IS NULL
    before IN_TRANSIT

actual_arrival IS NULL
    before ARRIVED

delivery_completed_at IS NULL
    before DELIVERED
```

Additionally:

```text
shipment.vehicle_id == active vehicle
shipment.route origin == shipment origin
shipment.route destination == shipment destination
```

---

# 9. OperationalEvent

## 9.1 Responsibility

`OperationalEvent` records meaningful operational occurrences or state transitions.

Events are not arbitrary log messages.

They must either:

- represent a lifecycle transition,
- represent a material state change,
- explain an analytical outcome,
- or provide meaningful auditability.

---

## 9.2 Suggested Event Structure

```text
event_id
event_time
event_type
shipment_id
vehicle_id
warehouse_id
route_id
severity
cause_code
detail
```

Not every reference must be populated for every event.

---

## 9.3 Core Event Types

Proposed v3 vocabulary:

```text
SHIPMENT_READY
PICKUP
DEPARTURE
SCAN

TRAFFIC_DELAY
WEATHER_DELAY
WAREHOUSE_DELAY
FUEL_STOP
MECHANICAL_WARNING

ETA_UPDATED
TEMP_EXCURSION

ARRIVAL
DELIVERY
```

---

## 9.4 Causal Role

Example:

```text
TRAFFIC_DELAY event
        ↓
route speed factor changes
        ↓
vehicle speed changes
        ↓
remaining travel time increases
        ↓
ETA changes
        ↓
ETA_UPDATED event
        ↓
performance may become AT_RISK or LATE
```

This causal chain is a core v3 design goal.

---

# 10. DelayContribution

`DelayContribution` is a domain concept that may be represented either as an explicit object or event metadata.

Suggested structure:

```text
cause
start_time
end_time
gross_delay_minutes
recovered_minutes
net_delay_minutes
```

Examples:

```text
WAREHOUSE
TRAFFIC
WEATHER
FUEL
MECHANICAL
DESTINATION_DWELL
```

The implementation does not require a separate database table unless later design shows clear analytical value.

---

# 11. ETA State

ETA should be treated as derived operational state.

Conceptual inputs:

```text
current simulation time
remaining distance
current route condition
vehicle capability
active disruptions
expected required stops
destination dwell expectations
recoverable schedule buffer
```

Output:

```text
estimated_arrival
```

ETA is therefore not generated independently.

---

# 12. Vehicle–Shipment Relationship

The relationship is:

```text
Vehicle 1 ───────< Shipment
```

A vehicle may execute many shipments over time.

At any instant:

```text
Vehicle → zero or one active Shipment
```

Never:

```text
Vehicle → two simultaneous active Shipments
```

---

# 13. Warehouse–Shipment Relationship

Each shipment requires:

```text
one origin Warehouse
one destination Warehouse
```

The same warehouse table supplies both relationships.

Conceptually:

```text
Warehouse (origin)
       │
       ▼
    Shipment
       │
       ▼
Warehouse (destination)
```

---

# 14. Route–Shipment Relationship

Each shipment executes one configured directional route:

```text
Shipment.route_id → Route
```

Multiple shipments may use the same route profile.

This is important because route behavior should persist across many shipments and therefore become visible analytically.

---

# 15. Cargo–Vehicle Compatibility

Before shipment assignment:

```text
CargoProfile
    +
Vehicle profile
    ↓
compatibility check
```

Example:

```text
PHARMA
requires_reefer = true

Vehicle 4
reefer_capable = false

assignment = INVALID
```

This should fail before telemetry generation begins.

---

# 16. Warehouse–Cargo Compatibility

Where configured, warehouse capability may also constrain cargo handling.

Example:

```text
FROZEN_FOOD
requires cold handling

Warehouse
cold_storage_capable = false

origin/destination assignment may be invalid
```

This level of compatibility is appropriate for v3 because it creates meaningful domain constraints without requiring inventory management.

---

# 17. Simulation Clock

All state transitions SHALL occur against one authoritative simulation clock.

Conceptually:

```text
SimulationRun.current_time
```

The generator should avoid independently calculating separate `now()` timestamps inside domain functions.

This is required for:

- deterministic replay,
- consistent event ordering,
- coherent telemetry,
- reproducible tests.

---

# 18. Randomness Ownership

The simulation should use an explicitly seeded random source owned by the simulation context.

Avoid:

```python
random.random()
```

scattered throughout domain modules without control.

Prefer conceptually:

```python
simulation.rng.random()
```

or injected domain-specific random sources.

The exact Python implementation belongs in `architecture.md`.

---

# 19. Domain State Versus Database State

Not every runtime attribute needs a database column.

Examples of likely runtime-only state:

```text
temporary route speed factor
recoverable schedule buffer
current queue position
short-lived mechanical warning timer
```

Persist only data that supports:

- business truth,
- reproducibility/traceability,
- analytics,
- operational event history,
- required validation.

This avoids turning the relational schema into a serialization of every Python object.

---

# 20. Proposed Domain Relationships

```text
SimulationRun
    │
    ├── owns simulation clock
    ├── owns deterministic RNG
    ├── references configuration
    │
    ├── Warehouse*
    │      │
    │      └── dynamic operating state
    │
    ├── Route*
    │      │
    │      └── dynamic route state
    │
    ├── Vehicle*
    │      │
    │      ├── persistent physical state
    │      └── 0..1 active Shipment
    │
    ├── CargoProfile*
    │
    ├── Shipment*
    │      │
    │      ├── origin Warehouse
    │      ├── destination Warehouse
    │      ├── Route
    │      ├── Vehicle
    │      ├── CargoProfile
    │      └── OperationalEvent*
    │
    └── validation/reporting
```

---

# 21. Example Domain State

A representative active shipment might look conceptually like:

```text
Shipment 1250
    lifecycle: IN_TRANSIT
    performance: AT_RISK

    vehicle: 4
    origin: Phoenix Central DC
    destination: Houston Distribution Hub
    route: PHX_HOU

    scheduled_departure: 08:00
    actual_departure:    08:17

    scheduled_arrival:   23:30
    estimated_arrival:   23:39
    actual_arrival:      NULL

    route_progress:      61%
    accumulated_delay:   24 min
    recovered_delay:      8 min

    active causes:
        traffic congestion
```

The corresponding vehicle might have:

```text
Vehicle 4
    availability: IN_TRANSIT
    speed: 63 km/h
    fuel: 48%
    active_shipment: 1250
```

The route might have:

```text
PHX_HOU
    traffic_state: HEAVY
    temporary_speed_factor: 0.72
```

Those states should tell one coherent story.

---

# 22. Domain Rules That Must Not Be Duplicated

Examples:

Cargo compatibility should exist in one authoritative rule, not separately in:

```text
shipment generator
telemetry generator
event generator
```

Likewise:

```text
late determination
ETA calculation
route speed limits
vehicle availability
```

should each have one authoritative domain implementation.

This reduces contradictory behavior.

---

# 23. Aggregate/Data-Warehouse Compatibility

The domain model must continue to support downstream TimescaleDB analytics.

High-frequency telemetry remains suitable for hypertables and continuous aggregates.

Examples:

```text
sc_fleet_telemetry
    ↓
sc_fleet_5min

sc_warehouse_env
    ↓
sc_warehouse_hourly
```

The v3 domain refactor SHALL NOT require Grafana to consume internal Python state.

Analytics must remain database-driven.

---

# 24. Domain Model Boundaries

The following are intentionally outside the v3 domain model:

```text
Driver
Customer
Order
InventoryItem
MaintenanceWorkOrder
FuelStation network
Carrier contract
Financial transaction
Road-network graph
```

These remain possible v4 entities.

Operational concepts such as fuel stops and mechanical warnings may still exist in v3 without introducing full domain entities for fuel stations or maintenance systems.

---

# 25. Requirement Mapping

Key mappings include:

```text
SC-DR-005 / 006 / 007
    → Route

SC-DR-008 / 009 / 010
    → Warehouse

SC-DR-011 / 012 / 013 / 014
    → Vehicle

SC-DR-015 / 016 / 017
    → Vehicle fuel state + OperationalEvent

SC-DR-018 / 019
    → Shipment priority behavior

SC-FR-006 / 007 / 008
    → OperationalEvent

SC-DR-020 / 021 / 022 / 023
    → CargoProfile + vehicle cargo state

SC-FR-009 / 010 / 011
    → runtime domain state feeding telemetry

SC-NFR-001 / 002
    → SimulationRun
```

---

# 26. Design Decisions Proposed for Lock-In

```text
1. Shipment remains the central business entity.

2. SimulationRun owns the authoritative simulation context.

3. Warehouse, Route, Vehicle, and CargoProfile are persistent domain concepts.

4. OperationalEvent records meaningful transitions and causes.

5. Route is directional.

6. Vehicle state persists across shipments.

7. Warehouse state persists across simultaneous shipment activity.

8. Cargo requirements are explicit configuration, not scattered string logic.

9. ETA is derived from current operational state.

10. Randomness is controlled by the simulation context.

11. Runtime state and database schema are deliberately separate concerns.

12. Full Driver, Customer, Inventory, Maintenance, and road-network entities remain outside v3.
```

---

# 27. Acceptance Criteria

The domain model is considered successfully implemented when a short simulation can demonstrate:

1. persistent vehicle state across consecutive shipments,
2. directional route differences,
3. warehouse congestion influencing multiple shipments,
4. cargo/vehicle compatibility enforcement,
5. operational events changing state,
6. ETA derived from current state,
7. telemetry reflecting the same active state,
8. deterministic replay using a fixed seed,
9. database persistence sufficient for analytics without exposing internal-only runtime fields,
10. automated validation of critical domain invariants.

---

## Next Artifact

The next document is:

```text
docs/model-v3/supply-chain/simulation-rules.md
```

That document will define how the entities in this domain model actually behave over time, including:

```text
shipment generation
vehicle assignment
warehouse dwell
route travel
traffic
weather
fuel
mechanical conditions
priority handling
cargo temperature
delay accumulation
schedule recovery
ETA updates
event generation
```
