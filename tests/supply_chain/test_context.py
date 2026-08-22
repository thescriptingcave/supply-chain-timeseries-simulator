from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.context import SimulationContext


def test_context_uses_seeded_randomness() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=2)

    a = SimulationContext(start, end, seed=42)
    b = SimulationContext(start, end, seed=42)

    assert a.rng.random() == b.rng.random()


def test_context_advances_without_passing_end() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    context = SimulationContext(start, end, seed=42)

    context.advance(timedelta(hours=2))

    assert context.now() == end
    assert context.finished is True


def test_context_rejects_invalid_window() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        SimulationContext(start, start, seed=42)
