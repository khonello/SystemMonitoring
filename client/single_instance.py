"""One agent per client id, enforced locally before anything connects.

Two agents sharing a `CLIENT_ID` share a `STATE_DIR`, so they race on the same
lockout schedule and pause file, and the Engine cannot help: `register()` sees a
second connection for a known peer and has no way to tell a duplicate process
from a reconnect after a network blip, so it replaces the writer and the first
agent goes on sending into a dead socket. The check therefore has to happen
here, before the connect loop.

The guard is an exclusive lock on one byte of `agent.lock` inside `STATE_DIR`,
held for the life of the process. The lock belongs to the open handle, so the
operating system drops it on a clean exit, a `taskkill /f` and a bugcheck alike
— there is no stale lock to detect and no liveness to infer.

That last property is why this is not a heartbeat timestamp that a starting
agent compares against a freshness window. Under that design an agent killed at
T and restarted by service recovery at T+2s reads a two-second-old file,
concludes an agent is alive and exits — a crash keeping the agent down, in the
component whose job is to fail closed.

Keyed on the client id rather than the machine, deliberately: two agents under
*different* ids on one box is the supported way to simulate many clients for
telemetry and reporting (issues.md B21). It does not simulate enforcement —
they still share one screen (issues.md D8) — but nothing here should break it.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from client.state import ensure_state_dir, state_path

logger = logging.getLogger(__name__)

LOCK_FILE = "agent.lock"

# Held for the process lifetime. Never closed on the success path: closing the
# handle is what would release the lock.
_lock_handle: int | None = None


if sys.platform == "win32":
    import msvcrt

    def _lock(handle: int) -> None:
        """Lock one byte, non-blocking. Raises OSError if already held."""
        # msvcrt locks relative to the current file position, which is 0 on a
        # freshly opened handle. Locking past the end of a zero-length file is
        # permitted on Windows and is what keeps this free of any write.
        msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)

    def _unlock(handle: int) -> None:
        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)

else:
    # The agent is Windows-only in production; this branch exists so the suite
    # exercises the guard on the Linux side rather than skipping it.
    import fcntl

    def _lock(handle: int) -> None:
        """Lock the file, non-blocking. Raises OSError if already held."""
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: int) -> None:
        fcntl.flock(handle, fcntl.LOCK_UN)


def lock_path() -> Path:
    """Where this client id's lock lives. Per client, since STATE_DIR is."""
    return state_path(LOCK_FILE)


def acquire() -> bool:
    """Take the agent lock for this client id.

    Returns:
        True to proceed. False *only* on a positive detection that another
        agent holds the lock.

    Any other failure — an unwritable state directory, a filesystem that cannot
    lock — is logged and returns True. Refusing to start on those would leave
    the machine with no agent enforcing anything, which is a worse outcome than
    the duplicate this guards against; the two arrive as the same OSError, so
    the distinction is made by which call raised, not by inspecting errno.
    """
    global _lock_handle

    if _lock_handle is not None:
        return True

    try:
        ensure_state_dir()
        # Not "w": truncating a file another agent holds open is both
        # unnecessary and a poor thing to attempt. Nothing is ever written.
        handle = os.open(lock_path(), os.O_CREAT | os.O_RDWR)
    except OSError:
        logger.warning(
            "Could not open the instance lock at %s; starting without the "
            "duplicate-agent guard", lock_path(), exc_info=True,
        )
        return True

    try:
        _lock(handle)
    except OSError:
        os.close(handle)
        return False

    _lock_handle = handle
    return True


def release() -> None:
    """Drop the lock.

    The operating system does this on process exit, which is the property the
    whole design rests on. This exists for tests, and for a caller that outlives
    the agent it started.
    """
    global _lock_handle

    if _lock_handle is None:
        return

    try:
        _unlock(_lock_handle)
    except OSError:
        logger.debug("Instance lock was already released", exc_info=True)
    finally:
        os.close(_lock_handle)
        _lock_handle = None
