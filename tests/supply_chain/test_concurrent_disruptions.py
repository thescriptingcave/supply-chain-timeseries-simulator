from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.disruptions import traffic_disruption
from generators.supply_chain.concurrent_disruptions import (
    DisruptedShipmentPlan,
    run_disruption_aware_fleet,
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


def vehicle(i: int, wh: int) -> VehicleState:
    return VehicleState(
        profile=VehicleProfile(
            vehicle_id=i,
            vehicle_reg=f"V{i}",
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
        current_warehouse_id=wh,
        lat=float(wh),
        lon=float(wh * 2),
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


def ctx() -> SimulationContext:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    return SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=1),
        seed=42,
        run_id=1,
    )


def run(*, with_disruption: bool):
    context = ctx()
    disruptions = []

    if with_disruption:
        disruptions.append(
            traffic_disruption(
                disruption_id="TRAFFIC-1",
                start_time=context.now() + timedelta(minutes=20),
                duration_minutes=40,
                speed_factor=0.5,
                route_id=1,
            )
        )

    return run_disruption_aware_fleet(
        context=context,
        plans=[
            DisruptedShipmentPlan(
                shipment_id=1,
                vehicle_id=1,
                route=route(),
                cargo=cargo(),
            )
        ],
        vehicles=[vehicle(1, 1)],
        warehouses={
            1: warehouse(1),
            2: warehouse(2),
        },
        disruptions=disruptions,
        movement_interval_seconds=600.0,
        base_consumption_pct_per_100km=1.0,
        eta_event_threshold_min=1.0,
    )


def test_traffic_disruption_delays_actual_arrival() -> None:
    baseline = run(with_disruption=False)
    disrupted = run(with_disruption=True)

    assert (
        disrupted.shipments[0].shipment.actual_arrival
        > baseline.shipments[0].shipment.actual_arrival
    )


def test_disruption_start_event_is_emitted() -> None:
    result = run(with_disruption=True)

    event_types = [
        event.event_type
        for event in result.shipments[0].events
    ]

    assert "DISRUPTION_STARTED" in event_types


def test_disruption_end_event_is_emitted() -> None:
    result = run(with_disruption=True)

    event_types = [
        event.event_type
        for event in result.shipments[0].events
    ]

    assert "DISRUPTION_ENDED" in event_types


def test_eta_update_carries_traffic_cause_code() -> None:
    result = run(with_disruption=True)

    eta_events = [
        event
        for event in result.shipments[0].events
        if event.event_type == "ETA_UPDATED"
        and event.cause_code == "TRAFFIC_CONGESTION"
    ]

    assert eta_events


def test_traffic_factor_is_restored_after_tick() -> None:
    result = run(with_disruption=True)

    assert result.shipments[0].route_state.traffic_factor == pytest.approx(1.0)


def test_disruption_does_not_break_telemetry_generation() -> None:
    result = run(with_disruption=True)

    assert result.telemetry_rows > 0
