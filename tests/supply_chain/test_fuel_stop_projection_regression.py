from datetime import datetime, timedelta, timezone

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.fuel_stop import FuelStopPolicy
from generators.supply_chain.fuel_stop_engine import (
    FuelStopShipmentPlan,
    _needs_refuel_before_next_tick,
    run_fuel_stop_shipment,
)
from generators.supply_chain.models import (
    CargoProfile,
    RouteProfile,
    RouteState,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)


def warehouse(i: int) -> WarehouseState:
    return WarehouseState(
        profile=WarehouseProfile(
            warehouse_id=i,
            warehouse_name=f"W{i}",
            lat=float(i),
            lon=float(i * 2),
            timezone="UTC",
            loading_capacity=5,
            unloading_capacity=5,
            baseline_loading_min=0.0,
            baseline_unloading_min=0.0,
            congestion_sensitivity=1.0,
            cold_storage_capable=True,
        )
    )


def vehicle(fuel_pct: float = 26.0) -> VehicleState:
    return VehicleState(
        profile=VehicleProfile(
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
        ),
        current_warehouse_id=1,
        lat=1.0,
        lon=2.0,
        fuel_level_pct=fuel_pct,
        odometer_km=1000.0,
    )


def route() -> RouteProfile:
    return RouteProfile(
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


def cargo() -> CargoProfile:
    return CargoProfile(
        cargo_type="GENERAL_FREIGHT",
        requires_reefer=False,
        target_temp_c=None,
        min_temp_c=None,
        max_temp_c=None,
        target_humidity_pct=None,
        handling_sensitivity=1.0,
        loading_time_factor=1.0,
    )


def policy() -> FuelStopPolicy:
    return FuelStopPolicy(
        trigger_pct=25.0,
        refuel_to_pct=90.0,
        stop_duration_minutes=20.0,
    )


def test_refuel_is_triggered_before_next_tick_crosses_threshold() -> None:
    v = vehicle(26.0)
    assert _needs_refuel_before_next_tick(
        vehicle=v,
        route_state=RouteState(profile=route()),
        policy=policy(),
        movement_interval_seconds=600.0,
        base_consumption_pct_per_100km=10.0,
    )


def test_integration_does_not_attempt_impossible_fuel_consumption() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    result = run_fuel_stop_shipment(
        context=SimulationContext(
            simulation_start=start,
            simulation_end=start + timedelta(days=1),
            seed=42,
            run_id=1,
        ),
        plan=FuelStopShipmentPlan(
            shipment_id=1,
            vehicle_id=1,
            route=route(),
            cargo=cargo(),
        ),
        vehicle=vehicle(26.0),
        origin=warehouse(1),
        destination=warehouse(2),
        policy=policy(),
        movement_interval_seconds=600.0,
        base_consumption_pct_per_100km=10.0,
        eta_event_threshold_min=1.0,
    )

    assert any(
        event.event_type == "FUEL_STOP_STARTED"
        for event in result.events
    )
    assert result.shipment.actual_arrival is not None
    assert result.vehicle.fuel_level_pct > 0


def test_refuel_still_occurs_only_once() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    result = run_fuel_stop_shipment(
        context=SimulationContext(
            simulation_start=start,
            simulation_end=start + timedelta(days=1),
            seed=42,
            run_id=1,
        ),
        plan=FuelStopShipmentPlan(
            shipment_id=1,
            vehicle_id=1,
            route=route(),
            cargo=cargo(),
        ),
        vehicle=vehicle(26.0),
        origin=warehouse(1),
        destination=warehouse(2),
        policy=policy(),
        movement_interval_seconds=600.0,
        base_consumption_pct_per_100km=10.0,
        eta_event_threshold_min=1.0,
    )

    starts = [
        event
        for event in result.events
        if event.event_type == "FUEL_STOP_STARTED"
    ]

    assert len(starts) == 1
