# Supply Chain v3 — Shipment Lifecycle

## 1. Purpose

This document defines the shipment lifecycle for Supply Chain Generator v3.

It implements and expands the shipment-related requirements defined in:

```text
docs/model-v3/supply-chain/requirements.md
```

Primary requirement references:

```text
SC-FR-001
SC-FR-002
SC-FR-003
SC-FR-004
SC-FR-005
SC-DR-001
SC-DR-002
SC-FR-006
SC-FR-008
SC-DQ-001
SC-DQ-002
SC-DQ-007
```

The central design decision is:

> Shipment lifecycle state and shipment delivery-performance state are separate concepts.

This prevents a status such as `DELAYED` from ambiguously representing both "where the shipment is in its lifecycle" and "how well it is performing against its commitment."

---

# 2. Lifecycle Model

## 2.1 Lifecycle States

Supply Chain v3 SHALL use the following core shipment lifecycle:

```text
PLANNED
   ↓
READY
   ↓
IN_TRANSIT
   ↓
ARRIVED
   ↓
DELIVERED
```

A future version may add cancellation, return, or failure states, but those are not required for v3.

---

## 2.2 State Definitions

### PLANNED

The shipment exists in the simulation plan but is not yet ready for dispatch.

Expected properties:

```text
scheduled_departure     populated
scheduled_arrival       populated
estimated_arrival       populated or initialized
actual_departure        NULL
actual_arrival          NULL
delivery_completed_at   NULL
```

Typical activities:

- shipment assignment,
- vehicle allocation,
- route planning,
- warehouse preparation,
- cargo preparation.

A `PLANNED` shipment is not yet physically in motion.

---

### READY

The shipment is operationally ready for departure but has not yet left the origin warehouse.

Expected properties:

```text
actual_departure        NULL
actual_arrival          NULL
```

Possible conditions during `READY`:

- awaiting loading completion,
- queueing for dock departure,
- waiting for vehicle availability,
- priority handling,
- warehouse congestion,
- final dispatch checks.

`READY` provides an explicit place to model departure delay without falsely treating the shipment as already in transit.

---

### IN_TRANSIT

The shipment has departed the origin warehouse and is actively executing the route.

Required condition:

```text
actual_departure IS NOT NULL
actual_arrival   IS NULL
```

While `IN_TRANSIT`, the simulation may update:

- vehicle position,
- speed,
- fuel,
- route progress,
- cargo temperature,
- estimated arrival,
- performance state,
- operational events.

Examples of events during this state:

```text
TRAFFIC_DELAY
WEATHER_DELAY
FUEL_STOP
MECHANICAL_WARNING
TEMP_EXCURSION
ETA_UPDATED
```

---

### ARRIVED

The vehicle has physically reached the destination facility, but final delivery completion has not yet occurred.

Required condition:

```text
actual_arrival IS NOT NULL
```

Possible activities:

- destination queueing,
- gate processing,
- unloading,
- receiving checks,
- cold-chain inspection,
- proof-of-delivery preparation.

The `ARRIVED` state exists because physical arrival and business completion are not always the same event.

---

### DELIVERED

The shipment has completed the required destination handling and is considered fulfilled.

Expected properties:

```text
actual_departure        populated
actual_arrival          populated
delivery_completed_at   populated
```

A `DELIVERY` event SHALL exist for the shipment.

`DELIVERED` is terminal for the v3 core lifecycle.

---

# 3. Valid State Transitions

The normal transition path is:

```text
PLANNED
   │
   ▼
READY
   │
   ▼
IN_TRANSIT
   │
   ▼
ARRIVED
   │
   ▼
DELIVERED
```

The following direct transitions are NOT valid in v3:

```text
PLANNED      → IN_TRANSIT
PLANNED      → ARRIVED
PLANNED      → DELIVERED
READY        → ARRIVED
READY        → DELIVERED
IN_TRANSIT   → DELIVERED
```

The generator SHALL transition through the required intermediate state.

---

# 4. State Transition Rules

## 4.1 PLANNED → READY

A shipment may transition to `READY` when:

- the simulation clock reaches its preparation window,
- the assigned vehicle is available,
- the origin warehouse can begin fulfillment,
- required cargo/vehicle compatibility is satisfied.

This transition does NOT imply departure.

Possible event:

```text
SHIPMENT_READY
```

This event is optional for v3 persistence but may exist internally.

---

## 4.2 READY → IN_TRANSIT

This transition occurs when the vehicle physically departs.

At transition:

```text
actual_departure = simulation_time
```

A `DEPARTURE` event SHALL be created.

The vehicle becomes unavailable for another shipment.

The shipment's route-progress state begins.

---

## 4.3 IN_TRANSIT → ARRIVED

This transition occurs only when route execution reaches the destination.

At transition:

