from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.disruptions import DisruptionType, mechanical_disruption


def test_mechanical_disruption_is_vehicle_scoped() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    d = mechanical_disruption(
        disruption_id="M1",
        start_time=start,
        duration_minutes=45,
        vehicle_id=7,
    )
    assert d.disruption_type == DisruptionType.MECHANICAL
    assert d.vehicle_id == 7
    assert d.cause_code == "MECHANICAL_BREAKDOWN"


def test_mechanical_window_closes() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    d = mechanical_disruption(
        disruption_id="M1",
        start_time=start,
        duration_minutes=45,
        vehicle_id=7,
    )
    assert d.is_active(start + timedelta(minutes=10))
    assert not d.is_active(start + timedelta(minutes=45))


def test_zero_duration_rejected() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        mechanical_disruption(
            disruption_id="M1",
            start_time=start,
            duration_minutes=0,
            vehicle_id=7,
        )
