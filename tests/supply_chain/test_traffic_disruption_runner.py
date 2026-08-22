from datetime import datetime, timedelta, timezone

from generators.supply_chain.disruptions import traffic_disruption


def test_integration_scenario_traffic_window_is_deterministic() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    disruption = traffic_disruption(
        disruption_id="TEST",
        start_time=start + timedelta(minutes=30),
        duration_minutes=60,
        speed_factor=0.5,
        route_id=1,
    )

    assert disruption.start_time == start + timedelta(minutes=30)
    assert disruption.end_time == start + timedelta(minutes=90)
    assert disruption.speed_factor == 0.5
    assert disruption.cause_code == "TRAFFIC_CONGESTION"
