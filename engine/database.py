"""Database interface — the only module in the project that speaks SQL.

Keeping every statement here is what makes the documented PostgreSQL upgrade a
rewrite of this file's internals rather than a hunt through the codebase
(README "Database").

Timestamp convention
--------------------
Times are stored as ISO-8601 UTC strings with millisecond precision and a
trailing 'Z' (see common.utils.utc_now_iso). They are fixed-width, so
lexicographic comparison is chronological comparison and `WHERE timestamp >= ?`
works directly against a string bound parameter. The schema declares these
columns TIMESTAMP to match the README; SQLite gives that NUMERIC affinity,
fails to coerce the ISO string to a number, and stores it as TEXT — which is
what we want. test_engine.py covers the window queries that depend on this.

Concurrency
-----------
These functions are synchronous and are called directly from the Engine's
event loop. That is deliberate and measured, not an oversight: see
`scripts/bench_database.py` and the note in todo.md. Should write volume ever
justify it, the fix is to wrap calls in `asyncio.to_thread` at the call sites
in command_handler.py — no change here.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from common.utils import utc_now_iso
from engine.config import DATABASE_PATH

logger = logging.getLogger(__name__)


SCHEMA: str = """
CREATE TABLE IF NOT EXISTS clients (
    client_id   TEXT PRIMARY KEY,
    hostname    TEXT,
    ip_address  TEXT,
    os_type     TEXT,
    last_seen   TIMESTAMP,
    status      TEXT
);

