# Supply Chain v3 — Requirements

## 1. Purpose

This document converts the findings from the Supply Chain v2 analytical review into explicit requirements for Supply Chain Generator v3.

Supply Chain v3 is the reference implementation for the project's Model v3 generator standard.

The objective is not to build a complete logistics digital twin. The objective is to produce a synthetic logistics environment whose telemetry, events, shipment states, and business outcomes are realistic enough to support meaningful SQL, TimescaleDB, Grafana, QA, and data-engineering work.

Requirements use the following identifiers:

- `SC-FR` — functional requirement
- `SC-DR` — domain/realism requirement
- `SC-DQ` — data-quality requirement
- `SC-AR` — architecture requirement
- `SC-NFR` — non-functional requirement

---

# 2. Shipment Lifecycle Requirements

## SC-FR-001 — Explicit Shipment Lifecycle

The generator SHALL model shipments using an explicit lifecycle rather than assigning only a final outcome.

At minimum, the lifecycle SHALL distinguish:

```text
PLANNED
READY
IN_TRANSIT
DELIVERED
```

The final state names and allowed transitions will be defined in `shipment-lifecycle.md`.

**Acceptance:** Every generated shipment has a valid lifecycle state and cannot transition through an invalid state sequence.

---

## SC-FR-002 — Separate Lifecycle From Delivery Performance

The generator SHALL distinguish shipment lifecycle state from service-performance state.

A shipment may therefore be:

```text
IN_TRANSIT + ON_TIME
IN_TRANSIT + AT_RISK
IN_TRANSIT + LATE
DELIVERED  + ON_TIME
DELIVERED  + LATE
```

The implementation MAY derive performance state rather than persist it if derivation is unambiguous.

**Acceptance:** `DELAYED` is not required to serve simultaneously as both lifecycle and delivery-performance state.

---

## SC-FR-003 — Correct Actual Arrival Semantics

`actual_arrival` SHALL represent an observed completed arrival.

For any shipment that has not arrived:

```text
actual_arrival IS NULL
```

**Acceptance:** No `PLANNED`, `READY`, or `IN_TRANSIT` shipment has a populated `actual_arrival`.

---

## SC-FR-004 — Estimated Arrival / ETA

Active shipments SHALL support an estimated arrival timestamp distinct from scheduled and actual arrival.

The model SHALL distinguish:

```text
scheduled_arrival
estimated_arrival
actual_arrival
```

**Acceptance:** An active shipment can experience ETA changes without modifying its original scheduled arrival.

---

## SC-FR-005 — Preserve Scheduled Commitments

Once a shipment begins execution, the original scheduled arrival SHALL remain available as the baseline service commitment.

Operational disruptions SHALL update ETA rather than rewriting the original schedule.

**Acceptance:** Late-delivery calculations remain possible using the original scheduled arrival.

---

# 3. Delay and Arrival Requirements

## SC-DR-001 — Continuous Arrival Variance

The generator SHALL support realistic arrival variance rather than dividing shipments into exact-on-time versus 1–4-hour-late populations.

The generated population SHOULD include:

- early arrivals where operationally plausible,
- near-on-time arrivals,
- minor delays,
- moderate delays,
- major delays,
- rare severe delays.

**Acceptance:** The minimum positive delay is not artificially constrained to approximately one hour.

---

## SC-DR-002 — Causal Delay Generation

Material delays SHALL originate from one or more modeled operational causes.

Potential causes include:

```text
warehouse dwell
traffic
weather
fuel stop
mechanical condition
route characteristics
priority handling
```

Randomness MAY influence occurrence and magnitude but SHALL operate through modeled causes.

**Acceptance:** A materially delayed shipment can be traced to one or more contributing modeled conditions/events.

---

## SC-DR-003 — Cumulative Delay

Multiple small operational effects MAY accumulate into a larger shipment delay.

Example:

```text
departure dwell      +18 min
traffic              +22 min
fuel stop            +14 min
schedule recovery     -8 min
                     -------
net ETA impact        +46 min
```

**Acceptance:** Final lateness need not be generated from one single delay draw.

---

## SC-DR-004 — Schedule Recovery

The model SHALL permit a shipment to recover some previously accumulated delay when operational conditions permit.

Recovery SHALL remain physically plausible and SHALL NOT require unsafe or impossible vehicle speeds.

**Acceptance:** ETA can improve during a trip without violating speed constraints.

---

# 4. Route Requirements

## SC-DR-005 — Directional Route Profiles

Each directional route SHALL have an explicit route profile.

`A → B` and `B → A` SHALL be independently configurable.

A route profile SHOULD support:

- distance,
- nominal travel time,
- normal speed characteristics,
- congestion sensitivity,
- time-of-day effects,
- weather sensitivity,
- route-specific disruption risk.

