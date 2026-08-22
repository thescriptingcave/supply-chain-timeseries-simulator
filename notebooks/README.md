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

1. `01_fleet_overview.ipynb` — connect to TimescaleDB, identify the latest run, inspect table grain, retrieve the latest vehicle state, and plot a fleet-speed time series.
2. Future notebooks will cover shipment performance, disruption impact, reefer excursions, and advanced time-series analysis.

## Design rule

Notebooks are for querying, analysis, visualization, and explanation. They should not become a second implementation of the simulator.
