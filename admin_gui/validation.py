"""Script validation, run before anything is sent to a client.

Catching mistakes here rather than discovering them on a lab machine is the
whole reason the Admin GUI carries its own interpreter (README "Bundled Runtime
& Script Validation").

Three checks, in increasing cost:

1. **Syntax** — the script parses at all.
2. **Import policy** — predefined scripts are an extension mechanism for small
   routine tasks, so they are standard-library only. No third-party packages,
   because the client's runtime has no pip and nothing to install them with.
3. **Target availability** — the imports actually exist on a Windows client.

Imports are read with `ast`, not a regular expression. A regex cannot see the
difference between `import os` and the same words inside a docstring, and it
mishandles `import os, sys` and parenthesised multi-line `from` imports. The
parser already exists; using it costs nothing and cannot be fooled.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

from admin_gui.config import BUNDLED_PYTHON_PATH
from common.constants import SCRIPT_TYPE_POWERSHELL, SCRIPT_TYPE_PYTHON

logger = logging.getLogger(__name__)

VALIDATION_TIMEOUT = 15.0

# Every module name the standard library ships, for the running Python version.
# Available since 3.10, which is this project's floor.
STDLIB_MODULES: frozenset[str] = frozenset(sys.stdlib_module_names)

# Standard-library modules that exist in the docs but not on Windows, because
# they wrap POSIX facilities. Clients are Windows-only, so importing any of
# these is a guaranteed failure on the lab machine even though the script is
# perfectly valid Python and compiles cleanly here.
#
# find_spec in the bundled interpreter is the authoritative check — this list
# exists so the operator gets "fcntl is Unix-only" instead of a bare "not
# found", and so the check still says something useful before the bundled
# runtime is packaged.
POSIX_ONLY_MODULES: frozenset[str] = frozenset({
    "crypt",
    "curses",
    "fcntl",
    "grp",
    "nis",
    "ossaudiodev",
    "posix",
    "pty",
    "pwd",
    "readline",
    "resource",
    "spwd",
    "syslog",
    "termios",
    "tty",
})

# Windows counterparts, listed only to explain why a Unix-minded author's
# instinct is wrong — these are the modules that *do* work here.
WINDOWS_EQUIVALENTS: dict[str, str] = {
    "pwd": "no equivalent; use os.getlogin() or the ctypes Win32 API",
    "grp": "no equivalent on Windows",
    "fcntl": "use msvcrt.locking for file locking",
    "termios": "use msvcrt for console handling",
    "tty": "use msvcrt for console handling",
    "pty": "no equivalent; use subprocess with pipes",
    "resource": "no equivalent; psutil is not available to scripts",
    "syslog": "use the logging module, or the Windows event log via pywin32",
    "curses": "no equivalent; write plain stdout",
    "readline": "no equivalent on Windows",
}


# ---------------------------------------------------------------------------
# Interpreter
# ---------------------------------------------------------------------------


def python_interpreter() -> str:
    """The interpreter used for validation.

    Prefers the bundled, pinned runtime. Falls back to the running interpreter
    during development, before the packaging step exists — a real caveat, since
    a fallback check can pass against a different Python version, and a
    different module set, than the client will execute on.
    """
    if BUNDLED_PYTHON_PATH.exists():
        return str(BUNDLED_PYTHON_PATH)

    logger.warning(
        "Bundled interpreter missing at %s - validating with %s instead. "
        "Version and module-availability skew against the client is possible.",
        BUNDLED_PYTHON_PATH,
        sys.executable,
    )
    return sys.executable


def using_bundled_interpreter() -> bool:
    """Whether validation reflects the client's actual runtime."""
    return BUNDLED_PYTHON_PATH.exists()


# ---------------------------------------------------------------------------
# Import analysis
# ---------------------------------------------------------------------------


def extract_imports(script: str) -> list[str]:
    """Every module a script imports, as written.

    Returns dotted names: `import a.b` yields "a.b", `from a.b import c`
    yields "a.b". Relative imports are skipped — a script is a single file with
    no package around it, so there is nothing for them to resolve against, and
    Python will reject them at runtime anyway.

    Raises:
        SyntaxError: If the script does not parse.
    """
    tree = ast.parse(script)
    modules: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # node.level > 0 is a relative import (`from . import x`).
            if node.level == 0 and node.module:
                modules.append(node.module)

    # Sorted and de-duplicated so the report is stable between runs.
    return sorted(set(modules))


def top_level(module: str) -> str:
    return module.split(".", 1)[0]


def classify_imports(modules: list[str]) -> dict[str, list[str]]:
    """Sort imports into stdlib, third-party and Unix-only."""
    stdlib: list[str] = []
    third_party: list[str] = []
    posix_only: list[str] = []

    for module in modules:
        root = top_level(module)

        if root in POSIX_ONLY_MODULES:
            posix_only.append(module)
        elif root in STDLIB_MODULES:
            stdlib.append(module)
        else:
            third_party.append(module)

    return {"stdlib": stdlib, "third_party": third_party, "posix_only": posix_only}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _empty_result(ok: bool, errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": ok,
        "errors": errors or [],
        "warnings": [],
        "stdlib": [],
        "third_party": [],
        "posix_only": [],
        "unavailable": [],
        "bundled": using_bundled_interpreter(),
    }


