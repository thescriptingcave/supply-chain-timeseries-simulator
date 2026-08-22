from datetime import datetime, timedelta, timezone

from generators.supply_chain.live_runtime import (
    LiveRuntimeState,
    LiveSupplyChainConfig,
    advance_next_shipment_time,
    should_start_shipment,
)


def test_live_config_validates() -> None:
    LiveSupplyChainConfig().validate()


def test_live_runtime_starts_when_wall_clock_reaches_next_shipment() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    state = LiveRuntimeState(
        rng=__import__("random").Random(42),
        next_shipment_at=now,
    )

    assert should_start_shipment(now=now, state=state)


def test_next_shipment_time_advances_by_configured_interval() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    state = LiveRuntimeState(
        rng=__import__("random").Random(42),
        next_shipment_at=now,
    )
    config = LiveSupplyChainConfig(
        shipment_interval_seconds=300,
    )

    advance_next_shipment_time(
        state=state,
        config=config,
    )

    assert state.next_shipment_at == now + timedelta(minutes=5)
