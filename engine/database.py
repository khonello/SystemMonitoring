"""Database interface — the only module in the project that speaks SQL.

Keeping every statement here is what makes the documented PostgreSQL upgrade
a rewrite of this file's internals rather than a hunt through the codebase
(README "Database").

PHASE 1 SCAFFOLD. `init_database` and the connection helper are real — the
schema needs to exist before anything can be written against it. The store and
query functions are present, typed and documented, but do nothing yet; Phase 2
fills in their bodies.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection, committing on success and closing always.

    Rows come back as sqlite3.Row so callers can use column names.
    """
    path = db_path if db_path is not None else DATABASE_PATH
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_database(db_path: Path | None = None) -> None:
    """Create the schema if it does not already exist. Idempotent."""
    path = db_path if db_path is not None else DATABASE_PATH
    with get_connection(path) as connection:
        connection.executescript(SCHEMA)
    logger.info("Database ready at %s", path)


# ---------------------------------------------------------------------------
# Writes — Phase 2
# ---------------------------------------------------------------------------


def store_client(
    client_id: str,
    hostname: str,
    ip_address: str,
    os_type: str,
) -> None:
    """Insert or update a client's registry row."""
    # TODO(Phase 2): INSERT ... ON CONFLICT(client_id) DO UPDATE.


def update_client_last_seen(client_id: str) -> None:
    """Refresh a client's last_seen timestamp."""
    # TODO(Phase 2)


def store_app_data(client_id: str, apps: list[dict[str, Any]]) -> None:
    """Persist one APP_DATA batch."""
    # TODO(Phase 2): executemany over the batch rather than per-row inserts.


def store_network_data(client_id: str, data: dict[str, Any]) -> None:
    """Persist one NETWORK_DATA sample."""
    # TODO(Phase 2)


def store_usb_event(client_id: str, event: dict[str, Any]) -> None:
    """Persist one USB insertion/removal event."""
    # TODO(Phase 2)


def log_command(
    admin_id: str,
    client_id: str,
    command_id: str,
    command_type: str,
    command_data: str,
) -> None:
    """Record a dispatched command."""
    # TODO(Phase 2)


def update_command_status(command_id: str, status: str) -> None:
    """Update a previously logged command's outcome."""
    # TODO(Phase 2)


# ---------------------------------------------------------------------------
# Reads — Phase 2
# ---------------------------------------------------------------------------


def get_client(client_id: str) -> dict[str, Any] | None:
    """Fetch one client's registry row."""
    # TODO(Phase 2)
    return None


def get_all_clients() -> list[dict[str, Any]]:
    """Fetch every known client, connected or not."""
    # TODO(Phase 2)
    return []


def get_client_apps(client_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Most recent application records for a client."""
    # TODO(Phase 2)
    return []


def get_network_summary(client_id: str, hours: int = 24) -> dict[str, Any]:
    """Aggregate network usage for a client over a trailing window."""
    # TODO(Phase 2)
    return {"bytes_sent": 0, "bytes_received": 0, "samples": 0}


def get_usb_events(client_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Most recent USB events for a client."""
    # TODO(Phase 2)
    return []
