# Supply Chain v3 — Findings

## Purpose

This document records the weaknesses and modeling limitations discovered in the current Supply Chain generator through SQL analysis, TimescaleDB aggregation, and Grafana visualization.

These findings are evidence for the v3 requirements. They are not yet the implementation specification.

---

## 1. Current Model Strengths

The current generator is a useful v2 baseline. It already provides:

- coherent shipment schedules per vehicle,
- origin-to-destination continuity between successive shipments,
- route-distance-based scheduled travel,
- vehicle-specific telemetry linked to active shipments,
- 10-second fleet telemetry,
- warehouse environmental telemetry,
- cargo selection based on vehicle type,
- reefer cargo telemetry,
- shipment events,
- bounded-memory streaming for high-volume telemetry,
- batched database persistence.

These capabilities should be preserved unless a v3 requirement explicitly replaces them.

---

## 2. Shipment Delay Model Is Too Simple

Current shipment generation effectively makes a binary decision:

```text
90% probability → not delayed
10% probability → delayed
```

A delayed shipment then receives approximately a 1–4 hour delay.

This creates an artificial separation between on-time and delayed shipments rather than a realistic arrival-time distribution.

### Analytical evidence

Full-year delay-severity analysis returned:

```text
Late shipments:       242
Average delay:        154.0 minutes
Minimum delay:         60.3 minutes
Maximum delay:        239.7 minutes
```

The approximately one-hour minimum is particularly revealing: minor delays are essentially absent.

### Consequence

The model cannot realistically represent:

- 5-minute lateness,
- 20-minute traffic delays,
- modest warehouse departure delays,
- schedule recovery,
- cumulative small delays,
- multiple contributing delay causes.

### v3 implication

Arrival variance should emerge from operational causes rather than a binary random delayed/not-delayed decision.

---

## 3. Arrival Semantics Need Correction

The current model calculates `actual_arrival` before determining whether the shipment has actually completed.

That means an `IN_TRANSIT` shipment can possess a future `actual_arrival`.

### Why this is problematic

`actual_arrival` should represent an observed fact:

> The shipment actually arrived at this timestamp.

For an active shipment, that fact does not yet exist.

### v3 implication

Separate:

```text
scheduled_arrival
estimated_arrival / ETA
actual_arrival
```

Expected semantics:

```text
IN_TRANSIT:
    estimated_arrival = populated
    actual_arrival = NULL

DELIVERED:
    estimated_arrival = final/latest estimate
    actual_arrival = observed arrival
```

---

## 4. Shipment Status Is Too Outcome-Oriented

The current statuses are primarily:

```text
IN_TRANSIT
DELIVERED
DELAYED
```

`DELAYED` mixes two concepts:

- lifecycle state,
- performance outcome.

A shipment can be in transit and delayed simultaneously.

Likewise, a delivered shipment can have arrived late.

### v3 implication

Lifecycle and service-performance concepts should be separated.

For example:

```text
Lifecycle:
PLANNED
READY
IN_TRANSIT
DELIVERED

Performance:
ON_TIME
AT_RISK
LATE
```

The final terminology will be defined in `shipment-lifecycle.md`.

---

## 5. Priority Has Little Operational Meaning

The generator assigns:

```text
STANDARD
EXPEDITED
CRITICAL
```

with an approximately:

```text
75% / 20% / 5%
```

distribution.

However, priority currently has little or no causal influence on:

- dispatch,
- warehouse dwell,
- route behavior,
- delay probability,
- recovery behavior,
- service target,
- ETA management.

### Analytical evidence

Full-year on-time performance was:

```text
CRITICAL      130 completed   120 on time   92.3%
EXPEDITED     464 completed   419 on time   90.3%
STANDARD     1884 completed  1697 on time   90.1%
```

The small differences are not clearly explained by model behavior.

### v3 implication

Priority should have explicit operational consequences while avoiding unrealistic guarantees.

---

## 6. Vehicle Behavior Is Too Homogeneous

Vehicle-level 30-day delivery analysis produced:

