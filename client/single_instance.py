"""Cross-process locks in STATE_DIR: one agent, and one overlay, per client id.

Two things on a lab machine must not be duplicated, and neither can be settled
inside a single process.

**The agent.** Two agents sharing a `CLIENT_ID` share a `STATE_DIR`, so they race
on the same lockout schedule and pause file, and the Engine cannot help:
`register()` sees a second connection for a known peer and has no way to tell a
duplicate process from a reconnect after a network blip, so it replaces the
writer and the first agent goes on sending into a dead socket.

**The overlay.** The agent and the Scheduled Task watchdog both launch it, by
design — the task exists precisely for when the agent hangs. But `_overlay` in
`client.lockout` is a `Popen` handle, so each process can only see overlays it
started itself, and the watchdog would launch a second one it could then never
stop (issues.md C12).

Both are solved the same way: an exclusive lock on one byte of a file in
`STATE_DIR`, held for the life of the holding process. The lock belongs to the
open handle, so the operating system drops it on a clean exit, a `taskkill /f`
and a bugcheck alike — there is no stale lock to detect and no liveness to infer.

That last property is why this is not a heartbeat timestamp compared against a
freshness window. Under that design a process killed at T and restarted at T+2s
reads a two-second-old file, concludes the previous one is alive and exits — a
crash keeping the machine unenforced, in the component whose job is to fail
closed.

Keyed on the client id rather than the machine, deliberately: two agents under
*different* ids on one box is the supported way to simulate many clients
(issues.md B21). It does not simulate enforcement — they still share one screen
(issues.md D8) — but nothing here should break it.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from client.state import ensure_state_dir, state_path

logger = logging.getLogger(__name__)

# The agent's lock. Held by client/main.py for the life of the process.
AGENT_LOCK = "agent.lock"

# The overlay's lock, held by the overlay itself rather than by whoever launched
# it — that is what makes it answer "is a lockout on screen?" rather than "did
# *I* put one there?".
OVERLAY_LOCK = "overlay.lock"

# Locks are empty files; the owner's pid goes beside them. Kept separate so
# nothing ever writes into the byte range being locked.
_PID_SUFFIX = ".pid"

# name -> open file descriptor. Never closed while held: closing releases.
_handles: dict[str, int] = {}


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
    # exercises the guards on the Linux side rather than skipping them.
    import fcntl

    def _lock(handle: int) -> None:
        """Lock the file, non-blocking. Raises OSError if already held."""
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: int) -> None:
        fcntl.flock(handle, fcntl.LOCK_UN)


def lock_path(name: str = AGENT_LOCK) -> Path:
    """Where a lock lives. Per client, since STATE_DIR is."""
    return state_path(name)


def acquire(name: str = AGENT_LOCK) -> bool:
    """Take a lock, and record this process as its owner.

    Returns:
        True to proceed. False *only* on a positive detection that another
        process holds it.

    Any other failure — an unwritable state directory, a filesystem that cannot
    lock — is logged and returns True. Refusing to start on those would leave
    the machine with nothing enforcing, which is worse than the duplicate this
    guards against; the two arrive as the same OSError, so the distinction is
    made by which call raised, not by inspecting errno.
    """
    if name in _handles:
        return True

    try:
        ensure_state_dir()
        # Not "w": truncating a file another process holds open is both
        # unnecessary and a poor thing to attempt.
        handle = os.open(lock_path(name), os.O_CREAT | os.O_RDWR)
    except OSError:
        logger.warning(
            "Could not open the lock at %s; continuing without this guard",
            lock_path(name), exc_info=True,
        )
        return True

    try:
        _lock(handle)
    except OSError:
        os.close(handle)
        return False

    _handles[name] = handle
    _write_owner_pid(name)
    return True


def release(name: str = AGENT_LOCK) -> None:
    """Drop a lock.

    The operating system does this on process exit, which is the property the
    whole design rests on. This exists for tests, and for a caller that outlives
    the process it started.
    """
    handle = _handles.pop(name, None)
    if handle is None:
        return

    try:
        _unlock(handle)
    except OSError:
        logger.debug("Lock %s was already released", name, exc_info=True)
    finally:
        os.close(handle)
        _clear_owner_pid(name)


def is_held(name: str) -> bool:
    """Is any process — including this one — holding this lock?

    Answered by trying to take it and letting go again, so it reports on the
    real lock rather than on a second record that could disagree with it. The
    momentary acquisition is why callers should treat a True as "something is
    already running" and not as grounds to skip their own guard.
    """
    if name in _handles:
        return True

    try:
        handle = os.open(lock_path(name), os.O_CREAT | os.O_RDWR)
    except OSError:
        logger.debug("Could not probe the lock at %s", lock_path(name), exc_info=True)
        return False

    try:
        _lock(handle)
    except OSError:
        os.close(handle)
        return True

    _unlock(handle)
    os.close(handle)
    return False


def owner_pid(name: str) -> int | None:
    """The pid recorded by whoever holds this lock, if it is readable.

    Advisory only — the lock is the truth. This exists so a process that did not
    launch the holder can still stop it, which `_overlay` being a per-process
    handle otherwise makes impossible.
    """
    try:
        raw = Path(str(lock_path(name)) + _PID_SUFFIX).read_text(encoding="utf-8")
        return int(raw.strip())
    except (OSError, ValueError):
        return None


def _write_owner_pid(name: str) -> None:
    try:
        Path(str(lock_path(name)) + _PID_SUFFIX).write_text(
            str(os.getpid()), encoding="utf-8"
        )
    except OSError:
        logger.debug("Could not record the owner pid for %s", name, exc_info=True)


def _clear_owner_pid(name: str) -> None:
    try:
        Path(str(lock_path(name)) + _PID_SUFFIX).unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not clear the owner pid for %s", name, exc_info=True)
