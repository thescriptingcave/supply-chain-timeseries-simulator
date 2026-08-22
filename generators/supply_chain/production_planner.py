"""Deterministic planning helpers for Supply Chain Generator v3."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .run_config import SupplyChainV3RunConfig


@dataclass(slots=True, frozen=True)
class ShipmentEventPlan:
    traffic: bool
    weather: bool
    mechanical: bool
    reefer_excursion: bool


def planned_shipment_count(
    *,
    vehicle_count: int,
    config: SupplyChainV3RunConfig,
) -> int:
    config.validate()

    if vehicle_count <= 0:
        raise ValueError("vehicle_count must be positive")

    return max(
        1,
        round(
            vehicle_count
            * config.simulation_days
            * config.target_shipments_per_vehicle_per_day
        ),
    )


def build_event_plan(
    *,
    rng: random.Random,
    config: SupplyChainV3RunConfig,
    requires_reefer: bool,
) -> ShipmentEventPlan:
    """Choose realistic event families for one shipment using seeded RNG."""
    config.validate()

    traffic = rng.random() < config.traffic_probability_per_shipment
    weather = rng.random() < config.weather_probability_per_shipment
    mechanical = (
        rng.random() < config.mechanical_probability_per_shipment
    )
    reefer_excursion = (
        requires_reefer
        and rng.random()
        < config.reefer_excursion_probability_per_shipment
    )

    return ShipmentEventPlan(
        traffic=traffic,
        weather=weather,
        mechanical=mechanical,
        reefer_excursion=reefer_excursion,
    )
