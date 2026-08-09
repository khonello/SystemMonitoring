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
from client.state import PAUSE_FILE, SCHEDULE_FILE, StateTampered, read_state, write_state
from common.constants import (
    MAX_BLOCK_HOURS,
    OVERLAY_MODE_PAUSE,
    OVERLAY_MODE_SCHEDULED,
    PAUSE_MAX_SECONDS,
    STATUS_ERROR,
    STATUS_SUCCESS,
)

logger = logging.getLogger(__name__)

# How often the agent checks whether the overlay should still be running.
WATCHDOG_INTERVAL = 30

_overlay: subprocess.Popen[bytes] | None = None
_overlay_mode: str | None = None


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
# Indeterminate pause
# ---------------------------------------------------------------------------
#
# Distinct from a scheduled restriction in intent and in presentation. A
# schedule has a known end the student can see counting down; a pause has no
# stated end and shows none — the admin holds it and drops it.
#
# The one-hour bound is a fail-safe against the admin, not a policy: if the
# operator closes the GUI or the network dies mid-pause, the lab must not stay
# frozen. The Admin GUI warns before it lapses so extending is deliberate.


def store_pause(until: datetime) -> dict[str, Any]:
    """Persist a pause, capping how long it can last unattended."""
    capped = min(until, _now() + timedelta(seconds=PAUSE_MAX_SECONDS))
    if capped < until:
        logger.warning(
            "Pause shortened from %s to %s by the %ds cap",
            until.isoformat(), capped.isoformat(), PAUSE_MAX_SECONDS,
        )

    pause = {"until": capped.isoformat(), "set_at": _now().isoformat()}
    write_state(PAUSE_FILE, pause)
    return pause


def load_pause() -> dict[str, Any] | None:
    """Read the stored pause.

    Fails closed like the schedule: a tampered file is treated as an active
    pause rather than trusted, since the tamper itself is evidence of intent.
    """
    try:
        return read_state(PAUSE_FILE)
    except StateTampered as exc:
        logger.error("Pause state tampered with (%s) - failing closed", exc)
        return {
            "until": (_now() + timedelta(seconds=PAUSE_MAX_SECONDS)).isoformat(),
            "set_at": _now().isoformat(),
            "tampered": True,
        }


def is_paused(pause: dict[str, Any] | None = None) -> bool:
    pause = pause if pause is not None else load_pause()
    if not pause:
        return False

    until = _parse(pause.get("until"))
    if until is None:
        logger.error("Pause state has an unreadable end time - failing closed")
        return True

    return _now() < until


def clear_pause() -> None:
    from client.state import clear_state

    clear_state(PAUSE_FILE)


def pause_expires_at() -> datetime | None:
    """When the current pause lapses, or None if not paused."""
    pause = load_pause()
    return _parse(pause.get("until")) if pause and is_paused(pause) else None


def apply_pause_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a SET_PAUSE command from the Engine."""
    action = payload.get("action", "pause")

    if action in {"resume", "clear", "release"}:
        clear_pause()
        enforce_once()
        return {"status": STATUS_SUCCESS, "message": "Pause released"}

    if action != "pause":
        return {"status": STATUS_ERROR, "message": f"Unknown pause action: {action!r}"}

    requested = payload.get("seconds")
    try:
        seconds = int(requested) if requested is not None else PAUSE_MAX_SECONDS
    except (TypeError, ValueError):
        seconds = PAUSE_MAX_SECONDS

    seconds = max(1, min(seconds, PAUSE_MAX_SECONDS))
    stored = store_pause(_now() + timedelta(seconds=seconds))
    enforce_once()

    return {
        "status": STATUS_SUCCESS,
        "message": "Screen paused",
        # Reported so the Admin GUI knows when to warn, without having to
        # assume the client honoured what it asked for.
        "pause_until": stored["until"],
    }


# ---------------------------------------------------------------------------
# Overlay process
# ---------------------------------------------------------------------------


def overlay_running() -> bool:
    return _overlay is not None and _overlay.poll() is None


def _overlay_command(end: datetime, mode: str) -> list[str]:
    """argv for the overlay, preferring the bundled executable.

    Falls back to running the module with the current interpreter during
    development, before the Phase 8 packaging step has produced the exe.
    """
    args = ["--until", end.isoformat(), "--mode", mode]

    if OVERLAY_EXE_PATH.exists():
        return [str(OVERLAY_EXE_PATH), *args]

    logger.warning(
        "Overlay executable missing at %s - running the module directly",
        OVERLAY_EXE_PATH,
    )
    return [sys.executable, "-m", "client.overlay_app", *args]


def start_overlay(end: datetime, mode: str = OVERLAY_MODE_SCHEDULED) -> bool:
    """Launch the overlay, or restart it if the mode has changed.

    The mode matters to what the student sees: a scheduled block counts down,
    a pause deliberately does not. Switching between them means replacing the
    window rather than leaving a countdown running under a pause.
    """
    global _overlay, _overlay_mode

    if overlay_running():
        if _overlay_mode == mode:
            return True
        logger.info("Overlay mode changing from %s to %s; restarting", _overlay_mode, mode)
        stop_overlay()

    try:
        _overlay = subprocess.Popen(_overlay_command(end, mode))
        _overlay_mode = mode
    except OSError:
        logger.exception("Could not launch the overlay")
        return False

    if mode == OVERLAY_MODE_PAUSE:
        logger.warning("Screen paused (internal expiry %s)", end.isoformat())
    else:
        logger.warning("Lockout overlay started, blocking until %s", end.isoformat())
    return True


def stop_overlay() -> None:
    """Force the overlay closed.

    terminate() first, then kill() if it does not go — the whole reason a
    watchdog exists is that the overlay may be wedged, and a wedged process
    will not honour a polite request.
    """
    global _overlay, _overlay_mode

    _overlay_mode = None

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
    """Bring the overlay in line with both the pause and the schedule.

    Deliberately a single synchronous pass with no memory of previous calls, so
    the same function serves the agent's watchdog loop, the startup check after
    a reboot, and the external Scheduled Task.

    A pause takes precedence over a scheduled block: it is the live admin
    action, and it deliberately shows no countdown. Dropping the pause while a
    scheduled window is still open falls back to the countdown rather than
    releasing the machine.
    """
    pause = load_pause()
    if is_paused(pause):
        until = _parse(pause.get("until")) if pause else None
        if until is not None:
            start_overlay(until, OVERLAY_MODE_PAUSE)
        return

    schedule = load_schedule()
    if is_blocked_now(schedule):
        end = _parse(schedule.get("end")) if schedule else None
        if end is not None:
            start_overlay(end, OVERLAY_MODE_SCHEDULED)
        return

    if overlay_running():
        logger.info("No active pause or block window; releasing the machine")
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
