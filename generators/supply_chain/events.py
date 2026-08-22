"""Operational event generation for Supply Chain Generator v3."""

from __future__ import annotations

from datetime import datetime

from .eta import eta_change_minutes, is_material_eta_change
from .models import OperationalEvent, Shipment, VehicleState


def make_departure_event(
    *,
    time: datetime,
    shipment: Shipment,
    vehicle: VehicleState,
) -> OperationalEvent:
    return OperationalEvent(
        event_id=f"DEP-{shipment.shipment_id}-{int(time.timestamp())}",
        time=time,
        event_type="DEPARTURE",
        shipment_id=shipment.shipment_id,
        vehicle_id=vehicle.profile.vehicle_id,
        route_id=shipment.route_id,
        run_id=shipment.run_id,
        severity="INFO",
        location_lat=vehicle.lat,
        location_lon=vehicle.lon,
        detail={
            "actual_departure": time.isoformat(),
            "scheduled_departure": shipment.scheduled_departure.isoformat(),
        },
    )


def make_arrival_event(
    *,
    time: datetime,
    shipment: Shipment,
    vehicle: VehicleState,
) -> OperationalEvent:
    return OperationalEvent(
        event_id=f"ARR-{shipment.shipment_id}-{int(time.timestamp())}",
        time=time,
        event_type="ARRIVAL",
        shipment_id=shipment.shipment_id,
        vehicle_id=vehicle.profile.vehicle_id,
        route_id=shipment.route_id,
        run_id=shipment.run_id,
        severity="INFO",
        location_lat=vehicle.lat,
        location_lon=vehicle.lon,
        detail={
            "actual_arrival": time.isoformat(),
            "scheduled_arrival": shipment.scheduled_arrival.isoformat(),
        },
    )


def make_delivery_event(
    *,
    time: datetime,
    shipment: Shipment,
    vehicle: VehicleState,
) -> OperationalEvent:
    return OperationalEvent(
        event_id=f"DEL-{shipment.shipment_id}-{int(time.timestamp())}",
        time=time,
        event_type="DELIVERY",
        shipment_id=shipment.shipment_id,
        vehicle_id=vehicle.profile.vehicle_id,
        route_id=shipment.route_id,
        run_id=shipment.run_id,
        severity="INFO",
        location_lat=vehicle.lat,
        location_lon=vehicle.lon,
        detail={
            "delivery_completed_at": time.isoformat(),
        },
    )


def maybe_make_eta_updated_event(
    *,
    time: datetime,
    shipment: Shipment,
    vehicle: VehicleState,
    previous_eta: datetime,
    new_eta: datetime,
    threshold_minutes: float,
    cause_code: str | None = None,
) -> OperationalEvent | None:
    if not is_material_eta_change(
        previous_eta,
        new_eta,
        threshold_minutes=threshold_minutes,
    ):
        return None

    delta = eta_change_minutes(previous_eta, new_eta)

    return OperationalEvent(
        event_id=f"ETA-{shipment.shipment_id}-{int(time.timestamp())}",
        time=time,
        event_type="ETA_UPDATED",
        shipment_id=shipment.shipment_id,
        vehicle_id=vehicle.profile.vehicle_id,
        route_id=shipment.route_id,
        run_id=shipment.run_id,
        severity="INFO" if delta <= 0 else "WARNING",
        cause_code=cause_code,
        location_lat=vehicle.lat,
        location_lon=vehicle.lon,
        detail={
            "previous_eta": previous_eta.isoformat(),
            "new_eta": new_eta.isoformat(),
            "delta_minutes": delta,
        },
    )
