from datetime import datetime, timedelta, timezone

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.disruptions import mechanical_disruption
from generators.supply_chain.mechanical_disruption import (
    MechanicalShipmentPlan,
    run_mechanical_disruption_shipment,
)
from generators.supply_chain.models import (
    CargoProfile,
    RouteProfile,
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


def vehicle() -> VehicleState:
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
        cargo_type="GENERAL_FREIGHT",
        requires_reefer=False,
        target_temp_c=None,
        min_temp_c=None,
        max_temp_c=None,
        target_humidity_pct=None,
        handling_sensitivity=1.0,
        loading_time_factor=1.0,
    )


def run_case():
    start = datetime(2026, 8, 18, 4, 3, 37, tzinfo=timezone.utc)
    context = SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=1),
        seed=42,
        run_id=13,
    )

    disruption_start = start + timedelta(minutes=30)
    disruption_end = disruption_start + timedelta(minutes=60)

    result = run_mechanical_disruption_shipment(
        context=context,
        plan=MechanicalShipmentPlan(
            shipment_id=23,
            vehicle_id=1,
            route=route(),
            cargo=cargo(),
        ),
        vehicle=vehicle(),
        origin=warehouse(1),
        destination=warehouse(2),
        disruption=mechanical_disruption(
            disruption_id="MECH-13-1",
            start_time=disruption_start,
            duration_minutes=60,
            vehicle_id=1,
        ),
        movement_interval_seconds=600.0,
    )

    return result, disruption_start, disruption_end


def test_no_duplicate_telemetry_timestamps_for_mechanical_run() -> None:
    result, _, _ = run_case()

    timestamps = [sample.time for sample in result.telemetry_samples]

    assert len(timestamps) == len(set(timestamps))


def test_breakdown_start_timestamp_has_one_stopped_row() -> None:
    result, disruption_start, _ = run_case()

    rows = [
        sample
        for sample in result.telemetry_samples
        if sample.time == disruption_start
    ]

    assert len(rows) == 1
    assert rows[0].row.speed_kmh == 0


def test_all_rows_inside_breakdown_window_are_stopped() -> None:
    result, disruption_start, disruption_end = run_case()

    rows = [
        sample
        for sample in result.telemetry_samples
        if disruption_start <= sample.time < disruption_end
    ]

    assert rows
    assert all(sample.row.speed_kmh == 0 for sample in rows)


def test_breakdown_window_does_not_change_odometer_or_fuel() -> None:
    result, disruption_start, disruption_end = run_case()

    rows = [
        sample
        for sample in result.telemetry_samples
        if disruption_start <= sample.time < disruption_end
    ]

    odometers = {sample.row.odometer_km for sample in rows}
    fuels = {sample.row.fuel_level_pct for sample in rows}

    assert len(odometers) == 1
    assert len(fuels) == 1
