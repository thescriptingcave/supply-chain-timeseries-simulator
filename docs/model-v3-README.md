# Model v3

## Purpose

Model v3 establishes a common design standard for the project's synthetic IoT data generators while preserving the domain-specific behavior of each generator.

The primary objective is to produce synthetic data that is:

- realistic enough to support meaningful operational analytics,
- causally consistent across related measurements and events,
- reproducible for QA and debugging,
- generated with bounded memory,
- modular enough to evolve without repeatedly rewriting entire generators,
- and validated with explicit domain and data-quality rules.

Supply Chain will be the reference implementation for the Model v3 architecture. Solar and Refinery will adopt the common v3 standards selectively based on their own domain requirements.

## Current Generators

### Supply Chain

**Classification:** Full v3 redesign / reference implementation

The current Supply Chain generator models vehicle routing between warehouses, shipment scheduling, fleet telemetry, reefer cargo conditions, warehouse environmental telemetry, and delivery events/exceptions.

Dashboard analysis exposed several realism limitations:

- shipment delays are modeled too simply,
- delivered shipments frequently arrive exactly at scheduled arrival,
- in-transit shipments can already have an `actual_arrival`,
- route, warehouse, vehicle, and priority effects are too homogeneous,
- many operational outcomes are generated independently rather than causally,
- event history does not yet fully explain telemetry and shipment outcomes.

Supply Chain v3 will become the reference design for stateful, causal, validated generation.

### Solar

**Classification:** Targeted v3 upgrade

The Solar generator already contains a substantial physical model, including solar position, clear-sky irradiance, panel temperature effects, inverter efficiency, clipping, shading, soiling, and inverter fault/degraded states.

The main v3 improvements will focus on:

- bounded-memory streaming,
- reproducible generation,
- persistent weather behavior,
- stateful soiling and cleaning,
- persistent equipment fault states,
- explicit configuration,
- common validation infrastructure.

Solar does not require the same degree of redesign as Supply Chain.

### Refinery

**Classification:** Targeted-to-moderate v3 upgrade

The Refinery generator currently models process-unit baselines, disturbances, maintenance windows, vibration degradation, equipment alarms, and safety detector events.

The main v3 improvements will focus on:

- bounded-memory streaming,
- reproducibility,
- causal coupling between process state, equipment condition, maintenance, and safety events,
- stateful maintenance and repair effects,
- shift-aware operator behavior,
- explicit configuration,
- domain validation.

## Model v3 Design Principles

### 1. Causality Before Randomness

Randomness may add variation, but it must not be the primary explanation for business or physical outcomes.

Prefer:

```text
cause
  ↓
state change
  ↓
event
  ↓
telemetry effect
  ↓
business outcome
```

over independently generated random values.

### 2. Stateful Simulation

Important conditions should persist across time.

Examples include vehicle location and fuel, shipment lifecycle state, warehouse congestion, weather systems, solar soiling, inverter fault state, refinery equipment degradation, and maintenance state.

### 3. Reproducibility

Every generator should support a random seed.

Example:

```bash
uv run python generators/generate_supply_chain.py --days 30 --seed 42
```

Given the same model version, seed, configuration, and simulation period, the generator should produce the same synthetic behavior.

### 4. Bounded-Memory Generation

High-volume telemetry must be streamed or generated in bounded batches.

Generators should not build an entire multi-month or multi-year telemetry dataset in Python memory before database insertion.

### 5. Configuration Separate From Behavior

Domain parameters should be defined explicitly rather than buried throughout generator functions.

Examples include route characteristics, warehouse behavior, vehicle characteristics, solar site/inverter characteristics, refinery process baselines, and equipment reliability parameters.

### 6. Domain-Specific Models, Shared Infrastructure

Shared infrastructure should include:

- simulation clock,
- deterministic random seed,
- persistence/batching,
- metadata,
- validation,
- configuration loading,
- common logging.

Domain behavior remains domain-specific.

### 7. Validation Is Part of the Generator

A generation run is not considered successful merely because rows were inserted.

#### Supply Chain examples

- no overlapping active shipments for the same vehicle,
- next shipment origin equals previous shipment destination,
- `actual_arrival` is NULL while a shipment is in transit,
- delivered shipments have a delivery event,
- shipment telemetry references the active shipment,
- fuel remains within valid bounds,
- telemetry location progresses consistently with route state.

#### Solar examples

- nighttime irradiance and AC power are zero or near zero,
- AC power does not exceed inverter capacity,
- inverter faults persist for realistic durations,
- soiling changes gradually unless a cleaning event occurs,
- irradiance and solar production remain positively correlated.

#### Refinery examples

- process values remain within physical bounds,
- shutdown state affects dependent process measurements,
- maintenance affects equipment state,
- degradation trends change appropriately after maintenance,
- safety alarms correspond to abnormal process or equipment conditions when applicable.

## Common CLI Standard

Where applicable, generators should converge on:

```bash
uv run python <generator> --days 30 --seed 42
```

## Simulation Metadata

Model v3 should record enough metadata to identify how a dataset was produced.

At minimum:

```text
model_version
generator_name
seed
simulation_start
simulation_end
generated_at
```

## Version 3 Implementation Order

### Phase 1 — Supply Chain Reference Implementation

1. requirements
2. shipment lifecycle
3. domain model
4. simulation rules
5. schema changes
6. module architecture
7. QA acceptance criteria
8. implementation
9. short validation run
10. full historical regeneration
11. Grafana validation

### Phase 2 — Solar Review and Upgrade

Apply the common v3 infrastructure where useful, then address Solar-specific state and realism issues.

### Phase 3 — Refinery Review and Upgrade

Apply the common infrastructure, then improve coupling among process state, equipment degradation, maintenance, and safety behavior.

## v3 Scope Boundary

Model v3 is intended to create a trustworthy, explainable synthetic IoT environment.

It includes realistic variation, persistent state, causal consistency, reproducibility, modular architecture, bounded-memory generation, domain validation, and simulation metadata.

## Deferred to v4

The following capabilities are intentionally outside the v3 scope unless a v3 requirement proves they are necessary:

- real road-network routing,
- external historical weather ingestion,
- driver entities and Hours-of-Service simulation,
- maintenance work-order lifecycle,
- route optimization and automated dispatch,
- customer/order/inventory integration,
- dynamic market demand,
- cost and profitability modeling,
- machine-learning ETA prediction,
- multi-facility disruption propagation,
- interactive/live digital-twin control.

Model v4 should represent expansion into a broader enterprise simulation platform rather than incremental generator cleanup.

## Documentation Structure

```text
docs/
└── model-v3/
    ├── README.md
    ├── design-principles.md
    ├── supply-chain/
    │   ├── findings.md
    │   ├── requirements.md
    │   ├── shipment-lifecycle.md
    │   ├── domain-model.md
    │   ├── simulation-rules.md
    │   ├── schema-changes.md
    │   ├── architecture.md
    │   ├── acceptance-tests.md
    │   └── implementation-plan.md
    ├── solar/
    │   ├── findings.md
    │   ├── requirements.md
    │   └── acceptance-tests.md
    └── refinery/
        ├── findings.md
        ├── requirements.md
        └── acceptance-tests.md
```

## Current Status

Model v3 planning is active.

The next document is:

```text
docs/model-v3/supply-chain/findings.md
```

That document will capture the specific weaknesses discovered through SQL, TimescaleDB, and Grafana analysis of the current Supply Chain model before new requirements are written.
