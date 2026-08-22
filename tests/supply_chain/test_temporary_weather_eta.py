from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.eta import calculate_eta_with_temporary_weather
from generators.supply_chain.models import (
    Priority,
    RouteProfile,
    RouteState,
    Shipment,
    VehicleProfile,
)


def test_temporary_weather_only_affects_weather_window() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    route = RouteProfile(
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        distance_km=120.0,
        nominal_speed_kmh=60.0,
        minimum_speed_kmh=20.0,
        maximum_speed_kmh=100.0,
        baseline_travel_min=120.0,
        congestion_sensitivity=1.0,
        weather_sensitivity=1.0,
        morning_peak_factor=1.0,
        evening_peak_factor=1.0,
        overnight_factor=1.0,
        demand_weight=1.0,
        disruption_probability=0.0,
    )

    shipment = Shipment(
        shipment_id=1,
        run_id=1,
        vehicle_id=1,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=now,
        scheduled_arrival=now + timedelta(hours=3),
        estimated_arrival=now + timedelta(hours=3),
    )

    vehicle = VehicleProfile(
        vehicle_id=1,
        vehicle_reg="V1",
        vehicle_type="DRY_VAN",
        max_payload_kg=10000,
        fuel_type="DIESEL",
        fleet_operator="TEST",
        year_manufactured=2022,
        fuel_efficiency_factor=1.0,
        reliability_factor=1.0,
        condition_factor=1.0,
        cruise_speed_factor=1.0,
        maintenance_risk_factor=1.0,
        reefer_capable=False,
    )

    result = calculate_eta_with_temporary_weather(
        now=now,
        shipment=shipment,
        route_state=RouteState(
            profile=route,
            weather_factor=0.70,
        ),
        vehicle_profile=vehicle,
        disruption_end=now + timedelta(hours=1),
        normal_weather_factor=1.0,
    )

    # 42 km in one hour at 42 km/h, then 78 km at 60 km/h = 138 min total.
    assert result.remaining_travel_minutes == pytest.approx(138.0)