async def validate_script(script: str, script_type: str) -> tuple[bool, str]:
    """Backwards-compatible pass/fail wrapper around `analyse_script`."""
    result = await analyse_script(script, script_type)
    return result["ok"], "\n".join(result["errors"])


async def analyse_script(script: str, script_type: str) -> dict[str, Any]:
    """Fully check a script and report everything found.

    Returns a dict the GUI can render directly: `ok`, plus `errors`,
    `warnings`, and the import breakdown so the operator can see *what* was
    accepted, not just that it passed.
    """
    if not script.strip():
        return _empty_result(False, ["Script is empty"])

    if script_type == SCRIPT_TYPE_POWERSHELL:
        return _validate_powershell(script)

    if script_type != SCRIPT_TYPE_PYTHON:
        return _empty_result(False, [f"Unsupported script type: {script_type!r}"])

    return await _validate_python(script)


async def _validate_python(script: str) -> dict[str, Any]:
    # Syntax first: an unparseable script has no imports to analyse, and the
    # parse error is the only thing worth reporting.
    try:
        modules = extract_imports(script)
    except SyntaxError as exc:
        location = f" (line {exc.lineno})" if exc.lineno else ""
        return _empty_result(False, [f"SyntaxError{location}: {exc.msg}"])

    result = _empty_result(True)
    result.update(classify_imports(modules))

    if result["third_party"]:
        result["ok"] = False
        result["errors"].append(
            "Third-party imports are not allowed: "
            + ", ".join(result["third_party"])
            + ". Predefined scripts run on the client's bundled runtime, which "
              "has no pip and nothing installed beyond the standard library."
        )

    if result["posix_only"]:
        result["ok"] = False
        for module in result["posix_only"]:
            hint = WINDOWS_EQUIVALENTS.get(top_level(module))
            result["errors"].append(
                f"{module} is Unix-only and does not exist on Windows clients"
                + (f" - {hint}" if hint else "")
            )

    # Compile check, which catches everything the import analysis does not.
    compiled, detail = await _compile_check(script)
    if not compiled:
        result["ok"] = False
        result["errors"].append(detail)
        return result

    # Availability in the runtime that will actually execute this. Skipped when
    # the imports are already rejected — no point asking about modules the
    # operator has to remove anyway.
    if result["ok"] and result["stdlib"]:
        missing = await _check_availability(result["stdlib"])
        if missing:
            result["ok"] = False
            result["unavailable"] = missing
            result["errors"].append(
                "Not available in the client's runtime: " + ", ".join(missing)
            )

    if not using_bundled_interpreter():
        result["warnings"].append(
            "Validated against this machine's Python, not the client's bundled "
            "runtime - availability may differ until packaging is done."
        )

    return result


async def _compile_check(script: str) -> tuple[bool, str]:
    """Syntax-check with `py_compile` in the validating interpreter.

    A subprocess rather than a plain compile() call, so the check runs under
    the same interpreter version the client will use.
    """
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "candidate.py"
        source.write_text(script, encoding="utf-8")

        try:
            process = await asyncio.create_subprocess_exec(
                python_interpreter(), "-m", "py_compile", str(source),
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


# Resolves each module without importing it. find_spec walks the finders and
# returns metadata only — importing would execute the module's top-level code,
# which for a validation step is both unnecessary and unsafe.
_AVAILABILITY_PROBE = """
import importlib.util, json, sys

missing = []
for name in sys.argv[1:]:
    try:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    except (ImportError, ValueError, AttributeError):
        # A submodule whose parent is absent raises rather than returning None.
        missing.append(name)

print(json.dumps(missing))
"""


async def _check_availability(modules: list[str]) -> list[str]:
    """Which of `modules` the target runtime cannot resolve.

    Run inside the bundled interpreter so the answer reflects the client's
    actual module set — an embeddable distribution omits parts of the standard
    library, and this is the only way to find out which.
    """
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.py"
        probe.write_text(_AVAILABILITY_PROBE, encoding="utf-8")

        try:
            process = await asyncio.create_subprocess_exec(
                python_interpreter(), str(probe), *modules,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=VALIDATION_TIMEOUT
            )
        except (asyncio.TimeoutError, OSError):
            logger.warning("Availability probe failed; skipping that check",
                           exc_info=True)
            return []

    if process.returncode != 0:
        return []

    try:
        return json.loads(stdout.decode("utf-8", errors="replace") or "[]")
    except ValueError:
        return []


# ---------------------------------------------------------------------------
# PowerShell
# ---------------------------------------------------------------------------


def _validate_powershell(script: str) -> dict[str, Any]:
    """Parse-check PowerShell.

    Deliberately not a subprocess: invoking powershell.exe to check syntax
    risks *running* something if the invocation is got wrong, and the whole
    point is to validate without executing. Only balance-checking is done here;
    the client re-checks on arrival.

    No import policy applies — PowerShell ships with Windows and scripts use
    built-in cmdlets rather than importable packages.
    """
    unbalanced = _first_unbalanced(script)
    if unbalanced is not None:
        return _empty_result(False, [f"Unbalanced {unbalanced}"])
    return _empty_result(True)


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
