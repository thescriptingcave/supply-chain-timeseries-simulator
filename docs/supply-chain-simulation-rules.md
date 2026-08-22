# Supply Chain v3 — Simulation Rules

## 1. Purpose

This document defines how Supply Chain v3 behaves over simulated time.

It operationalizes the entities defined in:

```text
docs/model-v3/supply-chain/domain-model.md
```

and implements the requirements defined in:

```text
docs/model-v3/supply-chain/requirements.md
```

The guiding principle is:

> Business outcomes must emerge from persistent state, domain rules, and causal events rather than from independent random outcomes.

This document defines behavior. It does not define the final Python module layout or database schema.

---

# 2. Simulation Execution Model

Supply Chain v3 SHALL execute against one authoritative simulation clock.

Conceptually:

```text
SimulationRun
    ↓
advance time
    ↓
update warehouse state
    ↓
update route state
    ↓
update vehicle state
    ↓
update shipment lifecycle
    ↓
process operational events
    ↓
recalculate ETA
    ↓
emit telemetry
    ↓
validate invariants
    ↓
persist bounded batches
```

The implementation MAY optimize this sequence, but observable outcomes must remain equivalent.

---

# 3. Simulation Time Step

Fleet telemetry currently operates at 10-second granularity.

Supply Chain v3 SHOULD preserve:

```text
fleet telemetry:       10 seconds
warehouse telemetry:    1 minute
```

Not every domain state must be recalculated at every 10-second step.

Examples:

```text
vehicle movement         10 seconds
traffic state             5–15 minutes
warehouse congestion      1–5 minutes
ETA recalculation         event-driven / material change
```

This allows realistic behavior without unnecessary computation.

---

# 4. Randomness

All stochastic behavior SHALL use the simulation's seeded random source.

No domain module should independently initialize uncontrolled randomness.

Conceptually:

```text
SimulationRun.rng
```

owns random generation.

Where useful, deterministic substreams MAY be derived for:

```text
shipment demand
routes
warehouses
vehicles
weather
events
```

This prevents one unrelated implementation change from unnecessarily changing every random outcome.

---

# 5. Shipment Generation

## 5.1 Shipment Demand

Shipments SHALL be generated across the complete requested simulation window.

Demand SHOULD vary over time rather than create perfectly even work allocation.

Demand MAY be influenced by:

```text
warehouse
route
day of week
hour of day
priority mix
cargo mix
```

The first v3 implementation does not require a demand-forecasting system.

---

## 5.2 Demand Profiles

Each origin/destination pair MAY have a relative demand weight.

Example:

```text
Phoenix → Houston         1.30
Houston → Los Angeles     1.15
El Paso → Phoenix         0.80
```

Weights influence shipment frequency but do not guarantee exact counts.

This should create natural long-window route-volume differences.

---

## 5.3 Priority Distribution

Baseline priority distribution may remain approximately:

```text
STANDARD      75%
EXPEDITED     20%
CRITICAL       5%
```

but priority selection MAY vary by cargo type or route.

The distribution must be configurable.

---

# 6. Shipment Scheduling

## 6.1 Planned Departure

Scheduled departure SHALL be created before operational execution.

It represents the planned dispatch commitment.

---

## 6.2 Scheduled Arrival

Scheduled arrival SHALL be based on:

```text
planned departure
+
route baseline travel time
+
planned operational allowances
```

Planned allowances MAY include:

```text
expected loading time
expected required stop time
expected destination handling buffer
```

Scheduled arrival SHALL NOT include future random disruptions.

---

## 6.3 Schedule Buffer

Each shipment MAY include implicit schedule buffer.

Buffer allows:

```text
minor disruption
    ↓
delay accumulation
    ↓
partial recovery
    ↓
still on-time delivery
```

This is required to avoid binary all-or-nothing lateness.

---

# 7. Vehicle Assignment

## 7.1 Eligibility

A vehicle is eligible only if:

```text
AVAILABLE
cargo-compatible
not overlapping another shipment
located at the required origin
or explicitly repositionable under a supported rule
```

