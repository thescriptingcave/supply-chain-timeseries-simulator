from generators.supply_chain.disruptions import DisruptionType


def test_disruption_type_includes_reefer() -> None:
    assert DisruptionType.REEFER.value == "REEFER"


def test_existing_disruption_types_remain_available() -> None:
    assert DisruptionType.TRAFFIC.value == "TRAFFIC"
    assert DisruptionType.WEATHER.value == "WEATHER"
    assert DisruptionType.MECHANICAL.value == "MECHANICAL"
    assert DisruptionType.FUEL_STOP.value == "FUEL_STOP"
