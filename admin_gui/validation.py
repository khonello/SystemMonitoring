"""Script validation, run before anything is sent to a client.

Catching authoring mistakes here rather than discovering them on a lab machine
is the whole point of the Admin GUI carrying its own interpreter (README
"Bundled Runtime & Script Validation").
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from admin_gui.config import BUNDLED_PYTHON_PATH
from common.constants import SCRIPT_TYPE_POWERSHELL, SCRIPT_TYPE_PYTHON

logger = logging.getLogger(__name__)

VALIDATION_TIMEOUT = 15.0


def python_interpreter() -> str:
    """The interpreter used for validation.

    Prefers the bundled, pinned runtime. Falls back to the running interpreter
    during development, before the Phase 4 packaging step exists — which is a
    real caveat: a fallback validation can pass against a different Python
    version than the client will execute on.
    """
    if BUNDLED_PYTHON_PATH.exists():
        return str(BUNDLED_PYTHON_PATH)

    logger.warning(
        "Bundled interpreter missing at %s - validating with %s instead. "
        "Version skew against the client's runtime is possible.",
        BUNDLED_PYTHON_PATH,
        sys.executable,
    )
    return sys.executable


async def validate_script(script: str, script_type: str) -> tuple[bool, str]:
    """Check a script compiles.

    Returns:
        (ok, message). `message` is empty on success, otherwise the compiler's
        complaint, ready to show the operator.
    """
    if not script.strip():
        return False, "Script is empty"

    if script_type == SCRIPT_TYPE_PYTHON:
        return await _validate_python(script)

    if script_type == SCRIPT_TYPE_POWERSHELL:
        return _validate_powershell(script)

    return False, f"Unsupported script type: {script_type!r}"


async def _validate_python(script: str) -> tuple[bool, str]:
    """Syntax-check with `py_compile` in the validating interpreter.

    A subprocess rather than a plain compile() call, so the check runs under
    the same interpreter version the client will use.
    """
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "candidate.py"
        source.write_text(script, encoding="utf-8")

        try:
            process = await asyncio.create_subprocess_exec(
                python_interpreter(),
                "-m",
                "py_compile",
                str(source),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=VALIDATION_TIMEOUT
            )
        except asyncio.TimeoutError:
            return False, "Validation timed out"
        except OSError as exc:
            return False, f"Could not run the validating interpreter: {exc}"

    if process.returncode == 0:
        return True, ""

    return False, stderr.decode("utf-8", errors="replace").strip()


def _validate_powershell(script: str) -> tuple[bool, str]:
    """Parse-check PowerShell.

    Deliberately not a subprocess: invoking powershell.exe to check syntax
    risks *running* something if the invocation is got wrong, and the whole
    point is to validate without executing. Only balance-checking is done
    here; the client re-checks on arrival.
    """
    unbalanced = _first_unbalanced(script)
    if unbalanced is not None:
        return False, f"Unbalanced {unbalanced}"
    return True, ""


def _first_unbalanced(script: str) -> str | None:
    """Return the first bracket type that does not balance, if any."""
    pairs = {"{": "}", "(": ")", "[": "]"}
    closers = {close: open_ for open_, close in pairs.items()}
    stack: list[str] = []

    for char in script:
        if char in pairs:
            stack.append(char)
        elif char in closers:
            if not stack or stack[-1] != closers[char]:
                return f"'{char}'"
            stack.pop()

    if stack:
        return f"'{stack[-1]}'"
    return None