Ordinary v3 shipments SHOULD prefer vehicles already at the origin.

---

## 7.2 Assignment Factors

Vehicle assignment MAY consider:

```text
availability
vehicle type
cargo compatibility
condition
reliability
recent utilization
```

The first implementation does not require optimization.

A weighted eligible selection is sufficient.

---

## 7.3 Workload Balance

Assignment SHOULD avoid artificial round-robin equality.

The system should create plausible variation while preventing starvation of valid vehicles.

---

# 8. Warehouse Readiness

## 8.1 PLANNED → READY

A shipment transitions to `READY` after preparation requirements are satisfied.

Readiness MAY be affected by:

```text
origin warehouse state
cargo type
priority
loading capacity
queue depth
vehicle availability
```

---

## 8.2 Loading Dwell

Loading dwell SHOULD be calculated from:

```text
warehouse baseline loading time
× warehouse congestion factor
× cargo handling factor
× priority adjustment
+ stochastic operational noise
```

Conceptually:

```text
loading_minutes =
    baseline
    × congestion
    × cargo_factor
    × priority_factor
    + noise
```

The exact function will be implemented later.

---

# 9. Priority Handling

Priority SHALL affect operations without guaranteeing outcomes.

Suggested initial effects:

```text
STANDARD
    normal queue position
    normal loading dwell
    normal recovery behavior

EXPEDITED
    reduced queue penalty
    modestly reduced loading dwell
    stronger recovery preference

CRITICAL
    highest dispatch preference
    lowest discretionary dwell
    strongest recovery preference
```

Priority SHALL NOT:

```text
eliminate traffic
eliminate weather
eliminate mechanical failure
permit unsafe speed
guarantee on-time arrival
```

---

# 10. Departure

## 10.1 READY → IN_TRANSIT

Departure occurs when:

```text
loading complete
vehicle ready
required dispatch conditions satisfied
```

At departure:

```text
actual_departure = current_time
shipment.lifecycle = IN_TRANSIT
vehicle.availability = IN_TRANSIT
```

A `DEPARTURE` event SHALL be generated.

---

# 11. Route Travel

## 11.1 Base Target Speed

Target travel speed SHALL derive from:

```text
route nominal speed
× vehicle cruise factor
× traffic factor
× weather factor
× mechanical factor
```

then be bounded by:

```text
route minimum / maximum
vehicle maximum
global safety limits
```

---

## 11.2 Departure and Arrival Zones

The first and final portion of a trip SHOULD operate below highway cruise speed.

Example:

```text
first 3–5%     terminal / urban acceleration
middle         route cruise behavior
last 3–5%      deceleration / destination approach
```

This preserves useful behavior from v2 while making the factors configurable.

---

# 12. Traffic Model

## 12.1 Traffic State

Each route MAY have:

```text
FREE_FLOW
MODERATE
HEAVY
INCIDENT
```

Traffic state should persist for meaningful durations.

It SHALL NOT be independently redrawn every 10 seconds.

---

## 12.2 Time-of-Day Effects

Traffic-state probabilities SHALL be influenced by route profile and time.

Example:

```text
07:00–09:00     elevated congestion probability
16:00–18:00     elevated congestion probability
overnight       increased free-flow probability
```

Directional routes may use different profiles.

---

## 12.3 Traffic Incidents

Rare incidents MAY create stronger temporary disruption.

An incident SHOULD have:

```text
start_time
duration
speed impact
affected route
severity
```

A material incident SHALL produce a corresponding operational event.

---

# 13. Weather Model for Supply Chain

Supply Chain v3 does not require external historical weather.

It MAY model simplified regional weather states sufficient to influence travel.

Possible states:

```text
CLEAR
RAIN
HEAVY_RAIN
WIND
EXTREME_HEAT
```

Weather SHOULD persist over meaningful periods and affect compatible routes.

Potential effects:

```text
reduced speed
increased incident probability
longer stopping distance
reefer load impact
```

Full meteorological modeling remains outside v3.

