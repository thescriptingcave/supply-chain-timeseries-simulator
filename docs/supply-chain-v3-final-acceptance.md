# Supply Chain V3 — Final Acceptance and Operations Guide

## Status

Supply Chain V3 has completed functional validation for:

- historical generation
- production-scale generation
- true-live wall-clock streaming
- traffic congestion
- heavy rain
- mechanical breakdown
- low-fuel/refuel stop
- reefer temperature excursion
- mixed concurrent live disruptions

The live runtime uses monotonic scheduling for cadence and UTC timestamps for persisted business data.

---

## 1. Final test gate

Run the complete Supply Chain V3 test suite:

```bash
uv run python -m pytest tests/supply_chain -q
```

Expected result: all tests pass.

Do not continue to dataset generation if this gate fails.

---

## 2. Historical / batch generation

The project currently contains dedicated V3 batch runners:

```text
scripts/generate_supply_chain_v3_validation.py
scripts/generate_supply_chain_v3_production.py
scripts/generate_supply_chain_v3_historical.py
```

Use the established CLI for each runner in the repository.

Validated dataset profiles to date:

```text
Validation:   short deterministic validation dataset
Production:   30-day production-scale validation
Historical:   365-day historical dataset
```

The historical engine has already demonstrated that it can generate a full 365-day dataset and persist it successfully.

---

## 3. True-live streaming

Standard live mode:

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60
```

This should continuously create wall-clock shipments and emit one telemetry sample per due movement tick.

---

## 4. Deterministic live disruption modes

Traffic:

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60 \
  --traffic-demo
```

Weather:

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60 \
  --weather-demo
```

Mechanical:

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60 \
  --mechanical-demo
```

Fuel stop:

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60 \
  --fuel-demo
```

Reefer:

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60 \
  --reefer-demo
```

Mixed live acceptance:

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60 \
  --mixed-demo
```

`--mixed-demo` assigns traffic, weather, mechanical, fuel, and reefer behavior to separate live shipments so that the runtime can be validated under simultaneous disruption activity.

---

## 5. Acceptance invariants

Every accepted live run should satisfy:

```text
future telemetry rows = 0
duplicate (vehicle_id, time) groups = 0
```

Mechanical stop:

```text
speed = 0 while active
odometer delta = 0 while active
```

Fuel stop:

```text
speed = 0 while active
odometer delta = 0 while active
fuel rises explicitly during the stop
```

Reefer excursion:

```text
cargo telemetry violates configured threshold
vehicle continues moving
temperature recovers
START and END events describe the same excursion window
```

Traffic and weather:

```text
speed decreases only while the disruption is active
speed returns after the disruption clears
ETA changes are causally attributed
```

---

## 6. Event vocabulary used by the live runtime

Current causal codes:

```text
TRAFFIC_CONGESTION
HEAVY_RAIN
MECHANICAL_BREAKDOWN
LOW_FUEL_REFUEL
REEFER_TEMP_EXCURSION
```

Important event types include:

```text
DISRUPTION_STARTED
DISRUPTION_ENDED
ETA_UPDATED
FUEL_STOP_STARTED
FUEL_STOP_ENDED
CARGO_EXCEPTION_STARTED
CARGO_EXCEPTION_ENDED
```

---

## 7. Database truth

Primary live facts are persisted in:

```text
sc_shipments
sc_fleet_telemetry
sc_events
```

Use the database as the authoritative acceptance source.

Console output is diagnostic evidence, but persisted rows are the final validation target.

---

## 8. Recommended release rule

Treat Supply Chain V3 as complete when all of the following are true:

```text
[ ] full tests green
[ ] short validation dataset passes
[ ] production-scale dataset passes
[ ] historical dataset passes
[ ] standard live streamer starts successfully
[ ] mixed live scenario completes
[ ] mixed validation SQL passes
[ ] no future telemetry
[ ] no duplicate vehicle/timestamp telemetry
[ ] stop scenarios do not move odometer
[ ] reefer event window matches telemetry
```

After this point, changes should be driven by a new requirement, defect, analytics need, or performance requirement rather than continued generator expansion.
