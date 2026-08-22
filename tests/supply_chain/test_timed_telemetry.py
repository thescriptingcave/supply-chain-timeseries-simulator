from datetime import datetime, timedelta, timezone

from generators.supply_chain.telemetry import (
    FleetTelemetryRow,
    TimedFleetTelemetrySample,
)


def test_timed_sample_keeps_authoritative_time() -> None:
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    row = FleetTelemetryRow(
        vehicle_id=1,
        shipment_id=2,
        lat=1.0,
        lon=2.0,
        speed_kmh=60.0,
        heading_deg=90.0,
        engine_rpm=1980,
        fuel_level_pct=75.0,
        cargo_temp_c=None,
        cargo_humidity_pct=None,
        door_open=False,
        harsh_braking=False,
        harsh_acceleration=False,
        idle_time_sec=0,
        odometer_km=100.0,
        geofence_zone="HIGHWAY",
    )

    sample = TimedFleetTelemetrySample(time=now, row=row)

    assert sample.time == now
    assert sample.row.shipment_id == 2
