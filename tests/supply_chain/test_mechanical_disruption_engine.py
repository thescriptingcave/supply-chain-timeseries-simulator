from datetime import datetime, timedelta, timezone

from generators.supply_chain.context import SimulationContext
from generators.supply_chain.disruptions import mechanical_disruption
from generators.supply_chain.mechanical_disruption import MechanicalShipmentPlan, run_mechanical_disruption_shipment
from generators.supply_chain.models import CargoProfile, RouteProfile, VehicleProfile, VehicleState, WarehouseProfile, WarehouseState


def wh(i):
    return WarehouseState(profile=WarehouseProfile(
        warehouse_id=i, warehouse_name=f"W{i}", lat=float(i), lon=float(i*2),
        timezone="UTC", loading_capacity=5, unloading_capacity=5,
        baseline_loading_min=0.0, baseline_unloading_min=0.0,
        congestion_sensitivity=1.0, cold_storage_capable=True,
    ))


def veh():
    return VehicleState(
        profile=VehicleProfile(
            vehicle_id=1, vehicle_reg="V1", vehicle_type="DRY_VAN",
            max_payload_kg=10000, fuel_type="DIESEL", fleet_operator="TEST",
            year_manufactured=2022, fuel_efficiency_factor=1.0,
            reliability_factor=1.0, condition_factor=1.0,
            cruise_speed_factor=1.0, maintenance_risk_factor=1.0,
            reefer_capable=False,
        ),
        current_warehouse_id=1, lat=1.0, lon=2.0,
        fuel_level_pct=95.0, odometer_km=1000.0,
    )


def rt():
    return RouteProfile(
        route_id=1, origin_wh_id=1, dest_wh_id=2, distance_km=120.0,
        nominal_speed_kmh=60.0, minimum_speed_kmh=20.0,
        maximum_speed_kmh=100.0, baseline_travel_min=120.0,
        congestion_sensitivity=1.0, weather_sensitivity=1.0,
        morning_peak_factor=1.0, evening_peak_factor=1.0,
        overnight_factor=1.0, demand_weight=1.0, disruption_probability=0.0,
    )


def cargo():
    return CargoProfile(
        cargo_type="GENERAL_FREIGHT", requires_reefer=False,
        target_temp_c=None, min_temp_c=None, max_temp_c=None,
        target_humidity_pct=None, handling_sensitivity=1.0,
        loading_time_factor=1.0,
    )


def run(start, offset_minutes):
    context = SimulationContext(
        simulation_start=start,
        simulation_end=start + timedelta(days=1),
        seed=42,
        run_id=1,
    )
    return run_mechanical_disruption_shipment(
        context=context,
        plan=MechanicalShipmentPlan(1, 1, rt(), cargo()),
        vehicle=veh(),
        origin=wh(1),
        destination=wh(2),
        disruption=mechanical_disruption(
            disruption_id="M1",
            start_time=start + timedelta(minutes=offset_minutes),
            duration_minutes=40,
            vehicle_id=1,
        ),
        movement_interval_seconds=600.0,
    )


def test_breakdown_emits_causal_events() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    result = run(start, 20)
    assert any(e.event_type == "DISRUPTION_STARTED" for e in result.events)
    assert any(e.event_type == "DISRUPTION_ENDED" for e in result.events)
    assert any(
        e.event_type == "ETA_UPDATED"
        and e.cause_code == "MECHANICAL_BREAKDOWN"
        for e in result.events
    )


def test_breakdown_generates_zero_speed_telemetry() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    result = run(start, 20)
    assert any(s.row.speed_kmh == 0 for s in result.telemetry_samples)


def test_breakdown_delays_arrival() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    broken = run(start, 20)
    baseline = run(start, 600)
    assert broken.shipment.actual_arrival > baseline.shipment.actual_arrival
