from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.engine import _advance_if_positive


def make_context() -> SimulationContext:
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    return SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(hours=2),
        seed=42,
    )


def test_zero_minutes_does_not_advance_or_raise() -> None:
    context = make_context()
    start = context.now()

    _advance_if_positive(context, minutes=0.0)

    assert context.now() == start


def test_zero_seconds_does_not_advance_or_raise() -> None:
    context = make_context()
    start = context.now()

    _advance_if_positive(context, seconds=0.0)

    assert context.now() == start


def test_positive_duration_advances_context() -> None:
    context = make_context()
    start = context.now()

    _advance_if_positive(context, minutes=15.0)

    assert context.now() == start + timedelta(minutes=15)


def test_negative_duration_rejected() -> None:
    context = make_context()

    with pytest.raises(ValueError):
        _advance_if_positive(context, minutes=-1.0)