```text
actual_arrival = simulation_time
```

An `ARRIVAL` event SHALL be created.

The vehicle position SHALL be consistent with the destination warehouse.

---

## 4.4 ARRIVED → DELIVERED

This transition occurs after required destination dwell and receiving operations complete.

At transition:

```text
delivery_completed_at = simulation_time
```

A `DELIVERY` event SHALL be created.

The vehicle may become available for its next shipment only after any configured turnaround requirements are satisfied.

---

# 5. Delivery Performance State

Lifecycle state answers:

> Where is the shipment operationally?

Performance state answers:

> How is the shipment performing against its delivery commitment?

These are independent dimensions.

---

## 5.1 Performance States

Supply Chain v3 SHALL support the following delivery-performance states:

```text
ON_TIME
AT_RISK
LATE
```

For completed shipments, the final performance result may be reported as:

```text
ON_TIME
LATE
```

`AT_RISK` is primarily an active-shipment condition.

---

## 5.2 ON_TIME

For an active shipment:

```text
estimated_arrival <= scheduled_arrival + tolerance
```

For a completed shipment:

```text
actual_arrival <= scheduled_arrival + tolerance
```

The default tolerance SHOULD initially be zero unless a service-level tolerance is explicitly configured.

---

## 5.3 AT_RISK

An active shipment is `AT_RISK` when current conditions indicate a meaningful probability of missing the scheduled arrival but the current ETA has not yet crossed the late threshold.

Example causes:

- accumulating warehouse dwell,
- developing congestion,
- worsening weather,
- equipment degradation,
- insufficient schedule buffer.

The first v3 implementation may use deterministic thresholds rather than probabilistic prediction.

Example:

```text
schedule_slack < configured_at_risk_threshold
```

---

## 5.4 LATE

For an active shipment:

```text
estimated_arrival > scheduled_arrival
```

For a completed shipment:

```text
actual_arrival > scheduled_arrival
```

A shipment may therefore be:

```text
IN_TRANSIT + LATE
```

or:

```text
DELIVERED + LATE
```

This is intentional.

---

# 6. Timestamp Semantics

## 6.1 scheduled_departure

Represents the original planned departure commitment.

It SHALL NOT be rewritten to hide departure delay.

---

## 6.2 scheduled_arrival

Represents the original planned service commitment.

It SHALL remain stable after execution begins.

This is the baseline used for:

- on-time delivery calculations,
- schedule variance,
- ETA variance,
- lateness severity.

---

## 6.3 estimated_arrival

Represents the best current simulation estimate of arrival.

It MAY change repeatedly while a shipment is active.

Examples:

```text
scheduled_arrival = 18:00
initial ETA       = 17:52
traffic event     = +25 min
new ETA           = 18:17
recovery          = -8 min
new ETA           = 18:09
```

The original `scheduled_arrival` remains `18:00`.

---

## 6.4 actual_departure

Represents the observed simulated departure.

Before departure:

```text
actual_departure IS NULL
```

At `READY → IN_TRANSIT`:

```text
actual_departure = simulation_time
```

---

## 6.5 actual_arrival

Represents physical arrival at the destination.

Before arrival:

```text
actual_arrival IS NULL
```

At `IN_TRANSIT → ARRIVED`:

```text
actual_arrival = simulation_time
```

This corrects the v2 behavior where an in-transit shipment could already contain a future actual arrival.

---

## 6.6 delivery_completed_at

Represents completion of destination handling.

Before `DELIVERED`:

```text
delivery_completed_at IS NULL
```

At `ARRIVED → DELIVERED`:

```text
delivery_completed_at = simulation_time
```

This field is proposed for v3 and will be confirmed in `schema-changes.md`.

---

# 7. ETA Evolution

ETA SHALL be derived from current simulation state.

A conceptual model is:

```text
current_time
    +
remaining_route_time
    +
known operational delay
    +
expected destination delay
    -
recoverable schedule buffer
    =
estimated_arrival
```

The first v3 implementation does not need a sophisticated forecasting model.

It does need causal consistency.

---

## 7.1 ETA Update Triggers

ETA SHOULD be recalculated when material state changes occur.

Examples:

```text
departure occurs
traffic condition changes
weather impact begins/ends
fuel stop begins/ends
mechanical degradation affects speed
warehouse/destination congestion changes
route progress crosses configured checkpoints
```

---

## 7.2 ETA_UPDATED Events

An `ETA_UPDATED` event SHOULD be emitted only when the new ETA changes by a meaningful configured threshold.

This avoids creating excessive events for tiny fluctuations.

Example threshold:

```text
5 minutes
```

The exact threshold will be configurable.

---

# 8. Delay Attribution

A shipment may accumulate delay from multiple causes.

The model SHOULD track delay contributions conceptually as:

