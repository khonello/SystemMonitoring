#!/usr/bin/env python3
"""Independent lockout watchdog, run by a Scheduled Task.

    python -m client.watchdog

Deliberately a separate process with no dependency on the agent. The agent's
own 30-second pass covers a hung *overlay*; this covers a hung *agent*, which
by definition the agent cannot check for itself (README "Independent
watchdog").

One shot: it enforces once and exits. The Scheduled Task provides the schedule.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s - watchdog - %(levelname)s - %(message)s",
    )

    try:
        from client import lockout

        schedule = lockout.load_schedule()
        blocked = lockout.is_blocked_now(schedule)

        if blocked:
            logger.info("Block window active; ensuring the overlay is up")
        elif schedule:
            logger.info("No active block window; ensuring the machine is released")

        lockout.enforce_once()
        return 0
    except Exception:
        logger.exception("Watchdog pass failed")
        # Non-zero so a failing watchdog shows up in Task Scheduler's history
        # rather than looking like a clean run.
        return 1


if __name__ == "__main__":
    sys.exit(main())
