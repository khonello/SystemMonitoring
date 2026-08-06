#!/usr/bin/env python3
"""Measure SQLite write cost, to decide whether the Engine needs a thread.

    python -m scripts.bench_database

README "Concurrency Model" says SQLite writes are the only Engine work that
might justify `run_in_executor`, and only "if they start to stack up under
load". This measures whether they do, rather than guessing.

Every write here runs on the event loop thread in production, so the number
that matters is: how much of each second does the loop spend blocked, at the
design ceiling of 50 clients?
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

from common.constants import APP_DATA_INTERVAL, HEARTBEAT_INTERVAL, NETWORK_DATA_INTERVAL
from engine import database

CLIENTS = 50
APPS_PER_BATCH = 80
ROUNDS = 200


def _sample_apps(count: int) -> list[dict]:
    return [
        {
            "process_name": f"process_{i}.exe",
            "window_title": f"Window title for process {i}",
            "start_time": "2026-08-06T00:00:00.000Z",
            "cpu_percent": 1.5,
            "memory_mb": 128.0,
        }
        for i in range(count)
    ]


def _time_it(label: str, fn, rounds: int = ROUNDS) -> float:
    """Run fn `rounds` times, report milliseconds per call, return the mean."""
    timings = []
    for _ in range(rounds):
        started = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - started) * 1000)

    mean = statistics.mean(timings)
    median = statistics.median(timings)
    p95 = sorted(timings)[int(len(timings) * 0.95) - 1]
    print(f"  {label:<28} mean {mean:6.3f}ms   median {median:6.3f}ms   p95 {p95:6.3f}ms")
    return mean


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        database.set_database_path(Path(tmp) / "bench.db")
        database.init_database()
        database.store_client("bench-01", "bench-host", "127.0.0.1", "Linux")

        apps = _sample_apps(APPS_PER_BATCH)

        print(f"\nWrite cost ({ROUNDS} rounds each)")
        heartbeat_ms = _time_it(
            "update_client_last_seen", lambda: database.update_client_last_seen("bench-01")
        )
        network_ms = _time_it(
            "store_network_data",
            lambda: database.store_network_data(
                "bench-01", {"bytes_sent": 1000, "bytes_received": 2000}
            ),
        )
        app_ms = _time_it(
            f"store_app_data ({APPS_PER_BATCH} rows)",
            lambda: database.store_app_data("bench-01", apps),
        )

        print(f"\nRead cost")
        _time_it("get_network_summary (24h)",
                 lambda: database.get_network_summary("bench-01"), rounds=50)
        _time_it("get_weekly_network_summary",
                 lambda: database.get_weekly_network_summary("bench-01"), rounds=50)
        _time_it("get_app_usage_summary (24h)",
                 lambda: database.get_app_usage_summary("bench-01"), rounds=50)

        # Each client sends heartbeats, app batches and network samples on its
        # own interval. Sum the per-second cost across all of them.
        per_second_ms = CLIENTS * (
            heartbeat_ms / HEARTBEAT_INTERVAL
            + app_ms / APP_DATA_INTERVAL
            + network_ms / NETWORK_DATA_INTERVAL
        )
        duty = per_second_ms / 1000 * 100

        print(f"\nProjected load at {CLIENTS} clients")
        print(f"  event loop blocked on writes   {per_second_ms:.1f}ms per second")
        print(f"  duty cycle                     {duty:.2f}%")
        print()

        if duty < 5:
            print("VERDICT: keep writes synchronous on the event loop.")
            print("         A thread would add complexity for no measurable gain.")
        elif duty < 20:
            print("VERDICT: synchronous is still workable, but re-measure if")
            print("         client count or collection frequency grows.")
        else:
            print("VERDICT: move writes to asyncio.to_thread at the call sites")
            print("         in engine/command_handler.py.")

        # The shared connection holds the file open; Windows refuses to delete
        # the temp directory underneath it.
        database.close_database()

    return 0


if __name__ == "__main__":
    sys.exit(main())