```text
departure_delay_minutes
traffic_delay_minutes
weather_delay_minutes
fuel_delay_minutes
mechanical_delay_minutes
destination_delay_minutes
recovery_minutes
```

The final implementation may store these in event detail rather than dedicated shipment columns.

The persistence design will be finalized in `schema-changes.md`.

---

# 9. Schedule Recovery

Schedule recovery SHALL be modeled explicitly.

Example:

```text
scheduled_arrival      18:00
current ETA            18:35
congestion clears
normal route speed resumes
schedule buffer exists
new ETA                18:22
```

Recovery SHALL NOT be produced by:

- exceeding configured maximum speed,
- teleporting route progress,
- skipping required events.

---

# 10. Shipment Lifecycle and Vehicle Availability

Vehicle availability SHALL follow shipment lifecycle.

A vehicle is considered committed beginning no later than:

```text
READY
```

and remains unavailable through at least:

```text
ARRIVED
```

The exact release point MAY be after `DELIVERED` plus turnaround time.

This will be coordinated with the vehicle-domain model.

---

# 11. Shipment Lifecycle and Warehouse State

The origin warehouse may influence:

```text
PLANNED → READY
READY → IN_TRANSIT
```

The destination warehouse may influence:

```text
ARRIVED → DELIVERED
```

This allows warehouse congestion to affect different parts of the lifecycle rather than being represented only as generic shipment delay.

---

# 12. Event Mapping

The following event/state relationship is proposed:

```text
Lifecycle transition / condition     Event
----------------------------------   -------------------
PLANNED → READY                      SHIPMENT_READY
READY → IN_TRANSIT                   DEPARTURE
route checkpoint                     SCAN
traffic disruption                   TRAFFIC_DELAY
weather disruption                   WEATHER_DELAY
origin/destination congestion        WAREHOUSE_DELAY
fueling                              FUEL_STOP
mechanical condition                 MECHANICAL_WARNING
material ETA change                  ETA_UPDATED
temperature threshold violation      TEMP_EXCURSION
IN_TRANSIT → ARRIVED                 ARRIVAL
ARRIVED → DELIVERED                  DELIVERY
```

Not every internal state transition must be persisted if doing so adds no analytical value, but persisted events SHALL remain consistent with lifecycle state.

---

# 13. Example Normal Shipment

```text
08:00  PLANNED
10:00  READY
10:18  DEPARTURE
       lifecycle = IN_TRANSIT
       performance = ON_TIME

13:45  ETA updated from 18:00 to 17:52

17:50  ARRIVAL
       lifecycle = ARRIVED
       performance = ON_TIME

18:12  DELIVERY
       lifecycle = DELIVERED
       final performance = ON_TIME
```

Important distinction:

```text
actual_arrival = 17:50
delivery_completed_at = 18:12
```

---

# 14. Example Delayed Shipment

```text
08:00  PLANNED
09:30  READY
09:55  DEPARTURE
       initial ETA = 17:40
       scheduled arrival = 18:00

13:10  TRAFFIC_DELAY
       ETA = 18:28
       performance = LATE

14:40  congestion clears
       ETA = 18:16

18:17  ARRIVAL
       lifecycle = ARRIVED
       actual arrival = 18:17
       performance = LATE

18:38  DELIVERY
       lifecycle = DELIVERED
       final performance = LATE
```

Final lateness:

```text
17 minutes
```

This is the type of minor delay absent from v2.

---

# 15. Example At-Risk Shipment

```text
scheduled arrival = 20:00
current ETA       = 19:54
remaining buffer  = 6 minutes
risk threshold    = 15 minutes
```

The shipment may be:

```text
IN_TRANSIT + AT_RISK
```

even though the current ETA is technically still on time.

This state gives us a useful future Grafana metric:

```text
Shipments At Risk
```

without falsely labeling them late.

---

# 16. Example Early Arrival

```text
scheduled arrival = 18:00
actual arrival    = 17:32
```

Final performance:

```text
ON_TIME
```

The generator SHOULD produce some early arrivals when route and operating conditions make them plausible.

Early arrival does not require rescheduling the original commitment.

---

# 17. Invalid State Examples

The following SHALL fail validation.

## Invalid: in transit with actual arrival

```text
lifecycle = IN_TRANSIT
actual_arrival = 2026-08-15 18:00
```

Reason:

```text
actual arrival cannot exist before ARRIVED
```

---

## Invalid: delivered without arrival

```text
lifecycle = DELIVERED
actual_arrival = NULL
```

Reason:

```text
delivery completion requires physical arrival
```

---

## Invalid: arrival before departure

```text
actual_departure = 12:00
actual_arrival   = 11:30
```

---

## Invalid: delivery before arrival

```text
actual_arrival        = 14:00
delivery_completed_at = 13:50
```

