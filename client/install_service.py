#!/usr/bin/env python3
"""Install the Client Agent as a Windows service.

    python -m client.install_service --startup auto
    python -m client.install_service --uninstall

Three things happen here, and the third is easy to forget:

1. The agent is registered as an auto-start service, so it survives a reboot.
2. `%ProgramData%` state is ACL-restricted to SYSTEM and Administrators, so a
   logged-in student cannot rewrite their own lockout schedule. The running
   agent deliberately does not do this itself — a process should not be able to
   widen its own permissions.
3. A Scheduled Task is registered that runs the lockout check independently.
   This is the backstop for the case the agent-level watchdog cannot cover:
   the agent itself having hung or crashed (README "Independent watchdog").

Needs an elevated prompt.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import subprocess
import sys
from pathlib import Path

from client.config import STATE_DIR

logger = logging.getLogger(__name__)

SERVICE_NAME = "LabMonitorAgent"
SERVICE_DISPLAY = "Lab Monitor Client Agent"
TASK_NAME = "LabMonitorLockoutWatchdog"

# Longer than the agent's own 30s pass: this exists to catch a dead agent, not
# to duplicate a working one.
TASK_INTERVAL_MINUTES = 5


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run(argv: list[str]) -> tuple[int, str]:
    completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def agent_command() -> str:
    """Command line that starts the agent."""
    frozen = Path(sys.executable).parent / "labmonitor-agent.exe"
    if frozen.exists():
        return str(frozen)
    return f'"{sys.executable}" -m client.main'


def watchdog_command() -> str:
    """Command line for the independent lockout check."""
    frozen = Path(sys.executable).parent / "labmonitor-watchdog.exe"
    if frozen.exists():
        return str(frozen)
    return f'"{sys.executable}" -m client.watchdog'


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def secure_state_directory() -> bool:
    """Restrict %ProgramData% state to SYSTEM and Administrators.

    Without this the lockout schedule sits somewhere the logged-in user can
    edit. The HMAC would still catch the edit and fail closed, but defence in
    depth costs one icacls call.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    code, output = _run([
        "icacls", str(STATE_DIR),
        "/inheritance:r",
        "/grant:r", "SYSTEM:(OI)(CI)F",
        "/grant:r", "Administrators:(OI)(CI)F",
        "/grant:r", "Users:(OI)(CI)R",
    ])

    if code != 0:
        logger.error("Could not restrict %s: %s", STATE_DIR, output)
        return False

    logger.info("State directory secured: %s", STATE_DIR)
    return True


def install_service(startup: str) -> bool:
    code, output = _run([
        "sc", "create", SERVICE_NAME,
        f"binPath= {agent_command()}",
        f"start= {startup}",
        f"DisplayName= {SERVICE_DISPLAY}",
    ])

    if code != 0:
        logger.error("Service creation failed: %s", output)
        return False

    _run(["sc", "description", SERVICE_NAME,
          "Monitors this machine and enforces lab access policy."])

    # Restart on failure rather than leaving a lab machine unmonitored.
    _run(["sc", "failure", SERVICE_NAME, "reset= 86400",
          "actions= restart/60000/restart/60000/restart/60000"])

    logger.info("Service %s installed (%s start)", SERVICE_NAME, startup)
    return True


def register_watchdog_task() -> bool:
    code, output = _run([
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", watchdog_command(),
        "/SC", "MINUTE",
        "/MO", str(TASK_INTERVAL_MINUTES),
        "/RU", "SYSTEM",
        "/RL", "HIGHEST",
        "/F",
    ])

    if code != 0:
        logger.error("Watchdog task registration failed: %s", output)
        return False

    logger.info("Watchdog task %s registered (every %d minutes)",
                TASK_NAME, TASK_INTERVAL_MINUTES)
    return True


def uninstall() -> bool:
    ok = True

    code, output = _run(["sc", "stop", SERVICE_NAME])
    if code != 0:
        logger.debug("Service stop: %s", output)

    code, output = _run(["sc", "delete", SERVICE_NAME])
    if code != 0:
        logger.error("Service removal failed: %s", output)
        ok = False

    code, output = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if code != 0:
        logger.error("Watchdog task removal failed: %s", output)
        ok = False

    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the Client Agent")
    parser.add_argument("--startup", default="auto", choices=["auto", "demand", "delayed-auto"])
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level="INFO", format="%(levelname)s - %(message)s")

    if sys.platform != "win32":
        logger.error("The Client Agent is Windows-only")
        return 1

    if not is_elevated():
        logger.error("Run this from an elevated prompt")
        return 1

    if args.uninstall:
        return 0 if uninstall() else 1

    steps = [
        ("secure state directory", secure_state_directory()),
        ("install service", install_service(args.startup)),
        ("register watchdog task", register_watchdog_task()),
    ]

    failed = [name for name, ok in steps if not ok]
    if failed:
        logger.error("Installation incomplete: %s failed", ", ".join(failed))
        return 1

    logger.info("Installation complete. Start it with: sc start %s", SERVICE_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
