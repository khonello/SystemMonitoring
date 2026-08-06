"""Time-based access restriction.

The lockout screen is a separate bundled overlay executable, launched only
while a block window is active — not a persistent hidden process.

Three properties matter more than the UI (README "Time-Based Restriction
Enforcement"):

1. **Fails closed.** If the stored schedule fails its integrity check, the
   machine is treated as still blocked. Editing the file to escape early gets
   you a locked screen, not an early release.
2. **Bounded.** Any single continuous block is capped at 2 hours. This is a
   safety timeout against the *overlay's own* failure modes — a hang or a
   rendering fault leaving the screen stuck — not a response to losing the
   network, since enforcement is entirely local.
3. **Watched from outside.** The overlay process could itself hang, so the
   agent force-closes it once its stored end time passes, and a Scheduled Task
   registered at install time runs the same check independently in case the
   *agent* is what has hung.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from client.config import OVERLAY_EXE_PATH
from client.state import SCHEDULE_FILE, StateTampered, read_state, write_state

logger = logging.getLogger(__name__)

# Safety timeout against the overlay's own failure modes.
MAX_BLOCK_HOURS = 2

# How often the agent checks whether the overlay should still be running.
WATCHDOG_INTERVAL = 30

_overlay: subprocess.Popen[bytes] | None = None


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def store_schedule(start: datetime, end: datetime) -> dict[str, Any]:
    """Persist a block window, capping its length.

    Returns the schedule as stored, whose end may be earlier than requested.
    """
    capped_end = min(end, start + timedelta(hours=MAX_BLOCK_HOURS))
    if capped_end < end:
        logger.warning(
            "Block window shortened from %s to %s by the %dh cap",
            end.isoformat(), capped_end.isoformat(), MAX_BLOCK_HOURS,
        )

    schedule = {"start": start.isoformat(), "end": capped_end.isoformat()}
    write_state(SCHEDULE_FILE, schedule)
    return schedule


def load_schedule() -> dict[str, Any] | None:
    """Read the stored block window.

    Returns:
        The schedule, None if none is stored, or a synthetic "blocked" schedule
        when the stored one fails its integrity check — failing closed.
    """
    try:
        return read_state(SCHEDULE_FILE)
    except StateTampered as exc:
        logger.error("Lockout schedule tampered with (%s) - failing closed", exc)
        now = _now()
        return {
            "start": now.isoformat(),
            "end": (now + timedelta(hours=MAX_BLOCK_HOURS)).isoformat(),
            "tampered": True,
        }


def is_blocked_now(schedule: dict[str, Any] | None = None) -> bool:
    """Whether a block window is currently active."""
    schedule = schedule if schedule is not None else load_schedule()
    if not schedule:
        return False

    start = _parse(schedule.get("start"))
    end = _parse(schedule.get("end"))
    if start is None or end is None:
        # Unparseable but integrity-valid: still fail closed.
        logger.error("Lockout schedule has unreadable times - failing closed")
        return True

    return start <= _now() < end


def clear_schedule() -> None:
    from client.state import clear_state

    clear_state(SCHEDULE_FILE)


# ---------------------------------------------------------------------------
# Overlay process
# ---------------------------------------------------------------------------


def overlay_running() -> bool:
    return _overlay is not None and _overlay.poll() is None


def _overlay_command(end: datetime) -> list[str]:
    """argv for the overlay, preferring the bundled executable.

    Falls back to running the module with the current interpreter during
    development, before the Phase 4 packaging step has produced the exe.
    """
    if OVERLAY_EXE_PATH.exists():
        return [str(OVERLAY_EXE_PATH), "--until", end.isoformat()]

    logger.warning(
        "Overlay executable missing at %s - running the module directly",
        OVERLAY_EXE_PATH,
    )
    return [sys.executable, "-m", "client.overlay_app", "--until", end.isoformat()]


def start_overlay(end: datetime) -> bool:
    """Launch the lockout overlay if it is not already up."""
    global _overlay

    if overlay_running():
        return True

    try:
        _overlay = subprocess.Popen(_overlay_command(end))
    except OSError:
        logger.exception("Could not launch the lockout overlay")
        return False

    logger.warning("Lockout overlay started, blocking until %s", end.isoformat())
    return True


def stop_overlay() -> None:
    """Force the overlay closed.

    terminate() first, then kill() if it does not go — the whole reason a
    watchdog exists is that the overlay may be wedged, and a wedged process
    will not honour a polite request.
    """
    global _overlay

    if _overlay is None:
        return

    if _overlay.poll() is None:
        try:
            _overlay.terminate()
            _overlay.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Overlay ignored terminate; killing it")
            _overlay.kill()
        except OSError:
            logger.exception("Could not stop the overlay")

    _overlay = None
    logger.info("Lockout overlay stopped")


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def enforce_once() -> None:
    """Bring the overlay's state in line with the schedule.

    Deliberately a single synchronous pass with no memory of previous calls, so
    the same function serves the agent's watchdog loop, the startup check after
    a reboot, and the external Scheduled Task.
    """
    schedule = load_schedule()

    if is_blocked_now(schedule):
        end = _parse(schedule.get("end")) if schedule else None
        if end is not None:
            start_overlay(end)
        return

    if overlay_running():
        logger.info("Block window has passed; releasing the machine")
        stop_overlay()


async def watchdog_loop(stop: asyncio.Event) -> None:
    """Keep the overlay honest, from outside the overlay.

    The agent is the primary watchdog. The Scheduled Task registered at install
    time is the backstop for the case this loop cannot cover — the agent itself
    having hung or crashed.
    """
    while not stop.is_set():
        try:
            enforce_once()
        except Exception:
            logger.exception("Lockout enforcement pass failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=WATCHDOG_INTERVAL)
            return
        except asyncio.TimeoutError:
            continue


def apply_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a SET_TIME_RESTRICTION command from the Engine."""
    start = _parse(payload.get("start")) or _now()
    end = _parse(payload.get("end"))

    if payload.get("clear"):
        clear_schedule()
        stop_overlay()
        return {"status": "success", "message": "Time restriction cleared"}

    if end is None:
        return {"status": "error", "message": "Missing or unparseable 'end'"}

    if end <= start:
        return {"status": "error", "message": "'end' must be after 'start'"}

    stored = store_schedule(start, end)
    enforce_once()

    return {
        "status": "success",
        "message": f"Blocked until {stored['end']}",
        "effective_end": stored["end"],
    }


def check_on_startup() -> None:
    """Re-apply an active block before anything else runs.

    A reboot is not an escape hatch: the agent auto-starts, reads the locally
    stored schedule, and re-launches the overlay if the window is still open —
    without needing the Engine to be reachable.
    """
    try:
        if is_blocked_now():
            logger.warning("Active lockout found at startup; re-applying")
        enforce_once()
    except Exception:
        logger.exception("Startup lockout check failed")
