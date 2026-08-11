"""Which Windows session this process is in.

Session 0 is reserved for services and has no display attached, so a window
drawn there reaches nobody. The agent is designed to run as a service, and it
also has to put the lockout overlay in front of a specific logged-in person —
two requirements that pull opposite ways (issues.md C11).

This module does not resolve that. It makes it *visible*: the failure mode being
guarded against is one where the overlay launches, the log says it launched, and
the screen stays untouched. A one-line warning at the point of launch is the
difference between reading that log and believing it.

Standard library only — `ProcessIdToSessionId` is a plain kernel32 call, so this
costs no dependency.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Services always land here; the first interactive user gets 1, the next 2.
SERVICES_SESSION = 0


def current_session_id() -> int | None:
    """This process's Windows session, or None off Windows or on failure."""
    if sys.platform != "win32":
        return None

    session = ctypes.c_ulong()
    try:
        ok = ctypes.windll.kernel32.ProcessIdToSessionId(
            os.getpid(), ctypes.byref(session)
        )
    except (AttributeError, OSError):
        logger.debug("ProcessIdToSessionId unavailable", exc_info=True)
        return None

    return session.value if ok else None


def in_services_session() -> bool:
    """True when this process cannot reach an interactive desktop.

    False when the answer is unknown — off Windows, or if the call failed. A
    caller uses this to warn, never to decide whether to enforce, so guessing
    "probably fine" is the safe direction: the alternative would have a failed
    API call suppress a lockout.
    """
    return current_session_id() == SERVICES_SESSION


def warn_if_invisible(what: str) -> bool:
    """Log loudly before drawing something a session-0 process cannot show.

    Returns True if the warning fired, so callers can record it. The point is
    that `enforce_once()` returning cleanly, the watchdog exiting 0 and Task
    Scheduler recording a clean run currently all say "enforced" whether or not
    anything appeared.
    """
    if not in_services_session():
        return False

    logger.warning(
        "%s is being launched from session 0, which has no display attached - "
        "it may run without anyone seeing it (issues.md C11)", what,
    )
    return True
