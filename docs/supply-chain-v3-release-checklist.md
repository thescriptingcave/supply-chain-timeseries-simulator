# Supply Chain V3 — Release Checklist

## Code
- [ ] `uv run python -m pytest tests/supply_chain -q` passes
- [ ] No temporary debug code remains
- [ ] No known import/collection errors
- [ ] Live streamer starts without exception

## Batch datasets
- [ ] Validation dataset passes
- [ ] Production-scale dataset passes
- [ ] Historical dataset passes
- [ ] Run metadata is persisted

## Live
- [ ] Normal live streaming works
- [ ] Traffic works
- [ ] Heavy rain works
- [ ] Mechanical works
- [ ] Fuel stop works
- [ ] Reefer works
- [ ] Mixed demo works

## Persistence
- [ ] No future telemetry
- [ ] No duplicate vehicle/timestamp telemetry
- [ ] Mechanical stop odometer delta = 0
- [ ] Fuel stop odometer delta = 0
- [ ] Reefer START/END metadata use the same event window
- [ ] All expected causal codes are present

## Release decision
- [ ] Supply Chain V3 accepted
