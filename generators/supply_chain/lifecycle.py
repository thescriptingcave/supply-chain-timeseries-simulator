"""Shipment lifecycle rules for Supply Chain Generator v3."""

from __future__ import annotations

from datetime import datetime

from .models import Shipment, ShipmentLifecycle


class InvalidLifecycleTransition(ValueError):
    """Raised when a shipment attempts an invalid lifecycle transition."""


_VALID_TRANSITIONS: dict[ShipmentLifecycle, ShipmentLifecycle] = {
    ShipmentLifecycle.PLANNED: ShipmentLifecycle.READY,
    ShipmentLifecycle.READY: ShipmentLifecycle.IN_TRANSIT,
    ShipmentLifecycle.IN_TRANSIT: ShipmentLifecycle.ARRIVED,
    ShipmentLifecycle.ARRIVED: ShipmentLifecycle.DELIVERED,
}


def _require_transition(
    shipment: Shipment,
    target: ShipmentLifecycle,
) -> None:
    expected = _VALID_TRANSITIONS.get(shipment.lifecycle_status)

    if expected != target:
        raise InvalidLifecycleTransition(
            f"Cannot transition shipment from "
            f"{shipment.lifecycle_status.value} to {target.value}"
        )


def mark_ready(shipment: Shipment, at: datetime) -> None:
    """Transition PLANNED -> READY."""
    _require_transition(shipment, ShipmentLifecycle.READY)

    if at > shipment.scheduled_departure:
        # READY may occur after schedule because of upstream operational delay.
        # The lifecycle transition itself remains valid.
        pass

    shipment.lifecycle_status = ShipmentLifecycle.READY
    shipment.validate_temporal_integrity()


def depart(shipment: Shipment, at: datetime) -> None:
    """Transition READY -> IN_TRANSIT and record actual departure."""
    _require_transition(shipment, ShipmentLifecycle.IN_TRANSIT)

    if shipment.actual_departure is not None:
        raise InvalidLifecycleTransition("actual_departure is already populated")

    shipment.actual_departure = at
    shipment.lifecycle_status = ShipmentLifecycle.IN_TRANSIT
    shipment.validate_temporal_integrity()


def arrive(shipment: Shipment, at: datetime) -> None:
    """Transition IN_TRANSIT -> ARRIVED and record physical arrival."""
    _require_transition(shipment, ShipmentLifecycle.ARRIVED)

    if shipment.actual_departure is None:
        raise InvalidLifecycleTransition(
            "Shipment cannot arrive without actual_departure"
        )

    if at <= shipment.actual_departure:
        raise InvalidLifecycleTransition(
            "Arrival time must be after actual_departure"
        )

    shipment.actual_arrival = at
    shipment.lifecycle_status = ShipmentLifecycle.ARRIVED
    shipment.route_progress_pct = 100.0
    shipment.validate_temporal_integrity()


def deliver(shipment: Shipment, at: datetime) -> None:
    """Transition ARRIVED -> DELIVERED and record delivery completion."""
    _require_transition(shipment, ShipmentLifecycle.DELIVERED)

    if shipment.actual_arrival is None:
        raise InvalidLifecycleTransition(
            "Shipment cannot be delivered without actual_arrival"
        )

    if at < shipment.actual_arrival:
        raise InvalidLifecycleTransition(
            "Delivery completion cannot precede actual_arrival"
        )

    shipment.delivery_completed_at = at
    shipment.lifecycle_status = ShipmentLifecycle.DELIVERED
    shipment.validate_temporal_integrity()
