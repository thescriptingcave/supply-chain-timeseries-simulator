import pytest

from generators.supply_chain.models import (
    Priority,
    Shipment,
    ShipmentLifecycle,
    VehicleAvailability,
    VehicleProfile,
    VehicleState,
)
from generators.supply_chain.telemetry import (
    derive_engine_rpm,
    derive_geofence_zone,
    make_fleet_telemetry_row,
)


def make_vehicle(
    *,
    lat: float = 0.0,
    lon: float = 0.0,
    speed: float = 0.0,
    fuel: float = 80.0,
) -> VehicleState:
    profile = VehicleProfile(
        vehicle_id=1,
        vehicle_reg="TEST-1",
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
        lat=lat,
        lon=lon,
        speed_kmh=speed,
        fuel_level_pct=fuel,
        odometer_km=1234.5,
        availability=VehicleAvailability.IN_TRANSIT,
        active_shipment_id=10,
    )


def make_shipment() -> Shipment:
    from datetime import datetime, timedelta, timezone

    departure = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    return Shipment(
        shipment_id=10,
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
        lifecycle_status=ShipmentLifecycle.IN_TRANSIT,
        actual_departure=departure,
    )


def test_geofence_prefers_fuel_stop() -> None:
    assert derive_geofence_zone(
        at_origin=True,
        at_destination=False,
        speed_kmh=0.0,
        at_fuel_stop=True,
    ) == "FUEL_STOP"


def test_geofence_detects_highway() -> None:
    assert derive_geofence_zone(
        at_origin=False,
        at_destination=False,
        speed_kmh=80.0,
    ) == "HIGHWAY"


def test_geofence_detects_urban() -> None:
    assert derive_geofence_zone(
        at_origin=False,
        at_destination=False,
        speed_kmh=30.0,
    ) == "URBAN"


def test_engine_rpm_derives_from_speed() -> None:
    assert derive_engine_rpm(0.0) == 700
    assert derive_engine_rpm(50.0) > 700


def test_telemetry_reflects_vehicle_state() -> None:
    vehicle = make_vehicle(lat=5.0, lon=10.0, speed=80.0, fuel=65.0)

    row = make_fleet_telemetry_row(
        vehicle=vehicle,
        shipment=make_shipment(),
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=20.0,
    )

    assert row.vehicle_id == 1
    assert row.shipment_id == 10
    assert row.lat == pytest.approx(5.0)
    assert row.lon == pytest.approx(10.0)
    assert row.speed_kmh == pytest.approx(80.0)
    assert row.fuel_level_pct == pytest.approx(65.0)
    assert row.odometer_km == pytest.approx(1234.5)
    assert row.geofence_zone == "HIGHWAY"


def test_telemetry_detects_origin_warehouse() -> None:
    vehicle = make_vehicle(lat=0.0, lon=0.0, speed=0.0)

    row = make_fleet_telemetry_row(
        vehicle=vehicle,
        shipment=make_shipment(),
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=20.0,
    )

    assert row.geofence_zone == "ORIGIN_WAREHOUSE"


def test_telemetry_detects_destination_warehouse() -> None:
    vehicle = make_vehicle(lat=10.0, lon=20.0, speed=0.0)

    row = make_fleet_telemetry_row(
        vehicle=vehicle,
        shipment=make_shipment(),
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=20.0,
    )

    assert row.geofence_zone == "DESTINATION_WAREHOUSE"


def test_stationary_vehicle_cannot_have_harsh_event() -> None:
    vehicle = make_vehicle(speed=0.0)

    with pytest.raises(ValueError):
        make_fleet_telemetry_row(
            vehicle=vehicle,
            shipment=make_shipment(),
            origin_lat=0.0,
            origin_lon=0.0,
            destination_lat=10.0,
            destination_lon=20.0,
            harsh_braking=True,
        )


def test_telemetry_without_active_shipment_has_null_shipment() -> None:
    vehicle = make_vehicle(speed=0.0)

    row = make_fleet_telemetry_row(
        vehicle=vehicle,
        shipment=None,
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=20.0,
    )

    assert row.shipment_id is None
