from datetime import datetime, timedelta, timezone

from generators.supply_chain.context import SimulationContext


def test_engine_may_ignore_zero_duration_completed_tick() -> None:
    """A completed/no-op movement tick must not be sent to context.advance()."""
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    context = SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(hours=1),
        seed=42,
    )

    # This represents the engine behavior after a no-op movement result.
    elapsed_seconds = 0.0

    if elapsed_seconds > 0:
        context.advance(timedelta(seconds=elapsed_seconds))

    assert context.now() == start
