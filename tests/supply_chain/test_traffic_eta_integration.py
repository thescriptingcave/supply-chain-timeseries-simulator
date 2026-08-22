from datetime import timedelta

from generators.supply_chain.disruptions import traffic_disruption
from tests.supply_chain.test_concurrent_disruptions import (
    cargo,
    ctx,
    route,
    vehicle,
    warehouse,
)
from generators.supply_chain.concurrent_disruptions import (
    DisruptedShipmentPlan,
    run_disruption_aware_fleet,
)


def test_one_hour_traffic_disruption_does_not_create_day_scale_eta_spike() -> None:
    context = ctx()

    result = run_disruption_aware_fleet(
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
        disruptions=[
            traffic_disruption(
                disruption_id="T1",
                start_time=context.now() + timedelta(minutes=20),
                duration_minutes=40,
                speed_factor=0.5,
                route_id=1,
            )
        ],
        movement_interval_seconds=600.0,
        base_consumption_pct_per_100km=1.0,
        eta_event_threshold_min=1.0,
    )

    traffic_eta_events = [
        event
        for event in result.shipments[0].events
        if event.event_type == "ETA_UPDATED"
        and event.cause_code == "TRAFFIC_CONGESTION"
    ]

    assert traffic_eta_events
    assert max(
        event.detail["delta_minutes"]
        for event in traffic_eta_events
    ) < 120.0
