"""Command execution.

PHASE 1 SCAFFOLD. Every command type the Engine can send has a handler wired
into the dispatch table; all of them report "not implemented". Phase 4 fills
in the bodies.

Note the shape of execute_script below: it is `async def` returning None
rather than returning a result dict like the others, because it must NOT wait
for the script to finish. Some admin-defined scripts run indefinitely. It
acknowledges the launch and then reports asynchronously via COMMAND_ACCEPTED /
COMMAND_OUTPUT / COMMAND_COMPLETE (README "Script Execution Model"). Getting
that signature right now is what stops Phase 4 from being tempted into a
blocking `subprocess.communicate()`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from client import connection
from client.config import CLIENT_ID
from common.constants import (
    MSG_COMMAND_COMPLETE,
    MSG_COMMAND_RESPONSE,
    MSG_EXECUTE_SCRIPT,
    MSG_SCREEN_CAPTURE,
    MSG_SET_WEBSITE_POLICY,
    MSG_TERMINATE_PROCESS,
    MSG_TERMINATE_SCRIPT,
    STATUS_ERROR,
)
from common.protocol import create_message, get_payload

logger = logging.getLogger(__name__)

# command_id -> live process, so TERMINATE_SCRIPT can target one specific run
# rather than guessing from a process name.
running_scripts: dict[str, asyncio.subprocess.Process] = {}

_NOT_IMPLEMENTED = {"status": STATUS_ERROR, "message": "Not implemented (Phase 1 scaffold)"}


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------


async def execute_script(command_id: str, script: str, script_type: str) -> None:
    """Launch a script detached from the response cycle.

    Sends its own lifecycle messages rather than returning a result, because
    the caller must not block on completion.
    """
    # TODO(Phase 4):
    #   1. Write the script to SCRIPT_LOG_DIR/{command_id}.{py,ps1}.
    #   2. Re-validate it with BUNDLED_PYTHON_PATH -m py_compile (tampering in
    #      transit), rejecting via COMMAND_COMPLETE on failure.
    #   3. create_subprocess_exec with stdout/stderr to {command_id}.log.
    #   4. Register in running_scripts, send COMMAND_ACCEPTED immediately.
    #   5. create_task(tail_log_and_report(...)) - do not await it.
    logger.warning("EXECUTE_SCRIPT %s (%s): not implemented", command_id, script_type)
    await connection.send(
        create_message(
            MSG_COMMAND_COMPLETE,
            {**_NOT_IMPLEMENTED, "command_id": command_id, "returncode": None},
            client_id=CLIENT_ID,
            command_id=command_id,
        )
    )


async def tail_log_and_report(
    command_id: str,
    log_path: str,
    process: asyncio.subprocess.Process,
) -> None:
    """Stream a running script's output, then clean up after it exits."""
    # TODO(Phase 4): poll on a fixed interval; read only when the file size has
    #   grown since the last check; send new bytes as COMMAND_OUTPUT. On exit
    #   send exactly one COMMAND_COMPLETE, then delete the log and the temp
    #   script - both are per-execution scratch, not durable records.


async def terminate_script(target_command_id: str, force: bool = False) -> dict[str, Any]:
    """Stop one running script, identified by the command_id that launched it."""
    # TODO(Phase 4): look up running_scripts, then kill() or terminate().
    logger.warning("TERMINATE_SCRIPT %s: not implemented", target_command_id)
    return dict(_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# Process and policy commands
# ---------------------------------------------------------------------------


async def terminate_process(process_name: str, force: bool = False) -> dict[str, Any]:
    """Terminate processes by name. Also the enforcement path for the
    application blacklist."""
    # TODO(Phase 4): psutil.process_iter, match on name, terminate() or kill().
    logger.warning("TERMINATE_PROCESS %s: not implemented", process_name)
    return dict(_NOT_IMPLEMENTED)


async def capture_screen(quality: int = 80) -> dict[str, Any]:
    """Capture the primary display, compressed for transport."""
    # TODO(Phase 4): grab, JPEG-compress at `quality`, base64 into the payload.
    #   The result is one large JSON line - this is why both ends set
    #   STREAM_LIMIT above asyncio's 64 KiB default.
    logger.warning("SCREEN_CAPTURE: not implemented")
    return dict(_NOT_IMPLEMENTED)


async def set_website_policy(
    mode: str,
    urls: list[str],
    action: str = "block",
) -> dict[str, Any]:
    """Apply a website filtering policy.

    `mode` is required and explicit: blacklist is the default for general lab
    use, whitelist is opt-in for locked-down sessions (README "Access Control").
    """
    # TODO(Phase 4): rewrite the hosts file or drive a local proxy. Whitelist
    #   mode will break sites whose third-party asset domains are unlisted -
    #   that is expected and accepted for locked-down sessions.
    logger.warning("SET_WEBSITE_POLICY (%s, %d urls): not implemented", mode, len(urls))
    return dict(_NOT_IMPLEMENTED)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def handle_command(message: dict[str, Any]) -> None:
    """Dispatch one Engine command and report the outcome.

    EXECUTE_SCRIPT is handled separately: it emits its own lifecycle messages,
    so there is no single COMMAND_RESPONSE to send for it.
    """
    command_type = message.get("type", "")
    payload = get_payload(message)
    command_id = message.get("command_id") or payload.get("command_id") or "unknown"

    logger.info("Received command %s (%s)", command_type, command_id)

    if command_type == MSG_EXECUTE_SCRIPT:
        await execute_script(
            command_id,
            payload.get("script", ""),
            payload.get("script_type", ""),
        )
        return

    if command_type == MSG_TERMINATE_SCRIPT:
        result = await terminate_script(
            payload.get("target_command_id", ""),
            payload.get("force", False),
        )
    elif command_type == MSG_TERMINATE_PROCESS:
        result = await terminate_process(
            payload.get("process_name", ""),
            payload.get("force", False),
        )
    elif command_type == MSG_SCREEN_CAPTURE:
        result = await capture_screen(payload.get("quality", 80))
    elif command_type == MSG_SET_WEBSITE_POLICY:
        result = await set_website_policy(
            payload.get("mode", ""),
            payload.get("urls", []),
            payload.get("action", "block"),
        )
    else:
        logger.warning("Unknown command type %r", command_type)
        result = {"status": STATUS_ERROR, "message": f"Unknown command: {command_type!r}"}

    await connection.send(
        create_message(
            MSG_COMMAND_RESPONSE,
            {"command_id": command_id, **result},
            client_id=CLIENT_ID,
            command_id=command_id,
        )
    )
