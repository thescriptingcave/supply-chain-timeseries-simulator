"""Simulation-wide context for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from random import Random


@dataclass(slots=True)
class SimulationContext:
    """Authoritative simulation clock and deterministic random source."""

    simulation_start: datetime
    simulation_end: datetime
    seed: int
    model_version: str = "3.0.0"
    current_time: datetime | None = None
    run_id: int | None = None
    configuration_version: str = "v3-default"
    rng: Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.simulation_end <= self.simulation_start:
            raise ValueError("simulation_end must be after simulation_start")

        self.current_time = self.current_time or self.simulation_start

        if not (self.simulation_start <= self.current_time <= self.simulation_end):
            raise ValueError(
                "current_time must be within the simulation window"
            )

        self.rng = Random(self.seed)

    @property
    def finished(self) -> bool:
        return self.current_time >= self.simulation_end

    def now(self) -> datetime:
        """Return the authoritative simulation timestamp."""
        return self.current_time

    def advance(self, delta: timedelta) -> datetime:
        """Advance the simulation clock without passing simulation_end."""
        if delta <= timedelta(0):
            raise ValueError("delta must be positive")

        next_time = self.current_time + delta
        self.current_time = min(next_time, self.simulation_end)
        return self.current_time