CREATE TABLE IF NOT EXISTS app_logs (
    id           INTEGER PRIMARY KEY,
    client_id    TEXT,
    process_name TEXT,
    window_title TEXT,
    start_time   TIMESTAMP,
    end_time     TIMESTAMP,
    cpu_usage    REAL,
    memory_mb    REAL,
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

CREATE TABLE IF NOT EXISTS network_usage (
    id             INTEGER PRIMARY KEY,
    client_id      TEXT,
    timestamp      TIMESTAMP,
    bytes_sent     INTEGER,
    bytes_received INTEGER,
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

CREATE TABLE IF NOT EXISTS usb_events (
    id          INTEGER PRIMARY KEY,
    client_id   TEXT,
    device_name TEXT,
    event_type  TEXT,
    timestamp   TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

CREATE TABLE IF NOT EXISTS command_log (
    id           INTEGER PRIMARY KEY,
    admin_id     TEXT,
    client_id    TEXT,
    command_id   TEXT,
    command_type TEXT,
    command_data TEXT,
    timestamp    TIMESTAMP,
    status       TEXT
);

-- Every query in this project filters by client and orders by time.
CREATE INDEX IF NOT EXISTS idx_app_logs_client_time
    ON app_logs(client_id, start_time);
CREATE INDEX IF NOT EXISTS idx_network_client_time
    ON network_usage(client_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_usb_client_time
    ON usb_events(client_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_command_log_command_id
    ON command_log(command_id);
"""


# The active database file, and the single long-lived connection to it.
#
# One connection is reused rather than opened per call. Measured on this
# project's own benchmark, per-call open/close plus a fully-synchronous commit
# cost ~11-15ms per write; reusing the connection removes the setup half of
# that. All access happens on the Engine's single event-loop thread, so
# sqlite3's default check_same_thread=True is left on — it enforces exactly the
# invariant this design relies on.
_db_path: Path = DATABASE_PATH
_connection: sqlite3.Connection | None = None


def set_database_path(path: Path) -> None:
    """Point subsequent operations at `path`, closing any open connection."""
    global _db_path
    close_database()
    _db_path = Path(path)


def get_database_path() -> Path:
    return _db_path


def close_database() -> None:
    """Close the shared connection. Safe to call when none is open."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def _connect() -> sqlite3.Connection:
    """Return the shared connection, opening it on first use."""
    global _connection

    if _connection is None:
        _connection = sqlite3.connect(_db_path)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA foreign_keys = ON")
        # synchronous=NORMAL rather than the FULL default. This trades an fsync
        # per commit for the possibility of losing the last few transactions in
        # a power loss - it cannot corrupt the database. That trade is right
        # here: the data is monitoring telemetry sampled every 15-60 seconds, so
        # losing the newest samples costs nothing, while the fsync dominated
        # write latency (see scripts/bench_database.py).
        _connection.execute("PRAGMA synchronous = NORMAL")

        # WAL is deliberately NOT enabled: the Engine runs under WSL against a
        # /mnt/c DrvFs mount, where WAL's shared-memory requirement is
        # unreliable, and a single writer process gains little from it anyway.

    return _connection


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield the shared connection, committing on success.

    Rows come back as sqlite3.Row so callers can index by column name.

    Passing `db_path` retargets the module first, which closes any existing
    connection — intended for setup and tests, not per-call use.
    """
    if db_path is not None and Path(db_path) != _db_path:
        set_database_path(Path(db_path))

    connection = _connect()
    try:
        yield connection
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise


def init_database(db_path: Path | None = None) -> None:
    """Create the schema if absent. Idempotent."""
    with get_connection(db_path) as connection:
        connection.executescript(SCHEMA)
    logger.info("Database ready at %s", _db_path)


def _window_start(hours: int) -> str:
    """ISO timestamp `hours` in the past, for window queries."""
    started = datetime.now(timezone.utc) - timedelta(hours=hours)
    return started.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def store_client(
    client_id: str,
    hostname: str,
    ip_address: str,
    os_type: str,
    status: str = "active",
) -> None:
    """Insert or refresh a client's registry row."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO clients (client_id, hostname, ip_address, os_type,
                                 last_seen, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET
                hostname   = excluded.hostname,
                ip_address = excluded.ip_address,
                os_type    = excluded.os_type,
                last_seen  = excluded.last_seen,
                status     = excluded.status
            """,
            (client_id, hostname, ip_address, os_type, utc_now_iso(), status),
        )


def update_client_last_seen(client_id: str, status: str = "active") -> None:
    """Refresh a client's liveness columns. No-op for unknown clients."""
    with get_connection() as connection:
        connection.execute(
            "UPDATE clients SET last_seen = ?, status = ? WHERE client_id = ?",
            (utc_now_iso(), status, client_id),
        )


def mark_client_offline(client_id: str) -> None:
    """Record that a client disconnected."""
    with get_connection() as connection:
        connection.execute(
            "UPDATE clients SET status = 'offline' WHERE client_id = ?",
            (client_id,),
        )


def get_client(client_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM clients WHERE client_id = ?", (client_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def get_all_clients() -> list[dict[str, Any]]:
    """Every client ever seen, connected or not."""
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM clients ORDER BY client_id"
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Monitoring data
# ---------------------------------------------------------------------------


def store_app_data(client_id: str, apps: list[dict[str, Any]]) -> int:
    """Persist one APP_DATA batch. Returns the number of rows written.

    One executemany rather than a statement per process: a batch can carry
    a hundred-plus entries every 30 seconds per client.
    """
    if not apps:
        return 0

    rows = [
        (
            client_id,
            app.get("process_name"),
            app.get("window_title"),
            app.get("start_time"),
            app.get("cpu_percent"),
            app.get("memory_mb"),
        )
        for app in apps
    ]

    with get_connection() as connection:
        connection.executemany(
            """
            INSERT INTO app_logs (client_id, process_name, window_title,
                                  start_time, cpu_usage, memory_mb)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def store_network_data(client_id: str, data: dict[str, Any]) -> None:
    """Persist one NETWORK_DATA sample.

    Counters arrive cumulative since the client booted. Samples are stored
    as received; differencing happens at query time in get_network_summary.
    """
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO network_usage (client_id, timestamp, bytes_sent,
                                       bytes_received)
            VALUES (?, ?, ?, ?)
            """,
            (
                client_id,
                utc_now_iso(),
                data.get("bytes_sent", 0),
                data.get("bytes_received", 0),
            ),
        )


def store_usb_event(client_id: str, event: dict[str, Any]) -> None:
    """Persist one USB event."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO usb_events (client_id, device_name, event_type, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (
                client_id,
                event.get("device_name"),
                event.get("event"),
                utc_now_iso(),
            ),
        )


# ---------------------------------------------------------------------------
# Command audit trail
# ---------------------------------------------------------------------------


def log_command(
    admin_id: str | None,
    client_id: str,
    command_id: str,
    command_type: str,
    command_data: dict[str, Any] | None = None,
) -> None:
    """Record a dispatched command (README "Access Control": log all admin
    actions)."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO command_log (admin_id, client_id, command_id,
                                     command_type, command_data, timestamp,
                                     status)
            VALUES (?, ?, ?, ?, ?, ?, 'dispatched')
            """,
            (
                admin_id,
                client_id,
                command_id,
                command_type,
                json.dumps(command_data or {}, separators=(",", ":")),
                utc_now_iso(),
            ),
        )


def update_command_status(command_id: str, status: str) -> None:
    """Update a dispatched command's outcome."""
    with get_connection() as connection:
        connection.execute(
            "UPDATE command_log SET status = ? WHERE command_id = ?",
            (status, command_id),
        )


def get_command_history(client_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Recent commands, newest first, optionally for one client."""
    with get_connection() as connection:
        if client_id is None:
            rows = connection.execute(
                "SELECT * FROM command_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM command_log WHERE client_id = ? ORDER BY id DESC LIMIT ?",
                (client_id, limit),
            ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Queries and aggregation
# ---------------------------------------------------------------------------


def get_client_apps(client_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Most recent application records for a client, newest first."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM app_logs
            WHERE client_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_app_usage_summary(client_id: str, hours: int = 24) -> list[dict[str, Any]]:
    """Per-application totals over a trailing window, busiest first."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT process_name,
                   COUNT(*)        AS samples,
                   AVG(cpu_usage)  AS avg_cpu,
                   MAX(cpu_usage)  AS peak_cpu,
                   AVG(memory_mb)  AS avg_memory_mb,
                   MAX(memory_mb)  AS peak_memory_mb,
                   MIN(start_time) AS first_seen
            FROM app_logs
            WHERE client_id = ? AND start_time >= ?
            GROUP BY process_name
            ORDER BY samples DESC
            """,
            (client_id, _window_start(hours)),
        ).fetchall()
    return [dict(row) for row in rows]


# Counters are cumulative since boot, so usage is the sum of positive deltas
# between consecutive samples. Negative deltas mean the client rebooted and its
# counters reset; those are skipped rather than counted as huge negative usage.
_DELTA_SUM = """
    COALESCE(SUM(CASE WHEN prev_sent IS NOT NULL AND bytes_sent >= prev_sent
                      THEN bytes_sent - prev_sent ELSE 0 END), 0) AS bytes_sent,
    COALESCE(SUM(CASE WHEN prev_recv IS NOT NULL AND bytes_received >= prev_recv
                      THEN bytes_received - prev_recv ELSE 0 END), 0) AS bytes_received
"""


def get_network_summary(client_id: str, hours: int = 24) -> dict[str, Any]:
    """Network usage for a client over a trailing window."""
    with get_connection() as connection:
        row = connection.execute(
            f"""
            WITH ordered AS (
                SELECT timestamp, bytes_sent, bytes_received,
                       LAG(bytes_sent)     OVER (ORDER BY timestamp) AS prev_sent,
                       LAG(bytes_received) OVER (ORDER BY timestamp) AS prev_recv
                FROM network_usage
                WHERE client_id = ? AND timestamp >= ?
            )
            SELECT {_DELTA_SUM}, COUNT(*) AS samples FROM ordered
            """,
            (client_id, _window_start(hours)),
        ).fetchone()

    return {
        "client_id": client_id,
        "hours": hours,
        "bytes_sent": row["bytes_sent"],
        "bytes_received": row["bytes_received"],
        "samples": row["samples"],
    }


def get_weekly_network_summary(client_id: str) -> list[dict[str, Any]]:
    """Per-day network usage for the last 7 days, oldest first.

    Days are bucketed by the date prefix of the ISO timestamp, and deltas are
    computed within each day so a bucket never absorbs the previous day's
    cumulative total.
    """
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            WITH ordered AS (
                SELECT substr(timestamp, 1, 10) AS day,
                       timestamp, bytes_sent, bytes_received,
                       LAG(bytes_sent) OVER (
                           PARTITION BY substr(timestamp, 1, 10) ORDER BY timestamp
                       ) AS prev_sent,
                       LAG(bytes_received) OVER (
                           PARTITION BY substr(timestamp, 1, 10) ORDER BY timestamp
                       ) AS prev_recv
                FROM network_usage
                WHERE client_id = ? AND timestamp >= ?
            )
            SELECT day, {_DELTA_SUM}, COUNT(*) AS samples
            FROM ordered
            GROUP BY day
            ORDER BY day
            """,
            (client_id, _window_start(24 * 7)),
        ).fetchall()
    return [dict(row) for row in rows]


def prune_older_than(days: int) -> dict[str, int]:
    """Delete monitoring rows older than `days`. Returns rows removed per table.

    Needed because app_logs grows fast: a client reporting ~80 processes every
    30 seconds writes roughly 230,000 rows a day, so the design ceiling of 50
    clients produces on the order of 11 million rows a day. Nothing calls this
    automatically yet — retention period and schedule are a deployment
    decision, so it is exposed and left to be wired up.
    """
    cutoff = _window_start(days * 24)
    removed: dict[str, int] = {}

    with get_connection() as connection:
        for table, column in (
            ("app_logs", "start_time"),
            ("network_usage", "timestamp"),
            ("usb_events", "timestamp"),
            ("command_log", "timestamp"),
        ):
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE {column} < ?", (cutoff,)  # noqa: S608
            )
            removed[table] = cursor.rowcount

    logger.info("Pruned rows older than %d days: %s", days, removed)
    return removed


def get_usb_events(client_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Most recent USB events for a client, newest first."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM usb_events
            WHERE client_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]
