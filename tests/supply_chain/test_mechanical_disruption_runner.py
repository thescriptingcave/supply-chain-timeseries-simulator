from datetime import datetime, timedelta, timezone

from generators.supply_chain.disruptions import mechanical_disruption


def test_integration_scenario_breakdown_window_is_deterministic() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    disruption = mechanical_disruption(
        disruption_id="MECH-TEST",
        start_time=start + timedelta(minutes=30),
        duration_minutes=60,
        vehicle_id=1,
    )

    assert disruption.start_time == start + timedelta(minutes=30)
    assert disruption.end_time == start + timedelta(minutes=90)
    assert disruption.vehicle_id == 1
    assert disruption.cause_code == "MECHANICAL_BREAKDOWN"