**Acceptance:** Persistent route differences can be explained by configuration rather than unexplained random variation.

---

## SC-DR-006 — Route Distance Consistency

Vehicle movement, odometer change, and trip completion SHALL remain consistent with route distance within defined tolerances.

**Acceptance:** A completed trip cannot require materially less or more travel distance than its configured route without an explicit modeled explanation.

---

## SC-DR-007 — Time-of-Day Effects

Routes SHALL support time-of-day operating differences where configured.

Examples MAY include:

- morning congestion,
- evening congestion,
- overnight free-flow conditions.

**Acceptance:** A configured congestion period can influence speed and ETA.

---

# 5. Warehouse Requirements

## SC-DR-008 — Warehouse Operating Profiles

Warehouses SHALL have explicit persistent characteristics rather than behaving identically.

Profiles SHOULD support:

- normal throughput,
- loading efficiency,
- unloading efficiency,
- congestion sensitivity,
- operating hours,
- cold-storage capability where applicable.

**Acceptance:** Warehouse-specific behavior can produce persistent analytical differences.

---

## SC-DR-009 — Warehouse Dwell

Shipment departure and completion timing SHALL support warehouse dwell.

Dwell MAY depend on:

- warehouse state,
- priority,
- congestion,
- cargo type,
- random operational variation.

**Acceptance:** Shipment timing can be affected before vehicle travel begins or after arrival.

---

## SC-DR-010 — Dynamic Warehouse State

Warehouse operating state SHOULD vary over time rather than remaining a fixed random distribution.

Examples:

```text
NORMAL
BUSY
CONGESTED
```

**Acceptance:** Temporary warehouse congestion can affect multiple shipments during the same period.

---

# 6. Vehicle Requirements

## SC-DR-011 — Persistent Vehicle Profiles

Each vehicle SHALL have persistent operating characteristics.

Profiles SHOULD support:

- vehicle type,
- cargo capability,
- fuel efficiency,
- reliability,
- condition,
- performance characteristics,
- degradation or failure susceptibility.

**Acceptance:** Vehicle-specific differences remain stable enough to be observable over long analytical windows.

---

## SC-DR-012 — Vehicle Availability

A vehicle SHALL NOT be assigned to overlapping active shipments.

Vehicle availability SHALL influence shipment assignment.

**Acceptance:** No vehicle has two simultaneous active trips.

---

## SC-DR-013 — Route Continuity

Unless explicitly repositioned, the origin of a vehicle's next shipment SHALL equal the destination of its previous completed shipment.

**Acceptance:** Vehicle location does not teleport between ordinary shipments.

---

## SC-DR-014 — Plausible Speed

Generated speed SHALL remain within configured operational limits.

Disruptions SHALL affect speed through the vehicle/trip state.

**Acceptance:** Schedule recovery does not require implausible speeds.

---

# 7. Fuel Requirements

## SC-DR-015 — Stateful Fuel Consumption

Fuel SHALL persist as vehicle state and decline consistently with vehicle operation.

Consumption SHOULD depend on relevant factors such as:

- distance,
- vehicle characteristics,
- operating conditions.

**Acceptance:** Fuel does not independently redraw at each telemetry sample.

---

## SC-DR-016 — Explicit Refueling

Fuel SHALL NOT silently jump from a low value to a high value.

Refueling SHALL be represented as an operational action/event.

**Acceptance:** A material fuel increase has a corresponding refueling state/event.

---

## SC-DR-017 — Refueling ETA Impact

When refueling occurs during an active trip, its time cost SHALL be reflected in trip progression and ETA where material.

---

# 8. Priority / Service-Level Requirements

## SC-DR-018 — Operational Priority Effects

Shipment priority SHALL influence modeled behavior.

The model SHALL support:

```text
STANDARD
EXPEDITED
CRITICAL
```

Priority MAY affect:

- warehouse queue position,
- allowed dwell,
- dispatch urgency,
- recovery behavior,
- service target,
- exception handling.

**Acceptance:** Priority categories have explainable operational differences.

---

## SC-DR-019 — No Guaranteed Priority Outcome

High priority SHALL improve service handling but SHALL NOT guarantee on-time delivery.

A CRITICAL shipment can still be late when operational conditions warrant it.

---

# 9. Event Requirements

## SC-FR-006 — Causal Event Model

Events SHALL represent meaningful state transitions or operational occurrences.

Where an event causes an operational effect, the state/telemetry change SHALL follow from the event.

---

## SC-FR-007 — Core Event Vocabulary

The v3 model SHALL support an event vocabulary sufficient to explain shipment execution.

Expected event concepts include:

