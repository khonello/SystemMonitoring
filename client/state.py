"""Tamper-protected local state under %ProgramData%.

Holds the small amount of security-sensitive, low-volume state the agent must
survive a reboot with: the lockout schedule, and a cached policy snapshot for
when the Engine is briefly unreachable (README "Local State").

Deliberately not a database. It is read-mostly, has no relational structure,
and needs tamper protection far more than it needs queries.

Every value is stored with an HMAC over its contents. If that check fails the
caller is told, and the lockout code **fails closed** — a student who edits the
schedule file to end their block early gets a failed check, not an early
release.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

from client.config import STATE_DIR

logger = logging.getLogger(__name__)


class StateTampered(Exception):
    """A stored value failed its integrity check."""


# Embedded in the agent binary at build time. A file-local key would be
# pointless — anyone who can rewrite the state file could rewrite the key
# beside it. This is deliberately not strong protection: a determined user with
# physical access and a debugger can extract it. It raises the cost of casual
# tampering (editing a JSON file in Notepad), which is the stated goal.
_INTEGRITY_KEY: bytes = os.environ.get(
    "CLIENT_STATE_KEY", "phase4-development-key-replace-at-build"
).encode()

SCHEDULE_FILE = "lockout_schedule.json"
POLICY_FILE = "policy_cache.json"


def state_path(name: str) -> Path:
    return STATE_DIR / name


def ensure_state_dir() -> Path:
    """Create the state directory if absent.

    ACLs restricting write access to the agent's service account are applied by
    the installer, not here — the running agent should not be able to widen its
    own permissions. See client/install_service.py.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def _sign(payload: str) -> str:
    return hmac.new(_INTEGRITY_KEY, payload.encode("utf-8"), sha256).hexdigest()


def write_state(name: str, value: dict[str, Any]) -> None:
    """Store a value with an integrity tag.

    Written to a temporary file and moved into place, so an interrupted write
    cannot leave a half-written schedule that fails its own check and locks a
    machine indefinitely.
    """
    ensure_state_dir()

    payload = json.dumps(value, separators=(",", ":"), sort_keys=True)
    document = json.dumps({"payload": payload, "hmac": _sign(payload)})

    target = state_path(name)
    handle, temporary = tempfile.mkstemp(dir=str(STATE_DIR), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def read_state(name: str) -> dict[str, Any] | None:
    """Read a stored value.

    Returns:
        The value, or None if it has never been written.

    Raises:
        StateTampered: If the file exists but fails its integrity check.
            Callers must treat this as hostile, not as missing data.
    """
    target = state_path(name)
    if not target.exists():
        return None

    try:
        document = json.loads(target.read_text(encoding="utf-8"))
        payload = document["payload"]
        stored_hmac = document["hmac"]
    except (OSError, ValueError, KeyError) as exc:
        raise StateTampered(f"{name} is unreadable: {exc}") from exc

    if not hmac.compare_digest(_sign(payload), stored_hmac):
        raise StateTampered(f"{name} failed its integrity check")

    try:
        return json.loads(payload)
    except ValueError as exc:
        raise StateTampered(f"{name} payload is not valid JSON: {exc}") from exc


def clear_state(name: str) -> None:
    state_path(name).unlink(missing_ok=True)
