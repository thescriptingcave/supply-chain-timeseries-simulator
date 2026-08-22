"""Supply Chain Generator v3 production planning gate.

Examples:

    uv run python -m scripts.generate_supply_chain_v3 --days 2 --profile validation
    uv run python -m scripts.generate_supply_chain_v3 --days 30 --profile production
"""

from __future__ import annotations

import argparse
import os
import random

import psycopg2

from generators.supply_chain.production_planner import (
    build_event_plan,
    planned_shipment_count,
)
from generators.supply_chain.run_config import (
    production_profile,
    validation_profile,
)


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan a Supply Chain v3 historical run."
    )
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--profile",
        choices=("validation", "production"),
        default="validation",
    )
    return parser.parse_args()


def load_reference_counts(conn) -> tuple[int, int, int, int, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sc_vehicles")
        vehicles = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM sc_warehouses")
        warehouses = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM sc_routes WHERE active = true")
        routes = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM sc_cargo_profiles WHERE active = true"
        )
        cargo_profiles = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*)
            FROM sc_cargo_profiles
            WHERE active = true
              AND requires_reefer = true
            """
        )
        reefer_profiles = cur.fetchone()[0]

    return vehicles, warehouses, routes, cargo_profiles, reefer_profiles


def main() -> None:
    args = parse_args()

    if args.profile == "validation":
        config = validation_profile(days=args.days, seed=args.seed)
    else:
        config = production_profile(days=args.days, seed=args.seed)

    config.validate()

    conn = psycopg2.connect(DB_URL)
    try:
        (
            vehicle_count,
            warehouse_count,
            route_count,
            cargo_profile_count,
            reefer_profile_count,
        ) = load_reference_counts(conn)
    finally:
        conn.close()

    if vehicle_count <= 0:
        raise RuntimeError("no supply-chain vehicles configured")
    if warehouse_count < 2:
        raise RuntimeError("at least two warehouses are required")
    if route_count <= 0:
        raise RuntimeError("no active routes configured")
    if cargo_profile_count <= 0:
        raise RuntimeError("no active cargo profiles configured")

    shipment_count = planned_shipment_count(
        vehicle_count=vehicle_count,
        config=config,
    )

    rng = random.Random(config.seed)

    event_totals = {
        "traffic": 0,
        "weather": 0,
        "mechanical": 0,
        "reefer_excursion": 0,
    }

    reefer_eligible_count = 0

    for shipment_index in range(shipment_count):
        # Until persisted cargo assignment is wired in, use the configured
        # cargo mix as a deterministic planning approximation.
        requires_reefer = (
            reefer_profile_count > 0
            and shipment_index % 4 == 0
        )
        reefer_eligible_count += int(requires_reefer)

        plan = build_event_plan(
            rng=rng,
            config=config,
            requires_reefer=requires_reefer,
        )

        event_totals["traffic"] += int(plan.traffic)
        event_totals["weather"] += int(plan.weather)
        event_totals["mechanical"] += int(plan.mechanical)
        event_totals["reefer_excursion"] += int(plan.reefer_excursion)

    print("[Supply Chain v3] Production planning gate passed")
    print(f"  profile:                  {args.profile}")
    print(f"  days:                     {config.simulation_days}")
    print(f"  seed:                     {config.seed}")
    print(f"  vehicles:                 {vehicle_count}")
    print(f"  warehouses:               {warehouse_count}")
    print(f"  active routes:            {route_count}")
    print(f"  cargo profiles:           {cargo_profile_count}")
    print(f"  reefer cargo profiles:    {reefer_profile_count}")
    print(f"  planned shipments:        {shipment_count}")
    print(f"  reefer-eligible shipments:{reefer_eligible_count}")
    print(f"  planned traffic events:   {event_totals['traffic']}")
    print(f"  planned weather events:   {event_totals['weather']}")
    print(f"  planned mechanical events:{event_totals['mechanical']}")
    print(f"  planned reefer events:    {event_totals['reefer_excursion']}")
    print()
    print("No rows were written.")


if __name__ == "__main__":
    main()
