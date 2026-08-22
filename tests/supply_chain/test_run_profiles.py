from generators.supply_chain.run_config import (
    production_profile,
    validation_profile,
)


def test_validation_profile_has_higher_short_run_event_density() -> None:
    validation = validation_profile(days=2, seed=42)
    production = production_profile(days=2, seed=42)

    assert (
        validation.traffic_probability_per_shipment
        > production.traffic_probability_per_shipment
    )
    assert (
        validation.weather_probability_per_shipment
        > production.weather_probability_per_shipment
    )
    assert (
        validation.mechanical_probability_per_shipment
        > production.mechanical_probability_per_shipment
    )
    assert (
        validation.reefer_excursion_probability_per_shipment
        > production.reefer_excursion_probability_per_shipment
    )


def test_profiles_preserve_requested_days_and_seed() -> None:
    config = validation_profile(days=7, seed=99)

    assert config.simulation_days == 7
    assert config.seed == 99
