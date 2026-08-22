# Supply Chain Analytics Notebooks

These notebooks are an analytics layer over the validated Supply Chain V3 simulator.
They do **not** contain simulator/domain logic. Core simulation behavior remains in
`generators/supply_chain/` and is covered by the automated test suite.

## Setup

From the repository root:

```bash
uv sync --group notebook
uv run python -m ipykernel install --user \
  --name supply-chain-timeseries \
  --display-name "Supply Chain Time-Series"
uv run jupyter lab
```

Copy `.env.example` to `.env` before opening the notebooks if you have not already done so.
The notebooks read `DATABASE_URL` from `.env`.

## Notebook sequence

### 01 — Fleet Overview

`01_fleet_overview.ipynb`

Introduces the analytics environment and validates access to simulator data.

Topics include:

- connecting Jupyter to TimescaleDB
- identifying simulation runs
- inspecting table grain
- retrieving latest vehicle state
- querying fleet telemetry
- plotting fleet-speed time series

### 02 — Disruption Impact Analysis

`02_disruption_impact_analysis.ipynb`

Analyzes how operational disruptions affect vehicle and cargo telemetry.

The notebook correlates discrete events from `sc_events` with continuous telemetry
from `sc_fleet_telemetry` and constructs BEFORE / DURING / AFTER event windows.

Disruption types analyzed:

- traffic congestion
- heavy rain
- mechanical breakdown
- low-fuel refueling
- reefer temperature excursions

The notebook demonstrates:

- event lifecycle reconstruction
- event-window analysis
- interval-based telemetry joins
- SQL common table expressions (CTEs)
- Pandas aggregation and Boolean filtering
- before/during/after comparisons
- multivariate disruption signatures
- operational impact visualization
- quantitative impact measurement

The current validation dataset demonstrates distinct operational signatures,
including reduced vehicle speed during traffic and weather disruptions, complete
vehicle stops during mechanical failures and refueling, fuel replenishment during
fuel stops, and cargo-temperature excursions that occur independently of vehicle
movement.

### Planned notebooks

Future notebooks will extend the analytics layer into areas such as:

- shipment performance and delivery reliability
- route performance
- warehouse operations
- service-level analysis
- fleet utilization
- advanced time-series SQL
- anomaly detection and event correlation

## Design

The notebooks are consumers of simulator output and intentionally remain separate
from the simulation engine.

```text
Supply Chain V3 Simulator
        |
        v
TimescaleDB
        |
        +---- sc_fleet_telemetry
        +---- sc_events
        +---- sc_shipments
        +---- supporting domain tables
        |
        v
SQL analytical queries
        |
        v
Pandas
        |
        v
Jupyter notebooks
        |
        +---- exploration
        +---- visualization
        +---- operational analysis