```text
Vehicle 5   303 completed   34 late   11.2%
Vehicle 3   306 completed   34 late   11.1%
Vehicle 2   307 completed   32 late   10.4%
Vehicle 6   310 completed   30 late    9.7%
Vehicle 4   306 completed   29 late    9.5%
Vehicle 8   308 completed   28 late    9.1%
Vehicle 1   313 completed   28 late    8.9%
Vehicle 7   318 completed   26 late    8.2%
```

Shipment volume and late-delivery rates are both tightly distributed.

### Interpretation

The current generator does not provide strong persistent vehicle characteristics capable of producing meaningful operational differences.

### v3 implication

Vehicles should have stable characteristics such as:

- reliability,
- age/condition,
- fuel efficiency,
- acceleration/performance characteristics,
- maintenance condition,
- cargo capability,
- breakdown or degradation risk.

These characteristics should influence behavior without making individual vehicles unrealistically deterministic.

---

## 7. Route Behavior Is Too Homogeneous

The 30-day route analysis initially appeared to show large differences:

```text
Phoenix → Houston       25.0% late
Phoenix → El Paso       20.8%
El Paso → Los Angeles   18.8%
...
several routes            0.0%
```

But the samples were small.

The full-year results converged substantially:

```text
Phoenix → Houston        12.2%
El Paso → Phoenix        11.8%
Houston → Los Angeles    11.5%
Houston → Phoenix        10.8%
Los Angeles → Houston    10.1%
Phoenix → El Paso        10.0%
Phoenix → Los Angeles     9.9%
Houston → El Paso         9.3%
Los Angeles → Phoenix     9.2%
El Paso → Houston         7.9%
El Paso → Los Angeles     7.5%
Los Angeles → El Paso     6.9%
```

### Interpretation

Much of the apparent short-term route variation is statistical noise rather than persistent route behavior.

### v3 implication

Directional routes should possess explicit characteristics such as:

- distance,
- normal travel-time distribution,
- congestion sensitivity,
- time-of-day effects,
- weather sensitivity,
- border/checkpoint effects where applicable,
- recovery opportunity.

`A → B` may legitimately differ from `B → A`.

---

## 8. Warehouse Behavior Is Too Uniform

Warehouse environmental telemetry currently models zone type and business-hours occupancy, but shipment operations are not strongly affected by warehouse state.

Warehouse behavior should be capable of influencing:

- loading delay,
- unloading delay,
- queueing,
- departure readiness,
- congestion,
- cold-storage handling,
- energy use,
- shipment risk.

### v3 implication

Warehouses should have persistent operating characteristics and dynamic state.

---

## 9. Events Document Outcomes More Than They Cause Them

Current events include concepts such as:

```text
PICKUP
SCAN
EXCEPTION
DELIVERY
TEMP_EXCURSION
```

However, many events are generated after shipment timing has already been determined.

For example, a traffic exception can explain an already-generated delay rather than causing vehicle speed, ETA, and arrival time to change.

### v3 implication

The causal direction should become:

```text
event/cause
    ↓
simulation state changes
    ↓
telemetry changes
    ↓
ETA changes
    ↓
shipment outcome
```

Examples:

```text
TRAFFIC_DELAY
WEATHER_DELAY
WAREHOUSE_CONGESTION
FUEL_STOP
MECHANICAL_WARNING
TEMP_EXCURSION
ETA_UPDATED
ARRIVAL
DELIVERY
```

---

## 10. Telemetry and Shipment Outcomes Need Stronger Causal Coupling

Fleet telemetry currently follows the generated shipment timeline, which is a useful baseline.

But because shipment arrival is determined before detailed telemetry generation, telemetry does not fully determine the business outcome.

### v3 implication

At minimum, v3 must ensure:

- vehicle movement is consistent with trip state,
- disruptions affect movement,
- movement affects ETA,
- ETA evolves during the trip,
- actual arrival follows simulated trip completion,
- generated events and telemetry agree.

---

## 11. Fuel Behavior Is Simplified

Fuel decreases during travel and is automatically reset to a high level once it falls below a threshold.

This creates a discontinuity without a corresponding operational event.

### v3 implication

Refueling should become an explicit state/event:

```text
low fuel
   ↓
fuel stop
   ↓
vehicle stationary / reduced trip progress
   ↓
fuel increases
   ↓
ETA impact
```

