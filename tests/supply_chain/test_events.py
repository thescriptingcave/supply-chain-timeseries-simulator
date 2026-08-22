from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.events import (
    make_arrival_event,
    make_delivery_event,
    make_departure_event,
    maybe_make_eta_updated_event,
)
from generators.supply_chain.models import (
    Priority,
    Shipment,
    ShipmentLifecycle,
    VehicleProfile,
    VehicleState,
)


def make_shipment() -> Shipment:
    start = datetime(2026, 8, 17, 5, 0, tzinfo=timezone.utc)
    return Shipment(
        shipment_id=1,
        run_id=3,
        vehicle_id=1,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=start,
        scheduled_arrival=start + timedelta(hours=8),
        estimated_arrival=start + timedelta(hours=8),
        lifecycle_status=ShipmentLifecycle.IN_TRANSIT,
        actual_departure=start + timedelta(minutes=20),
    )


def make_vehicle() -> VehicleState:
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
    return VehicleState(
        profile=profile,
        current_warehouse_id=None,
        lat=10.0,
        lon=20.0,
    )


def test_departure_event_contains_core_context() -> None:
    shipment = make_shipment()
    vehicle = make_vehicle()
    event = make_departure_event(
        time=shipment.actual_departure,
        shipment=shipment,
        vehicle=vehicle,
    )

    assert event.event_type == "DEPARTURE"
    assert event.shipment_id == 1
    assert event.vehicle_id == 1
    assert event.route_id == 1
    assert event.run_id == 3


def test_arrival_event_contains_actual_arrival() -> None:
    shipment = make_shipment()
    vehicle = make_vehicle()
    arrival = shipment.scheduled_arrival - timedelta(minutes=5)
    shipment.actual_arrival = arrival
    event = make_arrival_event(
        time=arrival,
        shipment=shipment,
        vehicle=vehicle,
    )

    assert event.event_type == "ARRIVAL"
    assert event.detail["actual_arrival"] == arrival.isoformat()


def test_delivery_event_uses_delivery_timestamp() -> None:
    shipment = make_shipment()
    vehicle = make_vehicle()
    delivery = shipment.scheduled_arrival
    event = make_delivery_event(
        time=delivery,
        shipment=shipment,
        vehicle=vehicle,
    )

    assert event.event_type == "DELIVERY"
    assert event.detail["delivery_completed_at"] == delivery.isoformat()


def test_material_eta_change_emits_event() -> None:
    shipment = make_shipment()
    vehicle = make_vehicle()
    old = shipment.estimated_arrival
    new = old + timedelta(minutes=12)

    event = maybe_make_eta_updated_event(
        time=shipment.actual_departure,
        shipment=shipment,
        vehicle=vehicle,
        previous_eta=old,
        new_eta=new,
        threshold_minutes=5,
        cause_code="TRAFFIC_CONGESTION",
    )

    assert event is not None
    assert event.event_type == "ETA_UPDATED"
    assert event.cause_code == "TRAFFIC_CONGESTION"
    assert event.detail["delta_minutes"] == pytest.approx(12.0)
    assert event.severity == "WARNING"


def test_small_eta_change_does_not_emit_event() -> None:
    shipment = make_shipment()
    vehicle = make_vehicle()
    old = shipment.estimated_arrival
    new = old + timedelta(minutes=2)

    event = maybe_make_eta_updated_event(
        time=shipment.actual_departure,
        shipment=shipment,
        vehicle=vehicle,
        previous_eta=old,
        new_eta=new,
        threshold_minutes=5,
    )

    assert event is None
