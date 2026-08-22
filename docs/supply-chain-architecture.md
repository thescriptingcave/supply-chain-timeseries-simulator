# Supply Chain v3 — Architecture

## 1. Purpose

This document defines the Python/package architecture for Supply Chain Generator v3.

It translates the approved:

```text
requirements
shipment lifecycle
domain model
simulation rules
schema changes
```

into a maintainable implementation structure.

The architecture must preserve the strongest aspect of the current implementation:

> high-volume telemetry is generated and persisted in bounded memory rather than accumulating an entire historical dataset in RAM.

At the same time, v3 must separate business rules from orchestration and database persistence.

---

# 2. Architectural Goals

Supply Chain v3 SHALL be:

```text
modular
deterministic
testable
bounded-memory
domain-driven
database-aware
analytics-friendly
```

The implementation should make it possible to test:

```text
shipment lifecycle logic
route behavior
warehouse dwell
vehicle behavior
ETA calculation
event causality
cargo temperature
validation rules
```

without needing to generate a full 365-day dataset.

---

# 3. Current Architecture Problem

The current generator is primarily one large Python module containing:

```text
configuration
shipment creation
telemetry generation
warehouse generation
events
database insertion
CLI orchestration
```

That worked for v2, but v3 introduces enough state and business rules that continuing with one monolithic module would create:

```text
duplicated rules
hard-to-test functions
implicit state
fragile changes
tight DB coupling
```

The v3 design therefore moves to a package.

---

# 4. Proposed Package Structure

Recommended repository structure:

```text
generators/
└── supply_chain/
    ├── __init__.py
    ├── cli.py
    ├── config.py
    ├── context.py
    ├── models.py
    ├── lifecycle.py
    ├── planning.py
    ├── routing.py
    ├── warehouses.py
    ├── vehicles.py
    ├── cargo.py
    ├── events.py
    ├── telemetry.py
    ├── eta.py
    ├── validation.py
    ├── persistence.py
    └── generator.py
```

A lightweight compatibility entry point may remain:

```text
generators/generate_supply_chain.py
```

Its role should be only to call the new package CLI.

---

# 5. Compatibility Entry Point

Recommended:

```python
from supply_chain.cli import main

if __name__ == "__main__":
    main()
```

This preserves the familiar command:

```bash
uv run python generators/generate_supply_chain.py --days 30 --seed 42
```

while moving real implementation into the package.

---

# 6. config.py

## Responsibility

Owns static configuration structures and defaults.

Examples:

```text
route profiles
warehouse profiles
vehicle profile defaults
cargo profiles
priority rules
traffic windows
fuel thresholds
ETA thresholds
batch size defaults
```

It should NOT contain simulation orchestration.

---

## Suggested Responsibilities

```python
load_configuration(...)
validate_configuration(...)
build_default_configuration(...)
```

Configuration may initially be Python-based.

A future YAML/TOML format is possible, but v3 does not require external configuration files if Python configuration remains explicit and testable.

---

# 7. context.py

## Responsibility

Owns authoritative simulation-wide state.

Suggested concept:

```python
SimulationContext
```

Possible fields:

```text
run_id
model_version
seed
simulation_start
simulation_end
current_time
rng
configuration
```

Potential methods:

```python
advance(...)
now(...)
```

All modules should use the same simulation context rather than calling:

```python
datetime.now()
```

independently during simulation.

---

# 8. models.py

## Responsibility

Defines core domain data structures.

Recommended use of:

```python
dataclasses
```

for v3 unless a stronger reason for another modeling library emerges.

Suggested classes:

```text
SimulationRun
WarehouseProfile
WarehouseState
RouteProfile
RouteState
VehicleProfile
VehicleState
CargoProfile
Shipment
OperationalEvent
DelayContribution
```

Keep persistence-specific SQL concerns out of these models.

---

# 9. lifecycle.py

## Responsibility

Authoritative shipment lifecycle implementation.

It owns:

```text
valid states
valid transitions
transition validation
transition side effects
```

Examples:

```python
mark_ready(...)
depart(...)
arrive(...)
deliver(...)
```

This module is the single authority for lifecycle semantics.

No other module should directly mutate lifecycle status arbitrarily.

---

# 10. planning.py

## Responsibility

Owns shipment demand generation and planning.

Responsibilities:

```text
generate shipment demand
choose origin/destination
assign priority
assign cargo
select eligible vehicle
calculate scheduled departure
calculate scheduled arrival
initialize ETA
```

Planning should produce `PLANNED` shipments.

It should not generate final actual arrival outcomes.

---

# 11. routing.py

## Responsibility

Owns route-specific travel behavior.

Responsibilities:

```text
route lookup
directional route profile
traffic state
weather impact
target speed
route progress
remaining distance
route disruption state
```

