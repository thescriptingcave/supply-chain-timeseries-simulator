"""Run profiles for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SupplyChainV3RunConfig:
    simulation_days: int = 2
    seed: int = 42
    movement_interval_seconds: float = 600.0
    warehouse_tick_seconds: float = 60.0
    base_consumption_pct_per_100km: float = 1.0

    traffic_probability_per_shipment: float = 0.08
    weather_probability_per_shipment: float = 0.05
    mechanical_probability_per_shipment: float = 0.015
    reefer_excursion_probability_per_shipment: float = 0.03

    fuel_trigger_pct: float = 25.0
    fuel_refill_pct: float = 90.0
    fuel_stop_minutes: float = 20.0

    target_shipments_per_vehicle_per_day: float = 1.5

    def validate(self) -> None:
        if self.simulation_days <= 0:
            raise ValueError("simulation_days must be positive")
        if self.seed < 0:
            raise ValueError("seed cannot be negative")
        if self.movement_interval_seconds <= 0:
            raise ValueError("movement_interval_seconds must be positive")
        if self.warehouse_tick_seconds <= 0:
            raise ValueError("warehouse_tick_seconds must be positive")
        if self.base_consumption_pct_per_100km <= 0:
            raise ValueError(
                "base_consumption_pct_per_100km must be positive"
            )

        for name, value in (
            ("traffic_probability_per_shipment", self.traffic_probability_per_shipment),
            ("weather_probability_per_shipment", self.weather_probability_per_shipment),
            ("mechanical_probability_per_shipment", self.mechanical_probability_per_shipment),
            ("reefer_excursion_probability_per_shipment", self.reefer_excursion_probability_per_shipment),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")

        if not 0 < self.fuel_trigger_pct < 100:
            raise ValueError("fuel_trigger_pct must be between 0 and 100")
        if not self.fuel_trigger_pct < self.fuel_refill_pct <= 100:
            raise ValueError(
                "fuel_refill_pct must exceed fuel_trigger_pct and be <= 100"
            )
        if self.fuel_stop_minutes <= 0:
            raise ValueError("fuel_stop_minutes must be positive")
        if self.target_shipments_per_vehicle_per_day <= 0:
            raise ValueError(
                "target_shipments_per_vehicle_per_day must be positive"
            )


def production_profile(*, days: int, seed: int) -> SupplyChainV3RunConfig:
    """Realistic event frequencies for longer historical runs."""
    return SupplyChainV3RunConfig(
        simulation_days=days,
        seed=seed,
        traffic_probability_per_shipment=0.08,
        weather_probability_per_shipment=0.05,
        mechanical_probability_per_shipment=0.015,
        reefer_excursion_probability_per_shipment=0.03,
    )


def validation_profile(*, days: int, seed: int) -> SupplyChainV3RunConfig:
    """Higher event density for short 2–7 day calibration runs.

    This profile is intentionally not the long-run production distribution.
    It exists so a small validation dataset contains enough examples of each
    event family to inspect in SQL and Grafana.
    """
    return SupplyChainV3RunConfig(
        simulation_days=days,
        seed=seed,
        traffic_probability_per_shipment=0.20,
        weather_probability_per_shipment=0.15,
        mechanical_probability_per_shipment=0.08,
        reefer_excursion_probability_per_shipment=0.25,
    )
