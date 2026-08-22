from datetime import datetime, timedelta, timezone

import pytest

from generators.supply_chain.lifecycle import (
    InvalidLifecycleTransition,
    arrive,
    deliver,
    depart,
    mark_ready,
)
from generators.supply_chain.models import (
    Priority,
    Shipment,
    ShipmentLifecycle,
)


def make_shipment() -> Shipment:
    departure = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    return Shipment(
        shipment_id=1,
        run_id=1,
        vehicle_id=1,
        route_id=1,
        origin_wh_id=1,
        dest_wh_id=2,
        cargo_type="GENERAL_FREIGHT",
        priority=Priority.STANDARD,
        scheduled_departure=departure,
        scheduled_arrival=departure + timedelta(hours=8),
        estimated_arrival=departure + timedelta(hours=8),
    )


def test_complete_normal_lifecycle() -> None:
    shipment = make_shipment()

    mark_ready(shipment, shipment.scheduled_departure - timedelta(minutes=30))
    assert shipment.lifecycle_status == ShipmentLifecycle.READY

    depart(shipment, shipment.scheduled_departure)
    assert shipment.lifecycle_status == ShipmentLifecycle.IN_TRANSIT
    assert shipment.actual_departure == shipment.scheduled_departure

    arrival = shipment.scheduled_departure + timedelta(hours=7, minutes=45)
    arrive(shipment, arrival)
    assert shipment.lifecycle_status == ShipmentLifecycle.ARRIVED
    assert shipment.actual_arrival == arrival
    assert shipment.route_progress_pct == 100.0

    completion = arrival + timedelta(minutes=20)
    deliver(shipment, completion)
    assert shipment.lifecycle_status == ShipmentLifecycle.DELIVERED
    assert shipment.delivery_completed_at == completion


def test_ready_cannot_skip_to_delivered() -> None:
    shipment = make_shipment()
    mark_ready(shipment, shipment.scheduled_departure)

    with pytest.raises(InvalidLifecycleTransition):
        deliver(shipment, shipment.scheduled_arrival)


def test_planned_cannot_depart_directly() -> None:
    shipment = make_shipment()

    with pytest.raises(InvalidLifecycleTransition):
        depart(shipment, shipment.scheduled_departure)


def test_arrival_requires_time_after_departure() -> None:
    shipment = make_shipment()
    mark_ready(shipment, shipment.scheduled_departure)
    depart(shipment, shipment.scheduled_departure)

    with pytest.raises(InvalidLifecycleTransition):
        arrive(shipment, shipment.scheduled_departure)


def test_delivery_cannot_precede_arrival() -> None:
    shipment = make_shipment()
    mark_ready(shipment, shipment.scheduled_departure)
    depart(shipment, shipment.scheduled_departure)

    arrival = shipment.scheduled_departure + timedelta(hours=8)
    arrive(shipment, arrival)

    with pytest.raises(InvalidLifecycleTransition):
        deliver(shipment, arrival - timedelta(minutes=1))


def test_actual_arrival_stays_null_while_in_transit() -> None:
    shipment = make_shipment()
    mark_ready(shipment, shipment.scheduled_departure)
    depart(shipment, shipment.scheduled_departure)

    assert shipment.lifecycle_status == ShipmentLifecycle.IN_TRANSIT
    assert shipment.actual_arrival is None
    assert shipment.delivery_completed_at is None