The route model should expose values needed by:

```text
vehicle movement
ETA
event generation
```

---

# 12. warehouses.py

## Responsibility

Owns warehouse state and dwell behavior.

Responsibilities:

```text
warehouse operating state
queue/load calculations
loading dwell
unloading dwell
congestion transitions
priority effects
warehouse telemetry drivers
```

This module should not directly determine whether a shipment is ultimately late.

It produces operational time/state effects.

---

# 13. vehicles.py

## Responsibility

Owns persistent vehicle state and behavior.

Responsibilities:

```text
availability
location
speed
fuel
odometer
engine state
reliability
condition
refueling
mechanical warnings
turnaround
```

Vehicle state persists across shipments.

---

# 14. cargo.py

## Responsibility

Owns cargo compatibility and cargo environmental state.

Responsibilities:

```text
vehicle compatibility
warehouse compatibility
reefer setpoint
temperature evolution
humidity evolution
door effect
refrigeration fault effect
excursion threshold detection
```

This centralizes behavior currently scattered through vehicle-type/cargo string conditions.

---

# 15. eta.py

## Responsibility

Single authoritative ETA calculation.

Conceptual API:

```python
calculate_eta(
    context,
    shipment,
    route_state,
    vehicle_state,
    warehouse_state,
) -> datetime
```

It owns:

```text
remaining travel estimate
known delays
expected stops
destination dwell expectation
schedule recovery
```

Other modules should not independently calculate competing ETAs.

---

# 16. events.py

## Responsibility

Defines and emits operational events.

Responsibilities:

```text
event construction
event IDs
severity
cause codes
event detail payload
event ordering support
```

Events should be triggered by domain behavior.

Do not generate a random "traffic exception" merely because a shipment was previously labeled late.

---

# 17. telemetry.py

## Responsibility

Converts current domain state into persisted time-series rows.

Primary generators:

```python
iter_fleet_telemetry(...)
iter_warehouse_telemetry(...)
```

These SHOULD yield rows incrementally.

Example:

```python
yield FleetTelemetryRow(...)
```

or tuples suitable for persistence.

This module should not invent independent business state.

It observes the simulation state.

---

# 18. validation.py

## Responsibility

Centralizes domain/data-quality validation.

Validation layers:

```text
configuration validation
per-transition validation
runtime invariant validation
post-generation validation
database validation queries
```

Example functions:

```python
validate_shipment(...)
validate_vehicle_state(...)
validate_event(...)
validate_simulation(...)
```

Critical violations should fail the run.

---

# 19. persistence.py

## Responsibility

Owns PostgreSQL/TimescaleDB interaction.

Responsibilities:

```text
connection handling
master data loading
simulation-run record
batch insertion
shipment persistence
event persistence
telemetry insertion
transaction boundaries
```

No core domain behavior should depend on SQL implementation details.

---

# 20. generator.py

## Responsibility

Orchestrates the complete simulation.

Conceptual flow:

```text
initialize context
load configuration
load master data
create simulation-run record
initialize domain states
plan shipments
advance simulation clock
process domain state
emit events/telemetry
validate
persist bounded batches
finalize run metadata
```

`generator.py` coordinates modules; it should not reimplement their business rules.

---

# 21. cli.py

## Responsibility

Command-line interface only.

Required options:

```text
--days
--seed
```

Recommended options:

```text
--batch-size
--start
--validate-only
```

Possible future options:

```text
--config
--run-id
```

Do not add options without a concrete use case.

---

# 22. Dependency Direction

Recommended dependency flow:

```text
config/models/context
        ↓
domain rule modules
        ↓
generator/orchestration
        ↓
telemetry/events
        ↓
persistence
```

Avoid:

```text
models importing persistence
routing importing CLI
validation mutating database silently
```

---

# 23. Domain Authority Rules

Each major concept should have one authoritative implementation.

| Concept | Authority |
|---|---|
| Lifecycle transition | `lifecycle.py` |
| ETA | `eta.py` |
| Route behavior | `routing.py` |
| Warehouse dwell | `warehouses.py` |
| Vehicle state/fuel | `vehicles.py` |
| Cargo temperature | `cargo.py` |
| Event creation | `events.py` |
| Validation | `validation.py` |
| Database writes | `persistence.py` |

This prevents duplicated logic.

---

# 24. Simulation Loop

A conceptual loop:

```python
while context.current_time < context.simulation_end:
    update_route_states(...)
    update_warehouse_states(...)
    process_shipment_transitions(...)
    update_vehicle_states(...)
    update_cargo_states(...)
    process_disruptions(...)
    recalculate_material_etas(...)
    emit_events(...)
    emit_due_telemetry(...)
    validate_runtime_state(...)
    context.advance(step)
```