---

# 14. Fuel Model

## 14.1 Consumption

Fuel consumption SHALL depend on vehicle operation.

Conceptually:

```text
fuel_consumption =
    distance_traveled
    × vehicle fuel efficiency factor
    × operating-condition factor
```

Possible condition effects:

```text
high speed
heavy congestion
idling
cargo type
```

---

## 14.2 Low-Fuel Threshold

A vehicle approaching a configured reserve threshold SHALL schedule a refueling stop when required.

Example:

```text
reserve threshold: 15%
target refill:      75–95%
```

---

## 14.3 Fuel Stop

A fuel stop SHALL:

```text
reduce speed to zero
pause route progress
consume time
increase fuel
generate FUEL_STOP event
affect ETA when material
```

Fuel SHALL NOT silently jump upward.

---

# 15. Mechanical Condition

## 15.1 Persistent Reliability

Vehicles SHALL have a persistent reliability/condition profile.

A vehicle with weaker condition MAY have:

```text
higher warning probability
higher disruption probability
slightly reduced performance
```

---

## 15.2 Mechanical Warning

A mechanical warning MAY:

```text
reduce maximum speed
increase fuel use
trigger inspection dwell
increase ETA
```

It does not need to represent a full breakdown system.

---

## 15.3 Out-of-Service

Rare severe conditions MAY place a vehicle temporarily `OUT_OF_SERVICE`.

If this occurs during a trip, v3 may model:

```text
extended delay
recovery period
```

Vehicle replacement/re-dispatch is optional for v3 and may be deferred if it creates excessive complexity.

---

# 16. Cargo Temperature Model

## 16.1 Reefer Setpoint

Reefer cargo SHALL have a configured target temperature.

Example:

```text
FROZEN_FOOD      -18 C
PHARMA            2–8 C or configured profile
FRESH_PRODUCE     cargo-specific range
```

---

## 16.2 Temperature Evolution

Temperature SHALL evolve gradually.

Conceptually:

```text
next_temp =
    current_temp
    + ambient influence
    + door influence
    + refrigeration correction
    + fault influence
```

No independent redraw per telemetry sample.

---

## 16.3 Door Events

Door opening near warehouses may temporarily increase temperature drift.

Door state SHOULD remain consistent with vehicle speed and location.

---

## 16.4 Refrigeration Fault

A refrigeration fault MAY cause:

```text
temperature drift
ETA-independent cargo risk
TEMP_EXCURSION
```

The event SHALL be derived from telemetry threshold crossing.

---

# 17. Delay Accumulation

Delay SHOULD be represented as the result of operational effects.

Potential contributors:

```text
origin warehouse dwell
late departure
traffic
weather
fuel stop
mechanical issue
destination queue
```

Conceptually:

```text
net_delay =
    gross_delay
    - recovered_time
```

---

# 18. Schedule Recovery

Recovery MAY occur when:

```text
traffic improves
weather clears
warehouse dwell is shorter than planned
vehicle travels at normal upper-range speed
route buffer remains
```

Recovery SHALL never depend on:

```text
unsafe speed
negative dwell
teleportation
discarding required stops
```

---

# 19. ETA Calculation

ETA SHALL be recalculated from current state.

Conceptually:

```text
ETA =
    current_time
    + estimated remaining travel time
    + expected known stop time
    + expected destination dwell
```

The model MAY incorporate remaining schedule buffer.

---

## 19.1 Material ETA Change

An `ETA_UPDATED` event SHOULD be emitted only when ETA changes by more than a configured threshold.

Suggested starting threshold:

```text
5 minutes
```

---

# 20. Performance-State Rules

## 20.1 ON_TIME

Active shipment:

```text
ETA safely <= scheduled arrival
```

Completed shipment:

```text
actual_arrival <= scheduled arrival
```

---

## 20.2 AT_RISK

Use remaining schedule slack.

Conceptually:

```text
slack_minutes =
    scheduled_arrival - ETA
```

If:

```text
0 < slack_minutes <= at_risk_threshold
```

