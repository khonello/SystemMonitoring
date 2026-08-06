"""Small helpers shared across components."""

from __future__ import annotations

import platform
import socket
from datetime import datetime, timezone
from uuid import uuid4


def utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with a trailing 'Z'.

    Millisecond precision, so messages emitted in the same second still sort
    deterministically.
    """
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def utc_now_ts() -> float:
    """Current UTC time as a POSIX timestamp, for last-seen bookkeeping."""
    return datetime.now(timezone.utc).timestamp()


def new_command_id() -> str:
    """Generate a unique command identifier.

    Every script execution keys its log file and its termination request off
    this, so collisions would cross-wire two runs (README "Script Execution
    Model").
    """
    return f"cmd_{uuid4().hex[:12]}"


def generate_client_id() -> str:
    """Derive a default client identifier from the host."""
    return f"{socket.gethostname()}-{platform.system()}"
