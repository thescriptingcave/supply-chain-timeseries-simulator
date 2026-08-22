from datetime import datetime, timedelta, timezone

from generators.supply_chain.cargo_exceptions import ReeferTemperaturePolicy
from generators.supply_chain.context import SimulationContext
from generators.supply_chain.models import (
    CargoProfile,
    RouteProfile,
    VehicleProfile,
    VehicleState,
    WarehouseProfile,
    WarehouseState,
)
from generators.supply_chain.reefer_exception_engine import (
    ReeferShipmentPlan,
    TemperatureExcursion,
    run_reefer_exception_shipment,
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


def vehicle() -> VehicleState:
    return VehicleState(
        profile=VehicleProfile(
            vehicle_id=1,
            vehicle_reg="REEFER-1",
            vehicle_type="REEFER",
            max_payload_kg=10000,
            fuel_type="DIESEL",
            fleet_operator="TEST",
            year_manufactured=2022,
            fuel_efficiency_factor=1.0,
            reliability_factor=1.0,
            condition_factor=1.0,
            cruise_speed_factor=1.0,
            maintenance_risk_factor=1.0,
            reefer_capable=True,
        ),
        current_warehouse_id=1,
        lat=1.0,
        lon=2.0,
        fuel_level_pct=95.0,
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
        cargo_type="REFRIGERATED",
        requires_reefer=True,
        target_temp_c=5.0,
        min_temp_c=2.0,
        max_temp_c=8.0,
        target_humidity_pct=60.0,
        handling_sensitivity=1.0,
        loading_time_factor=1.0,
    )


def run_case():
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

    return run_reefer_exception_shipment(
        context=SimulationContext(
            simulation_start=start,
            simulation_end=start + timedelta(days=1),
            seed=42,
            run_id=1,
        ),
        plan=ReeferShipmentPlan(
            shipment_id=1,
            vehicle_id=1,
            route=route(),
            cargo=cargo(),
        ),
        vehicle=vehicle(),
        origin=warehouse(1),
        destination=warehouse(2),
        policy=ReeferTemperaturePolicy(
            min_temp_c=2.0,
            max_temp_c=8.0,
            recovery_temp_c=5.0,
        ),
        excursion=TemperatureExcursion(
            start_time=start + timedelta(minutes=20),
            end_time=start + timedelta(minutes=60),
            excursion_temp_c=12.0,
        ),
        normal_cargo_temp_c=5.0,
        movement_interval_seconds=600.0,
    )


def test_reefer_exception_events_are_emitted() -> None:
    result = run_case()

    assert any(
        e.event_type == "CARGO_EXCEPTION_STARTED"
        and e.cause_code == "REEFER_TEMP_EXCURSION"
        for e in result.events
    )
    assert any(
        e.event_type == "CARGO_EXCEPTION_ENDED"
        and e.cause_code == "REEFER_TEMP_EXCURSION"
        for e in result.events
    )


def test_telemetry_contains_temperature_excursion() -> None:
    result = run_case()

    assert any(
        sample.row.cargo_temp_c > 8.0
        for sample in result.telemetry_samples
    )


def test_reefer_exception_does_not_stop_vehicle() -> None:
    result = run_case()

    excursion_samples = [
        sample
        for sample in result.telemetry_samples
        if sample.row.cargo_temp_c > 8.0
    ]

    assert excursion_samples
    assert all(sample.row.speed_kmh > 0 for sample in excursion_samples)


def test_temperature_recovers_after_excursion() -> None:
    result = run_case()

    assert result.telemetry_samples[-1].row.cargo_temp_c == 5.0