then:

```text
performance = AT_RISK
```

Suggested initial threshold:

```text
15 minutes
```

configurable by priority/service level.

---

## 20.3 LATE

Active:

```text
ETA > scheduled_arrival
```

Completed:

```text
actual_arrival > scheduled_arrival
```

---

# 21. Arrival

`IN_TRANSIT → ARRIVED` occurs when route execution reaches destination.

At that moment:

```text
actual_arrival = current_time
vehicle location = destination
vehicle speed approaches zero
```

An `ARRIVAL` event SHALL be emitted.

---

# 22. Destination Dwell

Arrival does not immediately imply delivery completion.

Destination dwell MAY depend on:

```text
warehouse congestion
unloading capacity
cargo type
priority
inspection requirements
```

---

# 23. Delivery Completion

`ARRIVED → DELIVERED` occurs when destination handling is complete.

At that moment:

```text
delivery_completed_at = current_time
```

A `DELIVERY` event SHALL be emitted.

---

# 24. Vehicle Turnaround

After delivery, the vehicle MAY enter:

```text
TURNAROUND
```

for:

```text
cleanup
inspection
driver-independent operational rest abstraction
maintenance checks
dispatch delay
```

After turnaround:

```text
AVAILABLE
```

The vehicle's current warehouse SHALL equal the shipment destination.

---

# 25. Warehouse Dynamic State

Warehouse state SHOULD be derived from workload.

Example inputs:

```text
active load operations
active unload operations
queue depth
time of day
configured capacity
```

Possible state rule:

```text
load < 60% capacity       NORMAL
60–85%                    BUSY
>85%                      CONGESTED
```

Exact thresholds will be configurable.

---

# 26. Warehouse Telemetry Coupling

Warehouse environmental telemetry SHOULD partially reflect facility activity.

Examples:

```text
higher occupancy
    ↓
higher CO2

higher door activity
    ↓
temperature disturbance

cold-storage load
    ↓
higher energy use

congestion
    ↓
higher occupancy / door activity
```

This avoids independent random warehouse telemetry.

---

# 27. Shipment Events

Events SHALL be generated from domain behavior.

Core events:

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

Not every shipment requires every event.

---

# 28. Event Severity

Suggested severity levels:

```text
INFO
WARNING
CRITICAL
```

Example:

```text
DEPARTURE           INFO
ETA_UPDATED         INFO
TRAFFIC_DELAY       WARNING
MECHANICAL_WARNING  WARNING
TEMP_EXCURSION      WARNING/CRITICAL
```

Severity must reflect operational impact rather than random selection.

---

# 29. Telemetry Emission

Fleet telemetry at each sample SHOULD be derived from vehicle state.

Expected fields include:

```text
time
vehicle_id
shipment_id
latitude
longitude
speed
heading
engine_rpm
fuel
cargo temperature
cargo humidity
door state
harsh braking
harsh acceleration
idle time
odometer
geofence
```

---

# 30. Geofence Rules

Geofence state SHOULD derive from route/location context rather than speed alone.

Possible states:

```text
ORIGIN_WAREHOUSE
DESTINATION_WAREHOUSE
URBAN
HIGHWAY
FUEL_STOP
```

A simplified implementation may still use speed/location heuristics, but warehouse proximity should be authoritative where possible.

---

# 31. Harsh Driving Events

Harsh braking and acceleration MAY remain stochastic but SHOULD be conditional on vehicle motion.

They SHOULD NOT occur when:

```text
speed = 0
```

Probability MAY increase under:

```text
heavy traffic
incident conditions
urban travel
```

---

# 32. Idle Time

Idle time SHALL accumulate while:

```text
engine running
speed near zero
```

It SHOULD reset or pause appropriately once vehicle movement resumes.

Parking with engine off should not necessarily count as engine-idle time.

---

# 33. Odometer

Odometer SHALL increase only with distance traveled.

Conceptually:

```text
distance_increment =
    speed_kmh × seconds_elapsed / 3600
```

Odometer SHALL never decrease.

