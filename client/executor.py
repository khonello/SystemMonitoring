"""Command execution.

The shape of execute_script is the important part: it is `async def` returning
None rather than a result dict, because it must NOT wait for the script to
finish. Some admin-defined scripts run indefinitely. It acknowledges the launch
and then reports asynchronously via COMMAND_ACCEPTED / COMMAND_OUTPUT /
COMMAND_COMPLETE (README "Script Execution Model"). A naive
`subprocess.communicate()` would hang forever on exactly the scripts that most
need supervising.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import sys
from pathlib import Path
from typing import Any

import psutil

from client import connection, lockout, policy
from client.config import BUNDLED_PYTHON_PATH, CLIENT_ID, SCRIPT_LOG_DIR
from common.constants import (
    MSG_COMMAND_ACCEPTED,
    MSG_COMMAND_COMPLETE,
    MSG_COMMAND_OUTPUT,
    MSG_COMMAND_RESPONSE,
    MSG_EXECUTE_SCRIPT,
    MSG_SCREEN_CAPTURE,
    MSG_SET_APP_BLACKLIST,
    MSG_SET_TIME_RESTRICTION,
    MSG_SET_WEBSITE_POLICY,
    MSG_SHOW_DIALOG,
    MSG_TERMINATE_PROCESS,
    MSG_TERMINATE_SCRIPT,
    SCRIPT_TYPE_POWERSHELL,
    SCRIPT_TYPE_PYTHON,
    STATUS_ERROR,
    STATUS_SUCCESS,
)
from common.protocol import create_message, get_payload

logger = logging.getLogger(__name__)

# command_id -> live process, so TERMINATE_SCRIPT can target one specific run
# rather than guessing from a process name.
running_scripts: dict[str, asyncio.subprocess.Process] = {}

TAIL_POLL_INTERVAL = 1.0
VALIDATION_TIMEOUT = 15.0
DIALOG_TIMEOUT_SLACK = 10


def python_interpreter() -> str:
    """The interpreter scripts are validated and run with.

    Prefers the bundled, pinned runtime. The development fallback is a real
    caveat, not a nicety: a script validated by the Admin against one version
    could execute here on another.
    """
    if BUNDLED_PYTHON_PATH.exists():
        return str(BUNDLED_PYTHON_PATH)

    logger.warning(
        "Bundled interpreter missing at %s - using %s. Version skew against "
        "the Admin's validating interpreter is possible.",
        BUNDLED_PYTHON_PATH, sys.executable,
    )
    return sys.executable


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------


async def execute_script(command_id: str, script: str, script_type: str) -> None:
    """Launch a script detached from the response cycle."""
    SCRIPT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_path = SCRIPT_LOG_DIR / f"{command_id}.log"

    try:
        argv, script_path = await _prepare(command_id, script, script_type)
    except _ScriptRejected as exc:
        await _send_complete(command_id, STATUS_ERROR, str(exc), returncode=None)
        return

    try:
        with open(log_path, "wb") as log_file:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(SCRIPT_LOG_DIR),
            )
    except OSError as exc:
        _cleanup(log_path, script_path)
        await _send_complete(command_id, STATUS_ERROR, f"Could not launch: {exc}", None)
        return

    running_scripts[command_id] = process

    # Acknowledge immediately. Waiting for completion is exactly what this
    # design exists to avoid.
    await connection.send(
        create_message(
            MSG_COMMAND_ACCEPTED,
            {"command_id": command_id, "log_path": str(log_path)},
            client_id=CLIENT_ID,
            command_id=command_id,
        )
    )

    asyncio.create_task(
        tail_log_and_report(command_id, log_path, script_path, process),
        name=f"tail-{command_id}",
    )


class _ScriptRejected(Exception):
    """The script never launched."""


async def _prepare(command_id: str, script: str, script_type: str) -> tuple[list[str], Path]:
    """Write the script out and build its argv, re-validating on arrival."""
    if script_type == SCRIPT_TYPE_PYTHON:
        script_path = SCRIPT_LOG_DIR / f"{command_id}.py"
        script_path.write_text(script, encoding="utf-8")

        # Re-validated here even though the Admin already checked it, in case
        # of tampering or corruption in transit or storage.
        ok, detail = await _validate_python(script_path)
        if not ok:
            _cleanup(script_path)
            raise _ScriptRejected(f"Script failed validation: {detail}")

        return [python_interpreter(), str(script_path)], script_path

    if script_type == SCRIPT_TYPE_POWERSHELL:
        script_path = SCRIPT_LOG_DIR / f"{command_id}.ps1"
        script_path.write_text(script, encoding="utf-8")
        return (
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(script_path)],
            script_path,
        )

    raise _ScriptRejected(f"Unsupported script_type: {script_type!r}")


async def _validate_python(script_path: Path) -> tuple[bool, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            python_interpreter(), "-m", "py_compile", str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=VALIDATION_TIMEOUT)
    except asyncio.TimeoutError:
        return False, "validation timed out"
    except OSError as exc:
        return False, f"could not run the interpreter: {exc}"

    if process.returncode == 0:
        return True, ""
    return False, stderr.decode("utf-8", errors="replace").strip()


async def tail_log_and_report(
    command_id: str,
    log_path: Path,
    script_path: Path,
    process: asyncio.subprocess.Process,
) -> None:
    """Stream a running script's output, then clean up after it exits.

    Polls on a fixed interval and only reads when the file has actually grown,
    so a silent long-running script costs one stat() per tick rather than a
    reopen-and-read.
    """
    position = 0

    try:
        while True:
            await asyncio.sleep(TAIL_POLL_INTERVAL)
            position = await _drain(command_id, log_path, position)

            if process.returncode is not None:
                break
            try:
                await asyncio.wait_for(process.wait(), timeout=0.01)
                break
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Tailing %s failed", command_id)
    finally:
        # One last read: output written between the final poll and exit would
        # otherwise be lost.
        try:
            await _drain(command_id, log_path, position)
        except Exception:
            logger.debug("Final drain failed for %s", command_id, exc_info=True)

        running_scripts.pop(command_id, None)

        await _send_complete(
            command_id,
            STATUS_SUCCESS if process.returncode == 0 else STATUS_ERROR,
            f"Exited with code {process.returncode}",
            process.returncode,
        )

        # Per-execution scratch space, not a durable record — cleared once the
        # output has been reported.
        _cleanup(log_path, script_path)


async def _drain(command_id: str, log_path: Path, position: int) -> int:
    """Send anything new in the log; return the new read position."""
    try:
        size = log_path.stat().st_size
    except OSError:
        return position

    if size <= position:
        return position

    with open(log_path, "rb") as stream:
        stream.seek(position)
        chunk = stream.read()
        position = stream.tell()

    if chunk:
        await connection.send(
            create_message(
                MSG_COMMAND_OUTPUT,
                {"command_id": command_id,
                 "chunk": chunk.decode("utf-8", errors="replace")},
                client_id=CLIENT_ID,
                command_id=command_id,
            )
        )

    return position


async def _send_complete(
    command_id: str, status: str, message: str, returncode: int | None
) -> None:
    await connection.send(
        create_message(
            MSG_COMMAND_COMPLETE,
            {"command_id": command_id, "status": status,
             "message": message, "returncode": returncode},
            client_id=CLIENT_ID,
            command_id=command_id,
        )
    )


def _cleanup(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Could not remove %s", path, exc_info=True)


async def terminate_script(target_command_id: str, force: bool = False) -> dict[str, Any]:
    """Stop one running script, identified by the command_id that launched it.

    Keyed by command_id rather than process name because a script may run
    indefinitely and several may share an interpreter name.
    """
    process = running_scripts.get(target_command_id)
    if process is None:
        return {"status": STATUS_ERROR,
                "message": f"No running script for {target_command_id}"}

    try:
        if force:
            process.kill()
        else:
            process.terminate()
    except (ProcessLookupError, OSError) as exc:
        return {"status": STATUS_ERROR, "message": f"Could not stop it: {exc}"}

    return {"status": STATUS_SUCCESS, "message": f"Stopped {target_command_id}"}


# ---------------------------------------------------------------------------
# Process control
# ---------------------------------------------------------------------------


async def terminate_process(process_name: str, force: bool = False) -> dict[str, Any]:
    """Terminate processes by name. Also the app-blacklist enforcement path."""
    if not process_name.strip():
        return {"status": STATUS_ERROR, "message": "No process name given"}

    target = process_name.strip().lower()
    terminated: list[int] = []
    denied = 0

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() != target:
                continue
            if force:
                proc.kill()
            else:
                proc.terminate()
            terminated.append(proc.info["pid"])
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            denied += 1
        except Exception:
            logger.debug("Could not terminate pid", exc_info=True)

    if terminated:
        return {"status": STATUS_SUCCESS,
                "message": f"Terminated {len(terminated)} process(es)",
                "terminated": terminated}

    if denied:
        return {"status": STATUS_ERROR,
                "message": f"{denied} matching process(es) refused access"}

    return {"status": STATUS_ERROR, "message": f"No process named {process_name!r}"}


# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------


async def capture_screen(quality: int = 80) -> dict[str, Any]:
    """Capture the primary display, JPEG-compressed and base64-encoded.

    Runs through to_thread: grabbing and encoding a screen is CPU-bound and
    takes long enough to stall the event loop if done inline.
    """
    try:
        encoded, width, height, size = await asyncio.to_thread(_grab_screen, quality)
    except _CaptureUnavailable as exc:
        return {"status": STATUS_ERROR, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        logger.exception("Screen capture failed")
        return {"status": STATUS_ERROR, "message": f"Capture failed: {exc}"}

    return {
        "status": STATUS_SUCCESS,
        "message": f"Captured {width}x{height} ({size / 1024:.0f} KB)",
        "image_base64": encoded,
        "format": "jpeg",
        "width": width,
        "height": height,
    }


class _CaptureUnavailable(Exception):
    """Screen capture is not possible in this environment."""


def _grab_screen(quality: int) -> tuple[str, int, int, int]:
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise _CaptureUnavailable(
            "Pillow is not installed; see requirements-client.txt"
        ) from exc

    image = ImageGrab.grab()
    if image is None:
        raise _CaptureUnavailable("No display available to capture")

    image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=max(1, min(quality, 95)), optimize=True)
    payload = buffer.getvalue()

    # A large capture travels as one JSON line; both ends set STREAM_LIMIT well
    # above asyncio's 64KiB default for exactly this reason.
    return base64.b64encode(payload).decode("ascii"), image.width, image.height, len(payload)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


async def show_dialog(
    message: str, title: str = "Lab Monitor", timeout: int = 60, allow_cancel: bool = False
) -> dict[str, Any]:
    """Spawn the bundled dialog executable and report the user's answer.

    Spawned the same way scripts are, so it never blocks the event loop, and
    the answer comes back as an exit code.
    """
    from client.config import DIALOG_EXE_PATH

    if DIALOG_EXE_PATH.exists():
        argv = [str(DIALOG_EXE_PATH)]
    else:
        logger.warning("Dialog executable missing at %s - running the module",
                       DIALOG_EXE_PATH)
        argv = [sys.executable, "-m", "client.dialog_app"]

    argv += ["--message", message, "--title", title, "--timeout", str(timeout)]
    if allow_cancel:
        argv.append("--allow-cancel")

    try:
        process = await asyncio.create_subprocess_exec(*argv)
        returncode = await asyncio.wait_for(
            process.wait(), timeout=timeout + DIALOG_TIMEOUT_SLACK
        )
    except asyncio.TimeoutError:
        return {"status": STATUS_ERROR, "message": "Dialog did not close in time"}
    except OSError as exc:
        return {"status": STATUS_ERROR, "message": f"Could not show dialog: {exc}"}

    answers = {0: "acknowledged", 1: "cancelled", 2: "timed out", 3: "bad arguments"}
    return {
        "status": STATUS_SUCCESS if returncode in (0, 1, 2) else STATUS_ERROR,
        "message": f"User {answers.get(returncode, f'exited {returncode}')}",
        "response": answers.get(returncode, "unknown"),
    }


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
            command_id, payload.get("script", ""), payload.get("script_type", "")
        )
        return

    try:
        result = await _run_command(command_type, payload)
    except Exception as exc:  # noqa: BLE001 - reported rather than killing the listener
        logger.exception("Command %s failed", command_type)
        result = {"status": STATUS_ERROR, "message": f"Internal error: {exc}"}

    await connection.send(
        create_message(
            MSG_COMMAND_RESPONSE,
            {"command_id": command_id, **result},
            client_id=CLIENT_ID,
            command_id=command_id,
        )
    )


async def _run_command(command_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if command_type == MSG_TERMINATE_SCRIPT:
        return await terminate_script(
            payload.get("target_command_id", ""), payload.get("force", False)
        )

    if command_type == MSG_TERMINATE_PROCESS:
        return await terminate_process(
            payload.get("process_name", ""), payload.get("force", False)
        )

    if command_type == MSG_SCREEN_CAPTURE:
        return await capture_screen(payload.get("quality", 80))

    if command_type == MSG_SET_WEBSITE_POLICY:
        return await asyncio.to_thread(
            policy.apply_website_policy,
            payload.get("mode", ""),
            payload.get("urls", []),
            payload.get("action", "block"),
        )

    if command_type == MSG_SET_APP_BLACKLIST:
        return await asyncio.to_thread(
            policy.set_app_blacklist, payload.get("process_names", [])
        )

    if command_type == MSG_SET_TIME_RESTRICTION:
        return await asyncio.to_thread(lockout.apply_command, payload)

    if command_type == MSG_SHOW_DIALOG:
        return await show_dialog(
            payload.get("message", ""),
            payload.get("title", "Lab Monitor"),
            int(payload.get("timeout", 60)),
            bool(payload.get("allow_cancel", False)),
        )

    return {"status": STATUS_ERROR, "message": f"Unknown command: {command_type!r}"}