---

## Invalid: overlapping active shipments

```text
Vehicle 3
Shipment A: IN_TRANSIT 10:00–14:00
Shipment B: IN_TRANSIT 13:00–16:00
```

---

# 18. Core Lifecycle Invariants

The implementation SHALL enforce at least the following:

```text
PLANNED:
    actual_departure IS NULL
    actual_arrival IS NULL

READY:
    actual_departure IS NULL
    actual_arrival IS NULL

IN_TRANSIT:
    actual_departure IS NOT NULL
    actual_arrival IS NULL

ARRIVED:
    actual_departure IS NOT NULL
    actual_arrival IS NOT NULL
    delivery_completed_at IS NULL

DELIVERED:
    actual_departure IS NOT NULL
    actual_arrival IS NOT NULL
    delivery_completed_at IS NOT NULL
```

And:

```text
scheduled_arrival > scheduled_departure

actual_arrival > actual_departure
    when actual_arrival exists

delivery_completed_at >= actual_arrival
    when delivery_completed_at exists
```

---

# 19. Lifecycle State Versus Database Persistence

The lifecycle model is a domain concept.

The final schema does not necessarily need to persist every intermediate simulation attribute directly.

For example:

```text
performance state
```

may be calculated from:

```text
estimated_arrival
scheduled_arrival
actual_arrival
lifecycle state
```

rather than stored redundantly.

The schema design will favor:

```text
single source of truth
+
derivable analytics
```

over unnecessary duplicated state.

---

# 20. Backward Compatibility Considerations

The current `sc_shipments.status` column exists and may be retained, repurposed, or renamed.

The v3 migration should avoid ambiguous semantics.

Potential design:

```text
status → lifecycle_status
```

with values:

```text
PLANNED
READY
IN_TRANSIT
ARRIVED
DELIVERED
```

Delivery performance would then be derived or stored separately.

The final decision belongs in `schema-changes.md`.

---

# 21. Analytics Enabled by This Lifecycle

The v3 lifecycle supports substantially richer analytics.

Examples:

```text
On-Time Delivery Rate
Late Delivery Rate
Average Delay Severity
Average Departure Delay
ETA Variance
At-Risk Shipments
Warehouse Dwell Time
Destination Dwell Time
Transit Time
Schedule Recovery
Delay Cause Distribution
Delivery Completion Time
```

It also allows us to distinguish:

```text
vehicle has arrived
```

from:

```text
shipment has been delivered
```

which is operationally important.

---

# 22. Acceptance Criteria

This lifecycle design is accepted when the implementation can demonstrate:

1. a shipment moving through every required lifecycle state,
2. an on-time shipment,
3. an early shipment,
4. a minor late shipment,
5. a major late shipment,
6. an `AT_RISK` active shipment,
7. an ETA that worsens after a disruption,
8. an ETA that partially recovers,
9. no future `actual_arrival` on an active shipment,
10. correct event ordering,
11. correct vehicle availability,
12. automated rejection of invalid lifecycle combinations.

---

# 23. Requirement Traceability

Primary mappings:

```text
SC-FR-001  → lifecycle states and transitions
SC-FR-002  → lifecycle/performance separation
SC-FR-003  → actual-arrival semantics
SC-FR-004  → ETA
SC-FR-005  → immutable schedule baseline
SC-DR-001  → early/minor/moderate/major arrival variance
SC-DR-002  → causal delay
SC-DR-003  → cumulative delay
SC-DR-004  → schedule recovery
SC-FR-006  → causal event model
SC-FR-008  → event timing
SC-DQ-001  → temporal integrity
SC-DQ-002  → no premature actual arrival
SC-DQ-007  → delivery completion integrity
```

---

# 24. Decision Status

The following design decisions are proposed for lock-in:

```text
1. Core lifecycle:
   PLANNED → READY → IN_TRANSIT → ARRIVED → DELIVERED

2. Lifecycle and performance are separate dimensions.

3. Performance states:
   ON_TIME / AT_RISK / LATE

4. scheduled_arrival is immutable after execution begins.

5. estimated_arrival is dynamic.

6. actual_arrival is NULL until physical arrival.

7. ARRIVED and DELIVERED are distinct states.

8. delivery_completed_at is proposed as a new v3 timestamp.

9. ETA changes originate from simulation state.

10. delay recovery is supported but physically constrained.
```

These decisions should be considered locked once reviewed and accepted, except where a later schema or domain-model constraint reveals a genuine contradiction.

---

## Next Artifact

The next document is:

```text
docs/model-v3/supply-chain/domain-model.md
```

That document will define the core v3 entities and persistent state for:

```text
Shipment
Vehicle
Route
Warehouse
Cargo
OperationalEvent
SimulationRun
```

and show how they relate to the lifecycle defined here.