---

# 34. Event Ordering

For a normal shipment:

```text
SHIPMENT_READY
PICKUP
DEPARTURE
[SCAN / operational events]
ARRIVAL
DELIVERY
```

The system SHALL reject logically impossible ordering.

---

# 35. Validation During Simulation

Critical invariants SHOULD be checked during or immediately after generation.

Examples:

```text
one active shipment per vehicle
valid lifecycle transition
no premature actual_arrival
fuel within bounds
route progress within 0–1
valid cargo/vehicle compatibility
event timestamps consistent
```

Long runs should fail fast on structural corruption.

---

# 36. Short Validation Scenarios

The two-day validation suite SHOULD intentionally exercise:

```text
normal on-time delivery
early delivery
minor delay
major delay
AT_RISK state
traffic disruption
fuel stop
warehouse congestion
ETA recovery
temperature excursion
vehicle-specific reliability difference
route-specific congestion difference
```

A fixed seed may be selected to guarantee coverage of these scenarios.

---

# 37. Full-Year Behavioral Expectations

A 365-day run SHOULD exhibit:

```text
non-identical vehicle utilization
non-identical route performance
non-identical warehouse dwell
broad but plausible delay distribution
early and late shipments
persistent route characteristics
persistent vehicle characteristics
priority effects without guarantees
causal events visible in analytics
```

No exact KPI target is mandated unless later acceptance criteria define one.

---

# 38. Anti-Patterns Explicitly Prohibited

Supply Chain v3 SHALL avoid:

```text
independent random actual_arrival assignment
silent fuel refill
instantaneous temperature redraw
random delay event added after outcome is already fixed
future actual_arrival on IN_TRANSIT shipment
random warehouse metrics unrelated to workload
perfectly balanced shipment assignment
priority that is only a label
route differences caused only by sample noise
```

---

# 39. Configuration Expectations

The following should become configuration-driven:

```text
route profiles
warehouse profiles
vehicle profiles
cargo profiles
priority rules
traffic windows
weather probabilities
fuel thresholds
ETA event threshold
AT_RISK threshold
batch sizes
```

The exact configuration representation will be defined in `architecture.md`.

---

# 40. Requirement Traceability

Examples:

```text
SC-DR-001
    → arrival variance rules

SC-DR-002 / 003 / 004
    → causal delay, accumulation, recovery

SC-DR-005 / 006 / 007
    → route behavior

SC-DR-008 / 009 / 010
    → warehouse behavior

SC-DR-011 through 017
    → vehicle/fuel behavior

SC-DR-018 / 019
    → priority handling

SC-DR-021 / 022 / 023
    → cargo temperature behavior

SC-FR-006 / 007 / 008
    → event generation

SC-FR-009 / 010 / 011
    → telemetry generation

SC-NFR-001 / 002
    → seeded deterministic behavior
```

---

# 41. Design Decisions Proposed for Lock-In

```text
1. One authoritative simulation clock.

2. Stateful conditions persist for realistic durations.

3. Shipment timing is not predetermined independently of trip execution.

4. Scheduled arrival is planned before disruptions occur.

5. ETA evolves from current operational state.

6. Delays may accumulate from multiple causes.

7. Schedule recovery is possible but physically bounded.

8. Priority affects handling, not external reality.

9. Fuel stops are explicit operational events.

10. Cargo temperature evolves as state.

11. Warehouse congestion derives partly from workload.

12. Route behavior is directional and persistent.

13. Vehicle behavior includes persistent reliability/condition differences.

14. Events are generated from domain behavior.

15. Telemetry reflects current domain state.

16. Validation occurs throughout the generation lifecycle.
```

---

# 42. Next Artifact

The next document is:

```text
docs/model-v3/supply-chain/schema-changes.md
```

That document will map this domain behavior onto PostgreSQL/TimescaleDB and determine:

```text
which existing columns remain
which columns change semantics
which columns are added
whether new configuration tables are required
simulation metadata storage
event-schema changes
migration/reset strategy
continuous aggregate impact
```
