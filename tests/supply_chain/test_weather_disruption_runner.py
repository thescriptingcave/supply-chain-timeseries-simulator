from datetime import datetime, timedelta, timezone

from generators.supply_chain.disruptions import weather_disruption


def test_integration_scenario_weather_window_is_deterministic() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    disruption = weather_disruption(
        disruption_id="RAIN-TEST",
        start_time=start + timedelta(minutes=30),
        duration_minutes=60,
        weather_factor=0.70,
        route_id=1,
        cause_code="HEAVY_RAIN",
    )

    assert disruption.start_time == start + timedelta(minutes=30)
    assert disruption.end_time == start + timedelta(minutes=90)
    assert disruption.speed_factor == 0.70
    assert disruption.cause_code == "HEAVY_RAIN"