The actual implementation may optimize ordering.

The invariant is:

> all emitted data for a timestamp must come from one coherent state.

---

# 25. Event-Driven Versus Fixed-Step Behavior

v3 may use a hybrid approach.

Fixed-step behavior:

```text
vehicle movement
fleet telemetry
warehouse telemetry
```

Event-driven behavior:

```text
departure
arrival
fuel stop
traffic incident
ETA update
temperature excursion
delivery completion
```

A full discrete-event simulation engine is not required for v3.

---

# 26. Bounded-Memory Persistence

The current Supply Chain generator already uses iterator-based telemetry generation and bounded insert batches.

Preserve that pattern.

Recommended abstraction:

```python
insert_rows(
    table=...,
    rows=iterator,
    batch_size=5000,
)
```

The iterator should be consumed incrementally.

---

# 27. Transaction Strategy

Reference/master configuration:

```text
small transactions
```

Shipments/events:

```text
moderate bounded batches
```

Telemetry:

```text
large bounded batches
```

Avoid one transaction for an entire year of telemetry.

Also avoid committing each row.

---

# 28. Simulation Metadata Lifecycle

At run start:

```text
sc_simulation_runs.status = STARTED
```

On successful generation + validation:

```text
COMPLETED
```

On runtime failure:

```text
FAILED
```

On critical validation failure:

```text
VALIDATION_FAILED
```

Metadata should include enough error context for debugging.

---

# 29. Seed Handling

CLI:

```bash
--seed 42
```

Context initializes deterministic random source.

Preferred conceptual structure:

```python
rng = random.Random(seed)
```

If NumPy randomness is used:

```python
np_rng = np.random.default_rng(seed_or_derived_seed)
```

Avoid unseeded module-global randomness.

---

# 30. Random Substreams

Recommended optional pattern:

```text
base seed
   ├── planning RNG
   ├── route RNG
   ├── warehouse RNG
   ├── vehicle RNG
   └── cargo RNG
```

This makes reproducibility more stable when one module changes.

Do not over-engineer this initially; a clear deterministic strategy is sufficient.

---

# 31. Time Handling

All persisted timestamps should remain:

```text
timestamptz
UTC
```

Warehouse timezone remains useful for interpreting local operating hours.

Simulation logic may derive local time from warehouse/route context when applying:

```text
business hours
rush hour
```

but persisted event/telemetry time remains UTC.

---

# 32. Master Data Loading

Persistence layer should load:

```text
warehouses
routes
vehicles
cargo profiles
```

into domain models before simulation.

Do not query PostgreSQL for route/profile data on every telemetry tick.

---

# 33. Master Data Caching

Reference objects should be cached in memory:

```text
warehouse_by_id
route_by_pair
vehicle_by_id
cargo_by_type
```

This is small, bounded state and avoids repeated database calls.

---

# 34. Shipment Planning Strategy

Planning may initially generate the complete list of shipment plans for the simulation window because shipment count is small compared with telemetry volume.

That is acceptable.

High-volume telemetry must remain streaming.

---

# 35. Avoid Premature Generic Frameworks

Supply Chain v3 is the reference implementation, but do not create generic abstractions such as:

```text
BaseGenerator
UniversalEntity
GenericSimulationObject
```

unless they solve a concrete shared problem.

We should extract common infrastructure for Solar/Refinery only after Supply Chain proves the pattern.

---

# 36. Testing Architecture

Recommended test structure:

```text
tests/
└── supply_chain/
    ├── test_lifecycle.py
    ├── test_planning.py
    ├── test_routing.py
    ├── test_warehouses.py
    ├── test_vehicles.py
    ├── test_cargo.py
    ├── test_eta.py
    ├── test_events.py
    ├── test_validation.py
    └── test_integration.py
```

---

# 37. Unit Tests

Unit tests should focus on deterministic small examples.

Examples:

```text
READY → IN_TRANSIT sets actual_departure
IN_TRANSIT cannot have actual_arrival
fuel stop raises fuel and consumes time
traffic factor reduces target speed
critical priority reduces dwell but does not eliminate delay
temperature excursion occurs after threshold crossing
```

---

# 38. Integration Tests

Integration tests should cover:

```text
multi-shipment vehicle continuity
event ordering
ETA evolution
warehouse congestion affecting multiple shipments
route-specific behavior
bounded persistence
database constraints
```

---

# 39. Two-Day Validation Test

The short validation run is not a substitute for unit tests.

It is an end-to-end system test:

```text
schema
configuration
simulation
persistence
TimescaleDB
SQL validation
```

Use a fixed seed chosen to exercise representative scenarios.

---

# 40. Logging

Use structured, concise progress logging.

Examples:

```text
simulation initialized
master data loaded
shipments planned
day N generated
batch N committed
validation passed
run completed
```

