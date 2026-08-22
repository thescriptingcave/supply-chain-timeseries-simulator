"""Configuration defaults and validation for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(slots=True, frozen=True)
class PriorityRule:
    queue_factor: float
    loading_factor: float
    recovery_factor: float
    at_risk_threshold_min: float


@dataclass(slots=True, frozen=True)
class SimulationConfig:
    fleet_telemetry_interval: timedelta = timedelta(seconds=10)
    warehouse_telemetry_interval: timedelta = timedelta(minutes=1)
    route_state_interval: timedelta = timedelta(minutes=5)
    warehouse_state_interval: timedelta = timedelta(minutes=1)
    eta_event_threshold_min: float = 5.0
    fuel_reserve_threshold_pct: float = 15.0
    fuel_refill_min_pct: float = 75.0
    fuel_refill_max_pct: float = 95.0
    batch_size: int = 5000

    standard_priority: PriorityRule = PriorityRule(
        queue_factor=1.00,
        loading_factor=1.00,
        recovery_factor=1.00,
        at_risk_threshold_min=15.0,
    )
    expedited_priority: PriorityRule = PriorityRule(
        queue_factor=0.85,
        loading_factor=0.90,
        recovery_factor=1.05,
        at_risk_threshold_min=20.0,
    )
    critical_priority: PriorityRule = PriorityRule(
        queue_factor=0.65,
        loading_factor=0.80,
        recovery_factor=1.10,
        at_risk_threshold_min=30.0,
    )

    def validate(self) -> None:
        if self.fleet_telemetry_interval <= timedelta(0):
            raise ValueError("fleet_telemetry_interval must be positive")
        if self.warehouse_telemetry_interval <= timedelta(0):
            raise ValueError("warehouse_telemetry_interval must be positive")
        if self.route_state_interval <= timedelta(0):
            raise ValueError("route_state_interval must be positive")
        if self.warehouse_state_interval <= timedelta(0):
            raise ValueError("warehouse_state_interval must be positive")
        if self.eta_event_threshold_min <= 0:
            raise ValueError("eta_event_threshold_min must be positive")
        if not 0 < self.fuel_reserve_threshold_pct < 100:
            raise ValueError("fuel reserve threshold must be between 0 and 100")
        if not (
            self.fuel_reserve_threshold_pct
            < self.fuel_refill_min_pct
            <= self.fuel_refill_max_pct
            <= 100
        ):
            raise ValueError("invalid fuel refill thresholds")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")


DEFAULT_CONFIG = SimulationConfig()