The level of detail should remain appropriate for v3; full fuel-network modeling is not required.

---

## 12. Cargo Temperature Excursions Are Not Fully Coupled

Temperature excursions can be emitted as events, but the event is not necessarily reflected in the actual cargo-temperature telemetry.

### v3 implication

If a temperature excursion occurs:

```text
refrigeration/environmental cause
    ↓
cargo temperature changes
    ↓
threshold crossed
    ↓
exception event
    ↓
recovery or continuing excursion
```

Telemetry and event history must tell the same story.

---

## 13. Workload Distribution Is Very Balanced

Analysis showed shipment volume distributed fairly evenly across vehicles and routes.

Balanced data is convenient for demonstration, but excessive balance removes realistic operational structure.

### v3 implication

Workload should vary according to:

- route demand,
- warehouse throughput,
- vehicle capability,
- priority,
- availability,
- operational conditions.

The model does not need a full demand-planning system in v3, but workload should not look artificially uniform.

---

## 14. Reproducibility Is Missing

The generator uses randomness extensively without an explicit simulation seed.

### Consequence

A defect or interesting analytical pattern cannot be recreated reliably.

### v3 implication

Support:

```bash
--seed <integer>
```

The seed must be captured in simulation metadata.

---

## 15. Configuration Is Embedded in Generator Code

Warehouse coordinates, route distances, probability values, operating thresholds, and other parameters are embedded directly in the Python module.

### Consequence

Business configuration and simulation behavior are difficult to distinguish and test independently.

### v3 implication

Separate:

```text
configuration
domain state
business rules
simulation orchestration
persistence
validation
```

---

## 16. Validation Must Become Explicit

The current model can produce technically valid database rows that still violate business semantics.

### Required v3 validation categories

#### Relational integrity

- valid vehicle references,
- valid warehouse references,
- valid shipment/event references.

#### Temporal integrity

- scheduled arrival after scheduled departure,
- actual departure after or near planned readiness,
- actual arrival after actual departure,
- no actual arrival for an unfinished shipment.

#### Vehicle integrity

- no overlapping active shipments,
- route continuity,
- plausible speed,
- valid fuel range,
- plausible odometer progression.

#### Event integrity

- delivery event only for completed shipment,
- event timestamps within valid shipment context,
- disruption events reflected in state/telemetry.

#### Cargo integrity

- cargo compatible with vehicle type,
- reefer telemetry present when required,
- excursion events correspond to actual threshold violations.

---

## 17. Current Strength Worth Preserving: Streaming Persistence

The current Supply Chain implementation already generates high-volume telemetry through iterators and writes rows in bounded batches.

This is the correct direction for v3 and should become a project-wide generator standard.

---

## 18. Dashboard/Analytics Lesson

The v2 model successfully supported learning and exposed its own weaknesses.

Important analytical lessons included:

- percentages must be interpreted with their denominators,
- short time windows can create misleading apparent patterns,
- not every query deserves a Grafana panel,
- long-term baselines help distinguish signal from noise,
- realistic-looking telemetry is not sufficient if business outcomes lack causal explanation.

This validation workflow should become part of future generator development:

```text
generate
   ↓
validate
   ↓
query
   ↓
visualize
   ↓
ask business questions
   ↓
identify unrealistic behavior
   ↓
refine model
```

---

## Findings Summary

The current Supply Chain generator is not a failed model. It is a successful v2 learning model whose limitations became visible through analytics.

The central v3 problem can be summarized as:

> The current generator creates plausible individual records, but too many business outcomes are determined independently rather than emerging from persistent operational state and causal events.

Supply Chain v3 therefore needs to move from:

```text
random values + predetermined outcomes
```

toward:

```text
configuration
    ↓
persistent domain state
    ↓
causal operational events
    ↓
telemetry
    ↓
evolving ETA
    ↓
business outcome
    ↓
validation
```

---

## Next Artifact

The next document is:

```text
docs/model-v3/supply-chain/requirements.md
```

It will convert these findings into explicit, testable v3 requirements while maintaining the agreed v3/v4 scope boundary.