Avoid per-row logs.

---

# 41. Error Handling

Domain errors should be explicit.

Examples:

```text
InvalidLifecycleTransition
VehicleUnavailableError
CargoCompatibilityError
RouteConfigurationError
SimulationInvariantError
```

Custom exceptions are useful where they improve diagnostics.

Do not create an excessive exception hierarchy.

---

# 42. SQL Migration Architecture

Schema changes should be versioned separately from Python code.

Recommended:

```text
sql/
└── migrations/
    └── 003_supply_chain_v3.sql
```

Optionally:

```text
sql/
└── seeds/
    └── supply_chain_v3_reference_data.sql
```

---

# 43. Reference Data Versus Generator Code

The following should eventually be persisted or seeded as master/reference data:

```text
routes
cargo profiles
vehicle profiles
warehouse profiles
```

The generator may provide defaults, but database state should be the authoritative reference during execution.

---

# 44. Continuous Aggregate Ownership

Do not create/drop/modify TimescaleDB continuous aggregates inside normal simulation code.

Manage those in:

```text
migration/setup SQL
```

The generator generates facts.

Database analytical objects are managed separately.

---

# 45. Grafana Separation

Generator architecture must not contain Grafana-specific logic.

Grafana consumes:

```text
PostgreSQL tables
TimescaleDB hypertables
continuous aggregates
```

No generator code should know panel titles or dashboard requirements.

---

# 46. Proposed Repository Layout

A broader target:

```text
generators/
├── generate_supply_chain.py
└── supply_chain/
    ├── __init__.py
    ├── cli.py
    ├── config.py
    ├── context.py
    ├── models.py
    ├── lifecycle.py
    ├── planning.py
    ├── routing.py
    ├── warehouses.py
    ├── vehicles.py
    ├── cargo.py
    ├── eta.py
    ├── events.py
    ├── telemetry.py
    ├── validation.py
    ├── persistence.py
    └── generator.py

sql/
├── migrations/
│   └── 003_supply_chain_v3.sql
└── seeds/
    └── supply_chain_v3_reference_data.sql

tests/
└── supply_chain/
    ├── test_lifecycle.py
    ├── test_planning.py
    ├── test_routing.py
    ├── test_warehouses.py
    ├── test_vehicles.py
    ├── test_cargo.py
    ├── test_eta.py
    ├── test_events.py
    ├── test_validation.py
    └── test_integration.py
```

---

# 47. Implementation Sequencing

Recommended code order:

```text
1. migration + reference tables
2. config/models/context
3. lifecycle
4. route model
5. warehouse model
6. vehicle model
7. cargo model
8. planning
9. ETA
10. events
11. telemetry
12. persistence
13. generator orchestration
14. validation
15. CLI compatibility wrapper
16. integration tests
```

Validation tests should be added throughout, not only at step 14.

---

# 48. What We Will Not Do

Do not:

```text
rewrite the entire repo
introduce a microservice architecture
add Kafka for generator internals
add Airflow to run the generator
build a generic simulation framework
move business logic into SQL
use TimescaleDB internal tables directly
couple generator code to Grafana
```

Those are outside the current objective.

---

# 49. Architecture Decision Summary

The v3 implementation should be considered locked around these principles:

```text
1. Modular package replaces monolithic implementation.

2. generate_supply_chain.py remains a compatibility entry point.

3. SimulationContext owns time and deterministic randomness.

4. Domain models are separate from persistence.

5. Each major rule has one authoritative module.

6. Shipment outcomes emerge from simulation state.

7. Telemetry observes state; it does not invent independent outcomes.

8. Events reflect domain behavior.

9. ETA has one authoritative implementation.

10. Database writes remain bounded-batch.

11. High-volume telemetry remains iterator/stream based.

12. Master data is loaded once and cached.

13. SQL migrations own schema/TimescaleDB objects.

14. Tests target domain modules directly.

15. Supply Chain proves the pattern before extracting shared infrastructure for Solar/Refinery.
```

---

# 50. Requirement Traceability

Examples:

```text
SC-AR-001
    → config.py

SC-AR-002
    → modular package structure

SC-AR-003
    → context/persistence/validation patterns

SC-AR-004
    → telemetry iterators + bounded persistence

SC-AR-005
    → persistence.py separated from domain rules

SC-NFR-001 / 002
    → deterministic SimulationContext

SC-NFR-006
    → unit-testable modules
```

---

# 51. Next Artifact

The next document is:

```text
docs/model-v3/supply-chain/acceptance-tests.md
```

That document will turn the requirements and architecture into explicit QA criteria and validation scenarios before implementation begins.

It will define:

```text
unit acceptance
domain invariants
database assertions
2-day validation
365-day validation
analytics validation
failure criteria
```
