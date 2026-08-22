# Supply Chain Time-Series Simulator — V3

A stateful synthetic Supply Chain simulator designed to generate **historical and true-live operational time-series data** for PostgreSQL/TimescaleDB.

The project models concurrent shipments, vehicle telemetry, warehouse operations, ETA evolution, and causal operational disruptions. It was built as a hands-on platform for software quality engineering, time-series SQL, TimescaleDB, and operational analytics.

## Project status

**Supply Chain V3: Complete.**

The public repository contains only the completed Supply Chain domain. Earlier Solar and Refinery experiments from the original development workspace are intentionally excluded.

## What the simulator models

- Stateful vehicle movement and route progression
- Concurrent shipments and vehicle scheduling
- Shipment lifecycle and evolving ETA
- Fuel consumption and refueling stops
- Warehouse loading/unloading contention
- Cargo and reefer temperature behavior
- Traffic congestion
- Heavy rain / weather slowdowns
- Mechanical breakdowns and recovery
- Causal operational events tied to telemetry
- Historical batch generation
- True wall-clock live streaming
- Deterministic simulation seeds and run metadata

The core design principle is **causality before randomness**:

```text
configuration
    ↓
persistent operational state
    ↓
causal event
    ↓
telemetry effect
    ↓
ETA / shipment outcome
    ↓
validation
```

## Technology

- Python 3.12
- PostgreSQL 16 / TimescaleDB
- Docker Compose
- Grafana 11
- pytest
- uv
- SQL / JSONB / continuous aggregates

## Repository layout

```text
.
├── generators/
│   └── supply_chain/        # Domain model and simulation engine
├── scripts/                 # Validation, historical, production, scenario, live runners
├── tests/
│   └── supply_chain/        # Automated Supply Chain test suite
├── sql/
│   ├── init/                # Fresh database bootstrap
│   ├── validation/          # Scenario and acceptance validation SQL
│   └── analytics/           # Representative analytical queries
├── docs/                    # Requirements, architecture, lifecycle, rules, acceptance docs
├── grafana/                 # Supply Chain Grafana provisioning
├── docker-compose.yaml
├── pyproject.toml
└── uv.lock
```

## Quick start

### Prerequisites

- Docker / Docker Compose
- Python 3.12+
- `uv`

### 1. Clone and configure

```bash
git clone <your-repository-url>
cd supply-chain-timeseries-simulator
cp .env.example .env
```

The supplied `.env.example` uses local-development credentials only. Change them if desired.

### 2. Start TimescaleDB and Grafana

```bash
docker compose up -d
```

Default local endpoints:

```text
TimescaleDB: localhost:5432
Grafana:     http://localhost:3000
```

### 3. Install Python dependencies

```bash
uv sync
```

### 4. Run the automated tests

Use module invocation so the repository root is on Python's import path:

```bash
uv run python -m pytest tests/supply_chain -q
```

### 5. Generate a short validation dataset

```bash
uv run python -m scripts.generate_supply_chain_v3_validation
```

### 6. Generate historical data

```bash
uv run python -m scripts.generate_supply_chain_v3_historical --help
```

The historical runner supports long-window datasets suitable for time-series analytics.

### 7. Run true-live streaming

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60
```

### 8. Run the mixed disruption demo

```bash
uv run python -m scripts.stream_supply_chain_v3 \
  --shipment-interval 60 \
  --movement-interval 60 \
  --mixed-demo
```

This deterministically exercises traffic, weather, mechanical, fuel-stop, and reefer behavior on separate concurrent shipments.

## Core data model

```text
sc_vehicles
     │
     ├──────────────┐
     ▼              │
sc_shipments ───► sc_routes
     │
     ├──────────────► sc_events
     │
     ▼
sc_fleet_telemetry

sc_warehouses
     │
     ├── sc_warehouse_env
     └── sc_warehouse_operations
```

`sc_simulation_runs` records generator version, deterministic seed lineage, simulation boundaries, status, and run metadata.

## Causal disruption model

Validated live disruption families include:

| Cause | Observable effect |
|---|---|
| `TRAFFIC_CONGESTION` | Vehicle speed reduction and ETA change |
| `HEAVY_RAIN` | Weather-related speed reduction and ETA change |
| `MECHANICAL_BREAKDOWN` | Vehicle stops; odometer remains stationary |
| `LOW_FUEL_REFUEL` | Vehicle stops, refuels, then resumes |
| `REEFER_TEMP_EXCURSION` | Cargo temperature violates limits while vehicle movement continues |

## Quality and validation

The simulator is not considered successful simply because it inserts rows. The project uses layered verification:

```text
unit tests
    ↓
domain invariants
    ↓
integration tests
    ↓
short deterministic validation
    ↓
database validation SQL
    ↓
historical generation
    ↓
analytics validation
```

Examples of validated invariants include:

- No overlapping active shipments for the same vehicle
- No future telemetry in true-live mode
- No duplicate `(vehicle_id, time)` telemetry groups
- Mechanical stops do not advance the odometer
- Fuel stops do not advance the odometer
- Reefer START/END events describe the same excursion window
- Events asserting measurable conditions are supported by telemetry
- Simulation run metadata records actual live shutdown time

See [`docs/supply-chain-acceptance-tests.md`](docs/supply-chain-acceptance-tests.md) and [`docs/supply-chain-v3-final-acceptance.md`](docs/supply-chain-v3-final-acceptance.md).

## Historical and true-live modes

The system deliberately supports both:

**Historical generation** produces long windows quickly for SQL, TimescaleDB, performance, and trend analysis.

**True-live streaming** uses wall-clock execution and monotonic scheduling so telemetry is generated only when a real tick becomes due. It does not pre-generate future sample batches.

## Example time-series SQL

Latest reading for each vehicle in a run:

```sql
SELECT DISTINCT ON (vehicle_id)
    vehicle_id,
    shipment_id,
    time,
    speed_kmh,
    fuel_level_pct,
    cargo_temp_c
FROM sc_fleet_telemetry
WHERE run_id = 41
ORDER BY vehicle_id, time DESC;
```

Five-minute fleet profile:

```sql
SELECT
    time_bucket('5 minutes', time) AS bucket,
    vehicle_id,
    AVG(speed_kmh) AS avg_speed_kmh
FROM sc_fleet_telemetry
GROUP BY bucket, vehicle_id
ORDER BY bucket, vehicle_id;
```

More examples are in [`sql/analytics/portfolio_queries.sql`](sql/analytics/portfolio_queries.sql).

## Documentation

The repository includes the design artifacts used to build V3 rather than treating documentation as an afterthought:

- Findings / problem analysis
- Requirements
- Shipment lifecycle
- Domain model
- Simulation rules
- Schema design
- Python architecture
- Acceptance tests
- Final acceptance and release checklist

This provides traceability from **finding → requirement → design → implementation → test**.

## Portfolio intent

This project demonstrates work across:

- Stateful simulation and domain modeling
- Python software architecture
- Automated testing and QA gates
- PostgreSQL / TimescaleDB schema design
- High-volume time-series persistence
- Event/telemetry causality
- Historical and live data generation
- SQL analytics and Grafana integration

It is a synthetic learning and portfolio system, not a production logistics platform and not a model of any specific real-world carrier or facility.

## License

MIT. See [`LICENSE`](LICENSE).