```text
PICKUP
DEPARTURE
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

The final vocabulary will be defined in `domain-model.md`.

---

## SC-FR-008 — Event Temporal Integrity

Event timestamps SHALL be consistent with shipment lifecycle and trip state.

Examples:

- `DELIVERY` cannot precede `ARRIVAL`,
- `DEPARTURE` cannot occur after `DELIVERY`,
- a trip disruption must occur during a relevant trip interval.

---

# 10. Cargo / Reefer Requirements

## SC-DR-020 — Cargo Compatibility

Cargo assignment SHALL remain compatible with vehicle capability.

Reefer-dependent cargo SHALL NOT be assigned to a vehicle incapable of refrigeration.

---

## SC-DR-021 — Stateful Cargo Temperature

Reefer cargo temperature SHALL evolve as state rather than independent random samples.

Temperature SHOULD respond to:

- setpoint,
- ambient conditions,
- refrigeration performance,
- door state,
- equipment fault state.

---

## SC-DR-022 — Causal Temperature Excursions

A temperature-excursion event SHALL correspond to an actual threshold violation in cargo telemetry.

**Acceptance:** An excursion event can be confirmed from the associated telemetry.

---

## SC-DR-023 — Temperature Recovery

When the causal condition is removed, cargo temperature SHOULD recover gradually toward its configured operating range.

---

# 11. Telemetry Requirements

## SC-FR-009 — Telemetry Reflects Simulation State

Fleet telemetry SHALL be generated from current simulation state.

At minimum, telemetry SHALL remain consistent with:

- active shipment,
- route progress,
- vehicle movement,
- fuel,
- cargo condition,
- trip disruptions.

---

## SC-FR-010 — Shipment/Telemetry Association

When a vehicle is actively executing a shipment, telemetry SHALL reference the correct shipment.

When no shipment is active, shipment association SHALL be NULL or otherwise explicitly absent.

---

## SC-FR-011 — Location Progression

Latitude and longitude SHALL progress consistently along the active route.

Material backward jumps or teleportation SHALL NOT occur without an explicit modeled cause.

---

# 12. Workload Requirements

## SC-DR-024 — Non-Uniform Workload

Shipment demand SHALL not be artificially balanced across all vehicles and routes.

Variation SHOULD arise from:

- route demand,
- warehouse activity,
- vehicle capability,
- availability,
- priority mix.

---

## SC-DR-025 — Controlled Distribution

Non-uniform workload SHALL remain controlled enough that all configured entities can participate in the simulation unless intentionally configured otherwise.

---

# 13. Reproducibility Requirements

## SC-NFR-001 — Seeded Randomness

The generator SHALL accept:

```bash
--seed <integer>
```

All stochastic behavior under generator control SHALL derive from deterministic seeded random state.

---

## SC-NFR-002 — Repeatable Simulation

Given identical:

- generator version,
- configuration,
- seed,
- simulation start/end,

the generator SHALL reproduce equivalent domain behavior.

Database-generated identifiers MAY differ if the persistence strategy makes exact identifiers impractical, but business behavior SHALL remain reproducible.

---

# 14. Simulation Metadata Requirements

## SC-FR-012 — Generation Metadata

Each generation run SHALL record:

```text
model_version
generator_name
seed
simulation_start
simulation_end
generated_at
```

The schema/storage design will be defined in `schema-changes.md`.

---

# 15. Architecture Requirements

## SC-AR-001 — Separate Configuration From Simulation Logic

Route, warehouse, vehicle, cargo, and probability parameters SHALL NOT be scattered throughout orchestration code.

They SHALL be represented through explicit configuration/domain structures.

---

## SC-AR-002 — Separate Domain Responsibilities

The v3 implementation SHALL separate major responsibilities such as:

```text
configuration
domain models/state
shipment lifecycle
routing
warehouse behavior
vehicle behavior
events
telemetry
validation
persistence
orchestration
```

The final module layout will be defined in `architecture.md`.

---

## SC-AR-003 — Shared v3 Infrastructure Compatibility

Supply Chain SHALL establish reusable patterns for:

- seed handling,
- simulation metadata,
- batching,
- validation,
- configuration,
- logging.

Solar and Refinery MAY reuse these patterns without inheriting Supply Chain-specific domain logic.

---

## SC-AR-004 — Preserve Bounded-Memory Generation

High-volume telemetry SHALL continue to use streaming/iterator or equivalent bounded-memory generation.

A full historical telemetry dataset SHALL NOT be accumulated in memory before persistence.

---

## SC-AR-005 — Persistence Is Not Domain Logic

Database insertion SHALL be separated from core business/simulation rules sufficiently that domain behavior can be unit tested without requiring a database write for every test.

---

# 16. Data Quality Requirements

## SC-DQ-001 — Temporal Integrity

The following SHALL hold:

```text
scheduled_arrival > scheduled_departure
actual_arrival > actual_departure        when actual_arrival exists
```

Additional lifecycle-specific timing rules will be defined later.

---

## SC-DQ-002 — No Premature Actual Arrival

For all unfinished shipments:

```sql
actual_arrival IS NULL
```

---

## SC-DQ-003 — Vehicle Shipment Exclusivity

A vehicle SHALL have at most one active shipment at any instant.

---

## SC-DQ-004 — Valid Numeric Ranges

At minimum:

```text
0 <= fuel_level_pct <= 100
speed_kmh >= 0
cargo_humidity_pct within configured physical range
```

Additional ranges will be defined by the domain model.

---

## SC-DQ-005 — Event/Telemetry Consistency

Events that assert measurable conditions SHALL be supported by corresponding simulation state or telemetry.

Examples:

- temperature excursion,
- fuel stop,
- traffic slowdown,
- arrival,
- delivery.

---

## SC-DQ-006 — Route/Location Consistency

Vehicle location and route progress SHALL remain consistent with the assigned route within configured tolerance.

---

## SC-DQ-007 — Delivery Completion Consistency

A delivered shipment SHALL have:

- an actual arrival,
- a valid arrival/delivery sequence,
- a final vehicle location consistent with the destination.

---

# 17. Performance Requirements

## SC-NFR-003 — Historical Generation Capability

The generator SHALL remain capable of generating at least a 365-day dataset on the project's existing development environment without requiring the entire generated telemetry dataset in memory.

---

## SC-NFR-004 — Batch Persistence

Database writes SHALL use configurable bounded batches suitable for high-volume telemetry.

---

## SC-NFR-005 — Progress Visibility

Long generation runs SHALL report useful progress without logging every generated row.

---

# 18. Testing Requirements

## SC-NFR-006 — Unit-Testable Domain Rules

Core domain rules SHALL be testable independently of full-year generation.

---

## SC-NFR-007 — Short Validation Run

Before any full 365-day generation, the implementation SHALL pass a short validation run, initially targeted at two simulated days.

---

## SC-NFR-008 — Automated Acceptance Checks

The project SHALL provide automated checks covering the critical `SC-DQ` requirements and key lifecycle invariants.

A generation run that violates critical invariants SHALL be considered failed even if database insertion succeeds.

---

# 19. Analytics Acceptance Requirements

## SC-NFR-009 — Explainable Analytical Differences

Long-window analytics SHOULD reveal persistent differences where configuration intentionally creates them.

Examples:

- route performance,
- warehouse dwell,
- vehicle reliability,
- priority handling.

These differences SHALL be explainable from model configuration and events.

---

## SC-NFR-010 — Avoid Artificial Uniformity

The generator SHOULD NOT force key operational KPIs toward nearly identical values for every vehicle, route, or warehouse unless the configuration genuinely describes identical entities.

---

## SC-NFR-011 — Avoid Artificial Extremes

The generator SHALL also avoid creating dramatic differences solely to make dashboards visually interesting.

Analytical variation must arise from plausible model behavior.

---

# 20. Explicit v3 Non-Requirements

The following are NOT required for Supply Chain v3:

- real road-network routing,
- live traffic APIs,
- historical weather APIs,
- individual driver entities,
- Hours-of-Service compliance,
- complete maintenance work-order management,
- customer/order/inventory systems,
- route optimization,
- dispatch optimization,
- detailed logistics cost accounting,
- ML-based ETA prediction,
- interactive real-time digital-twin control.

These remain candidates for v4.

---

# 21. Definition of Done for Supply Chain v3

Supply Chain v3 is complete when:

1. the shipment lifecycle and domain model are documented,
2. required schema changes are implemented,
3. the generator follows the agreed modular architecture,
4. stochastic behavior is reproducible by seed,
5. telemetry generation remains bounded-memory,
6. shipment timing emerges from modeled operational state,
7. ETA and actual-arrival semantics are correct,
8. events and telemetry are causally consistent,
9. critical data-quality invariants are automatically validated,
10. a two-day validation run passes,
11. a 365-day generation completes successfully,
12. continuous aggregates are refreshed/rebuilt as required,
13. representative SQL analyses produce plausible results,
14. Grafana panels are validated against the v3 dataset,
15. the v3 documentation reflects the implemented behavior.

---

# 22. Requirements Traceability

The next design artifacts SHALL reference these requirement IDs where appropriate.

For example:

```text
SC-FR-001
    ↓
shipment-lifecycle.md
    ↓
architecture.md
    ↓
acceptance-tests.md
```

This provides a traceable path from:

```text
finding
  ↓
requirement
  ↓
design
  ↓
implementation
  ↓
test
```

---

## Next Artifact

The next document is:

```text
docs/model-v3/supply-chain/shipment-lifecycle.md
```

That document will define the shipment state machine, valid transitions, timing semantics, ETA behavior, and the distinction between lifecycle state and delivery-performance state.
