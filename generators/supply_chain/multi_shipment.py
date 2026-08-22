"""Sequential multi-shipment orchestration for Supply Chain Generator v3."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import DEFAULT_CONFIG, SimulationConfig
from .context import SimulationContext
from .engine import ShipmentExecutionResult, execute_single_shipment
from .models import (
    CargoProfile,
    Priority,
    RouteProfile,
    RouteState,
    VehicleState,
    WarehouseState,
)


@dataclass(slots=True)
class MultiShipmentResult:
    """Results from a sequential multi-shipment simulation."""

    shipments: list[ShipmentExecutionResult] = field(default_factory=list)

    @property
    def total_telemetry_rows(self) -> int:
        return sum(len(result.telemetry_samples) for result in self.shipments)

    @property
    def total_events(self) -> int:
        return sum(len(result.events) for result in self.shipments)


def choose_shortest_outbound_route(
    *,
    current_warehouse_id: int,
    routes: list[RouteProfile],
) -> RouteProfile:
    """Choose the shortest configured route leaving the current warehouse."""
    candidates = [
        route
        for route in routes
        if route.origin_wh_id == current_warehouse_id
    ]

    if not candidates:
        raise ValueError(
            f"no outbound route from warehouse {current_warehouse_id}"
        )

    return min(
        candidates,
        key=lambda route: (route.distance_km, route.route_id),
    )


def execute_sequential_shipments(
    *,
    context: SimulationContext,
    routes: list[RouteProfile],
    warehouses: dict[int, WarehouseState],
    vehicles: list[VehicleState],
    cargo: CargoProfile,
    shipment_ids: list[int],
    priority: Priority = Priority.STANDARD,
    config: SimulationConfig = DEFAULT_CONFIG,
    movement_interval_seconds: float = 600.0,
    base_consumption_pct_per_100km: float = 1.5,
) -> MultiShipmentResult:
    """Execute multiple shipments sequentially while preserving vehicle state.

    The current integration slice intentionally runs one shipment at a time.
    That lets us validate:
      - vehicle reuse,
      - location continuity,
      - fuel persistence,
      - odometer persistence,
      - route chaining,
      - non-overlap by construction.

    Concurrent scheduling/warehouse contention comes later.
    """
    if not shipment_ids:
        raise ValueError("shipment_ids cannot be empty")

    if not vehicles:
        raise ValueError("vehicles cannot be empty")

    result = MultiShipmentResult()

    for shipment_id in shipment_ids:
        eligible_at_any_origin = [
            vehicle
            for vehicle in vehicles
            if vehicle.current_warehouse_id is not None
        ]
        if not eligible_at_any_origin:
            raise ValueError("no vehicle is currently positioned at a warehouse")

        # Prefer the lowest vehicle_id for deterministic integration behavior.
        vehicle = min(
            eligible_at_any_origin,
            key=lambda state: state.profile.vehicle_id,
        )

        origin_id = vehicle.current_warehouse_id
        route = choose_shortest_outbound_route(
            current_warehouse_id=origin_id,
            routes=routes,
        )

        origin = warehouses[route.origin_wh_id]
        destination = warehouses[route.dest_wh_id]

        shipment_result = execute_single_shipment(
            context=context,
            route=route,
            route_state=RouteState(profile=route),
            vehicles=vehicles,
            origin_warehouse=origin,
            destination_warehouse=destination,
            cargo=cargo,
            priority=priority,
            shipment_id=shipment_id,
            config=config,
            movement_interval_seconds=movement_interval_seconds,
            base_consumption_pct_per_100km=base_consumption_pct_per_100km,
        )

        result.shipments.append(shipment_result)

    return result
