from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.engine import execute_single_shipment
from generators.supply_chain.models import (
    CargoProfile,
    RouteProfile,
    RouteState,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)


def test_actual_arrival_does_not_include_unused_final_tick_time() -> None:
    start = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    context = SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=1),
        seed=42,
    )

    route = RouteProfile(
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        distance_km=100.0,
        nominal_speed_kmh=60.0,
        minimum_speed_kmh=20.0,
        maximum_speed_kmh=100.0,
        baseline_travel_min=100.0,
        congestion_sensitivity=1.0,
        weather_sensitivity=1.0,
        morning_peak_factor=1.0,
        evening_peak_factor=1.0,
        overnight_factor=1.0,
        demand_weight=1.0,
        disruption_probability=0.0,
    )

    def warehouse(i, lat, lon):
        return WarehouseState(
            profile=WarehouseProfile(
                warehouse_id=i,
                warehouse_name=f"W{i}",
                lat=lat,
                lon=lon,
                timezone="UTC",
                loading_capacity=5,
                unloading_capacity=5,
                baseline_loading_min=0.0,
                baseline_unloading_min=0.0,
                congestion_sensitivity=1.0,
                cold_storage_capable=True,
            )
        )

    profile = VehicleProfile(
        vehicle_id=1,
        vehicle_reg="TEST",
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
    vehicle = VehicleState(
        profile=profile,
        current_warehouse_id=1,
        lat=0.0,
        lon=0.0,
        fuel_level_pct=100.0,
    )

    cargo = CargoProfile(
        cargo_type="GENERAL_FREIGHT",
        requires_reefer=False,
        target_temp_c=None,
        min_temp_c=None,
        max_temp_c=None,
        target_humidity_pct=None,
        handling_sensitivity=1.0,
        loading_time_factor=1.0,
    )

    result = execute_single_shipment(
        context=context,
        route=route,
        route_state=RouteState(profile=route),
        vehicles=[vehicle],
        origin_warehouse=warehouse(1, 0.0, 0.0),
        destination_warehouse=warehouse(2, 1.0, 1.0),
        cargo=cargo,
        movement_interval_seconds=3600.0,
        base_consumption_pct_per_100km=1.0,
    )

    # 100 km at 60 km/h = 100 minutes exactly.
    assert (
        result.shipment.actual_arrival - result.shipment.actual_departure
    ).total_seconds() / 60.0 == pytest.approx(100.0)
