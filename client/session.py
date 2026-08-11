"""Which Windows session this process is in, and how to launch out of it.

Session 0 is reserved for services and has no display attached, so a window
drawn there reaches nobody. The agent is designed to run as a service, and it
also has to put the lockout overlay in front of a specific logged-in person —
two requirements that pull opposite ways (issues.md C11).

Two halves, and they are worth keeping apart:

- **Detection** (`current_session_id`, `warn_if_invisible`) makes the failure
  visible rather than silent. Correct regardless of anything below, and cheap.
- **Crossing** (`spawn_in_active_session`) launches into the interactive session
  from a service, which is the actual fix. **Untested — see issues.md C15.** It
  cannot run outside a real service: `WTSQueryUserToken` needs SYSTEM, and from
  an ordinary account the console session is already this one. Everything in it
  fails soft and returns None, so a caller falls back to an ordinary spawn.

Standard library only, via `ctypes`. `pywin32` is declared in
requirements-client.txt but is neither installed nor imported anywhere, and the
rest of the client reaches Win32 through `ctypes` — this follows that rather
than introducing the first real use of a dependency nobody has exercised.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

# Services always land here; the first interactive user gets 1, the next 2.
SERVICES_SESSION = 0

# CreateProcessAsUser flags and the desktop an interactive window belongs on.
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_NEW_CONSOLE = 0x00000010
_INTERACTIVE_DESKTOP = r"winsta0\default"

_MAXIMUM_ALLOWED = 0x02000000
_SECURITY_IMPERSONATION = 2
_TOKEN_PRIMARY = 1

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


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


# ---------------------------------------------------------------------------
# Crossing into the interactive session — issues.md C15, UNTESTED
# ---------------------------------------------------------------------------


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _last_error(call: str) -> str:
    code = ctypes.get_last_error()
    return f"{call} failed (WinError {code}: {ctypes.FormatError(code).strip()})"


def _win32():
    """Load the libraries and declare every prototype used below.

    Declaring `argtypes`/`restype` is not optional here. Without a `restype`,
    ctypes assumes `int` — so a 64-bit `HANDLE` comes back truncated and every
    later use of it fails in a way that looks like a permissions problem.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

    # Note this one lives in kernel32, not wtsapi32 despite the WTS prefix.
    kernel32.WTSGetActiveConsoleSessionId.argtypes = []
    kernel32.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    wtsapi32.WTSQueryUserToken.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    wtsapi32.WTSQueryUserToken.restype = wintypes.BOOL

    advapi32.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
        ctypes.c_int, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.DuplicateTokenEx.restype = wintypes.BOOL

    advapi32.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR,
        wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL, wintypes.DWORD,
        wintypes.LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW), ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    advapi32.CreateProcessAsUserW.restype = wintypes.BOOL

    userenv.CreateEnvironmentBlock.argtypes = [
        ctypes.POINTER(wintypes.LPVOID), wintypes.HANDLE, wintypes.BOOL,
    ]
    userenv.CreateEnvironmentBlock.restype = wintypes.BOOL
    userenv.DestroyEnvironmentBlock.argtypes = [wintypes.LPVOID]
    userenv.DestroyEnvironmentBlock.restype = wintypes.BOOL

    return kernel32, advapi32, userenv, wtsapi32


def spawn_in_active_session(argv: list[str]) -> int | None:
    """Start argv in the interactive session, as the logged-on user.

    This is what lets a session-0 service put a window on someone's screen. The
    sequence is fixed: find the console session, borrow that user's token,
    duplicate it into a primary token, build their environment, and create the
    process on `winsta0\default`.

    Returns:
        The new process id, or None if this could not be done — no console
        session, nobody logged in, insufficient privilege, or any API failure.
        **Every failure returns None and logs.** The caller falls back to an
        ordinary spawn, which is what happens today, so a fault here can never
        be the reason a lockout does not launch.

    UNTESTED beyond the failure paths (issues.md C15): the success path needs a
    real service in session 0 to execute at all.
    """
    if sys.platform != "win32":
        return None

    try:
        kernel32, advapi32, userenv, wtsapi32 = _win32()
    except (OSError, AttributeError):
        logger.warning("Session-crossing APIs unavailable", exc_info=True)
        return None

    session_id = kernel32.WTSGetActiveConsoleSessionId()
    if session_id == 0xFFFFFFFF:
        # No console session: nobody is logged in, or a session switch is in
        # progress. Not an error worth a traceback — there is nobody to show.
        logger.info("No active console session; nothing to display to")
        return None

    token = wintypes.HANDLE()
    if not wtsapi32.WTSQueryUserToken(session_id, ctypes.byref(token)):
        # The expected failure when not running as SYSTEM, which is every
        # invocation outside a service.
        logger.warning(_last_error("WTSQueryUserToken"))
        return None

    primary = wintypes.HANDLE()
    environment = wintypes.LPVOID()
    info = _PROCESS_INFORMATION()

    try:
        if not advapi32.DuplicateTokenEx(
            token, _MAXIMUM_ALLOWED, None,
            _SECURITY_IMPERSONATION, _TOKEN_PRIMARY, ctypes.byref(primary),
        ):
            logger.warning(_last_error("DuplicateTokenEx"))
            return None

        # Without the user's environment the child inherits the service's, which
        # resolves %APPDATA% and friends to the wrong profile. Not fatal, so it
        # degrades to a null block rather than aborting the launch.
        if not userenv.CreateEnvironmentBlock(ctypes.byref(environment), primary, False):
            logger.warning(_last_error("CreateEnvironmentBlock"))
            environment = wintypes.LPVOID()

        startup = _STARTUPINFOW()
        startup.cb = ctypes.sizeof(_STARTUPINFOW)
        # The window station and desktop the interactive user is looking at.
        # This one line is the difference between a window nobody sees and a
        # window on their screen.
        startup.lpDesktop = _INTERACTIVE_DESKTOP

        # CreateProcessAsUserW may write to the command line, so it has to be a
        # writable buffer rather than a Python string.
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))

        if not advapi32.CreateProcessAsUserW(
            primary, None, command, None, None, False,
            _CREATE_UNICODE_ENVIRONMENT | _CREATE_NEW_CONSOLE,
            environment, None, ctypes.byref(startup), ctypes.byref(info),
        ):
            logger.warning(_last_error("CreateProcessAsUserW"))
            return None

        logger.info(
            "Launched into session %s as the logged-on user (pid %s)",
            session_id, info.dwProcessId,
        )
        return int(info.dwProcessId)

    finally:
        if environment:
            userenv.DestroyEnvironmentBlock(environment)
        for handle in (info.hProcess, info.hThread, primary, token):
            if handle:
                kernel32.CloseHandle(handle)


def pid_is_running(pid: int) -> bool:
    """Whether a process id is still alive.

    Needed because a process started by `spawn_in_active_session` has no `Popen`
    to poll — the caller gets a bare pid back.
    """
    if sys.platform != "win32":
        return False

    try:
        kernel32, _, _, _ = _win32()
    except (OSError, AttributeError):
        return False

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False

    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
