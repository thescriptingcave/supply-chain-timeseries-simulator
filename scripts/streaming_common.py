"""Shared helpers for live IoT streamers."""

from __future__ import annotations

import os
import signal

import psycopg2
from psycopg2.extras import execute_values


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://supply_chain:supply_chain_dev@localhost:5432/supply_chain",
)


class ShutdownFlag:
    def __init__(self) -> None:
        self.running = True

    def install(self, label: str) -> None:
        def handler(sig, frame) -> None:
            del sig, frame
            print(f"\n[{label}] Shutting down gracefully...")
            self.running = False

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)


def connect():
    return psycopg2.connect(DB_URL)


def insert_rows(cur, table: str, rows: list[tuple]) -> None:
    if rows:
        execute_values(cur, f"INSERT INTO {table} VALUES %s", rows)
