from datetime import datetime, timedelta, timezone

from generators.supply_chain.cargo_exceptions import (
    ReeferExceptionState,
    ReeferTemperaturePolicy,
    temperature_out_of_range,
    update_reefer_exception,
)


def policy() -> ReeferTemperaturePolicy:
    return ReeferTemperaturePolicy(
        min_temp_c=2.0,
        max_temp_c=8.0,
        recovery_temp_c=5.0,
    )


def test_temperature_excursion_detection() -> None:
    assert temperature_out_of_range(
        cargo_temp_c=10.0,
        policy=policy(),
    )
    assert not temperature_out_of_range(
        cargo_temp_c=5.0,
        policy=policy(),
    )


def test_exception_starts_and_ends() -> None:
    start = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    state = ReeferExceptionState()

    assert update_reefer_exception(
        now=start,
        cargo_temp_c=10.0,
        policy=policy(),
        state=state,
    ) == "CARGO_EXCEPTION_STARTED"

    assert update_reefer_exception(
        now=start + timedelta(minutes=10),
        cargo_temp_c=11.0,
        policy=policy(),
        state=state,
    ) is None

    assert update_reefer_exception(
        now=start + timedelta(minutes=20),
        cargo_temp_c=5.0,
        policy=policy(),
        state=state,
    ) == "CARGO_EXCEPTION_ENDED"

    assert state.peak_temp_c == 11.0
