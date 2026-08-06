"""Running-application collection.

collect_process_data is SYNCHRONOUS on purpose. psutil.process_iter has no
async equivalent and takes tens of milliseconds on a busy machine, so it must
be called via asyncio.to_thread and never awaited inline, or it stalls the
event loop and delays heartbeats (README "Concurrency Model").
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Any

import psutil

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# Noise that would otherwise dominate every batch. svchost in particular runs
# dozens of times over and says nothing about what a student is doing.
IGNORED_PROCESSES: frozenset[str] = frozenset({
    "System",
    "System Idle Process",
    "Registry",
    "Memory Compression",
    "svchost.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "smss.exe",
    "fontdrvhost.exe",
    "dwm.exe",
})


def collect_process_data() -> list[dict[str, Any]]:
    """Enumerate running processes with their resource usage.

    Returns:
        One dict per process: process_name, pid, window_title, cpu_percent,
        memory_mb, start_time.
    """
    titles = window_titles_by_pid()
    processes: list[dict[str, Any]] = []

    for proc in psutil.process_iter(
        ["pid", "name", "cpu_percent", "memory_info", "create_time"]
    ):
        try:
            info = proc.info
            name = info.get("name")
            if not name or name in IGNORED_PROCESSES:
                continue

            memory = info.get("memory_info")
            created = info.get("create_time")

            processes.append({
                "process_name": name,
                "pid": info["pid"],
                "window_title": titles.get(info["pid"], ""),
                "cpu_percent": info.get("cpu_percent") or 0.0,
                "memory_mb": round(memory.rss / (1024 * 1024), 1) if memory else 0.0,
                "start_time": _iso(created),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Processes die mid-iteration constantly, and a lab account cannot
            # see everything. Both are normal; skip and carry on.
            continue
        except Exception:
            logger.debug("Skipping a process that could not be read", exc_info=True)
            continue

    return processes


def _iso(created: float | None) -> str:
    if not created:
        return ""
    return (
        datetime.fromtimestamp(created, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def window_titles_by_pid() -> dict[int, str]:
    """Map process id to its visible top-level window title.

    psutil has no notion of windows, so this walks the Win32 window list
    directly. Returns an empty mapping off Windows, which keeps the collector
    usable for tests on any platform.
    """
    if not IS_WINDOWS:
        return {}

    try:
        return _enumerate_windows()
    except Exception:
        logger.debug("Window enumeration failed", exc_info=True)
        return {}


def _enumerate_windows() -> dict[int, str]:
    user32 = ctypes.windll.user32

    titles: dict[int, str] = {}

    # WNDENUMPROC: BOOL CALLBACK(HWND, LPARAM)
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def on_window(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # First visible titled window wins; a process with several windows
        # reports the one the OS lists first rather than an arbitrary later one.
        titles.setdefault(pid.value, buffer.value)
        return True

    user32.EnumWindows(callback_type(on_window), 0)
    return titles


def prime_cpu_percent() -> None:
    """Prime psutil's per-process CPU counters.

    psutil.cpu_percent measures between calls, so the very first reading for
    each process is always 0.0. Calling this once at startup means the first
    real batch carries usable numbers instead of a screen of zeroes.
    """
    for proc in psutil.process_iter(["pid"]):
        try:
            proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
