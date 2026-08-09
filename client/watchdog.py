#!/usr/bin/env python3
"""Independent lockout watchdog, run by a Scheduled Task.

    python -m client.watchdog --id <client id>

Deliberately a separate process with no dependency on the agent. The agent's
own 30-second pass covers a hung *overlay*; this covers a hung *agent*, which
by definition the agent cannot check for itself (README "Independent
watchdog").

One shot: it enforces once and exits. The Scheduled Task provides the schedule.

**`--id` is not optional in practice.** State lives under a per-client directory
(`client.config.STATE_DIR`), and a Scheduled Task running as SYSTEM does not
inherit the environment the agent was started with — so without being told the
client id this process would resolve a *different* directory, find no schedule,
and release a machine that should still be blocked. That is a fail-open, in the
one component whose whole job is to fail closed. The installer bakes the id into
the task's command line for exactly this reason.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m client.watchdog",
        description="One-shot lockout enforcement pass, independent of the agent.",
    )
    parser.add_argument(
        "--id", metavar="NAME", dest="client_id",
        help="Client id whose state to enforce (env CLIENT_ID). Must match the "
             "agent's, or this reads the wrong state directory and releases a "
             "blocked machine",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level="INFO",
        format="%(asctime)s - watchdog - %(levelname)s - %(message)s",
    )

    # Set before importing anything that reads config: client.config resolves
    # CLIENT_ID and STATE_DIR into module-level constants at import time.
    if args.client_id:
        os.environ["CLIENT_ID"] = args.client_id

    try:
        from client import lockout
        from client.config import CLIENT_ID, STATE_DIR

        logger.info("Enforcing for %s from %s", CLIENT_ID, STATE_DIR)

        schedule = lockout.load_schedule()
        blocked = lockout.is_blocked_now(schedule)

        if blocked:
            logger.info("Block window active; ensuring the overlay is up")
        elif schedule:
            logger.info("No active block window; ensuring the machine is released")
        else:
            # Worth distinguishing from "released": no schedule at all is also
            # what a wrong --id looks like, and that is the failure this flag
            # exists to prevent.
            logger.info("No schedule stored for %s", CLIENT_ID)

        lockout.enforce_once()
        return 0
    except Exception:
        logger.exception("Watchdog pass failed")
        # Non-zero so a failing watchdog shows up in Task Scheduler's history
        # rather than looking like a clean run.
        return 1


if __name__ == "__main__":
    sys.exit(main())
