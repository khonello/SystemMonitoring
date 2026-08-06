"""USB device events and user idle time.

Logging only: insertions are recorded, never blocked (README "USB Device
Monitoring").

Detection is by polling the set of removable drives rather than subscribing to
WM_DEVICECHANGE. A message-only window would be more immediate, but it needs a
Win32 message pump running alongside the asyncio loop — a second event loop to
keep alive, for a class of event that happens a handful of times a day. Polling
on the existing 30s monitoring cycle is enough, and it stays a plain function
that can be called through asyncio.to_thread like the other collectors.
"""

from __future__ import annotations

import ctypes
import logging
import string
import sys
from ctypes import wintypes

from typing import Any

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

EVENT_INSERTED: str = "inserted"
EVENT_REMOVED: str = "removed"

DRIVE_REMOVABLE = 2

# Drives seen on the previous poll, so only changes are reported.
_known_drives: set[str] = set()


def poll_usb_events() -> list[dict[str, Any]]:
    """Return USB events observed since the previous call.

    The first call establishes the baseline and reports nothing — drives that
    were already plugged in before the agent started are not insertions.
    """
    global _known_drives

    if not IS_WINDOWS:
        return []

    try:
        current = _removable_drives()
    except Exception:
        logger.debug("Drive enumeration failed", exc_info=True)
        return []

    if not _known_drives and current:
        # Baseline: adopt whatever is already mounted without reporting it.
        _known_drives = current
        return []

    events = [
        {
            "event": EVENT_INSERTED,
            "device_name": _volume_label(drive),
            "device_id": drive,
            "mount_point": drive,
        }
        for drive in sorted(current - _known_drives)
    ]

    events.extend(
        {
            "event": EVENT_REMOVED,
            "device_name": "",
            "device_id": drive,
            "mount_point": drive,
        }
        for drive in sorted(_known_drives - current)
    )

    _known_drives = current
    return events


def reset_baseline() -> None:
    """Forget known drives. Used by tests."""
    global _known_drives
    _known_drives = set()


def _removable_drives() -> set[str]:
    """Drive letters currently presenting as removable media."""
    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()

    drives = set()
    for index, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << index):
            continue
        root = f"{letter}:\\"
        if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == DRIVE_REMOVABLE:
            drives.add(root)

    return drives


def _volume_label(root: str) -> str:
    """Volume label for a drive, or a usable fallback."""
    try:
        kernel32 = ctypes.windll.kernel32
        label = ctypes.create_unicode_buffer(261)

        ok = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), label, 261,
            None, None, None, None, 0,
        )
        if ok and label.value:
            return label.value
    except Exception:
        logger.debug("Volume label lookup failed for %s", root, exc_info=True)

    return f"Removable disk ({root.rstrip(chr(92))})"


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def get_idle_time() -> float:
    """Seconds since the last keyboard or mouse input.

    Lives here rather than in its own module because it shares the same
    Win32-input origin as device notifications.
    """
    if not IS_WINDOWS:
        return 0.0

    try:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0

        # Both are millisecond tick counts that wrap at 2^32; the subtraction
        # is masked so the answer stays correct across a wrap (~49.7 days).
        elapsed = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
        return elapsed / 1000.0
    except Exception:
        logger.debug("Idle time lookup failed", exc_info=True)
        return 0.0


def is_screen_locked() -> bool:
    """Whether the workstation is locked.

    Detected by asking for the input desktop: when the machine is locked, the
    secure desktop is active and the agent's session cannot open it.
    """
    if not IS_WINDOWS:
        return False

    try:
        user32 = ctypes.windll.user32
        desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not desktop:
            return True
        user32.CloseDesktop(desktop)
        return False
    except Exception:
        logger.debug("Lock state lookup failed", exc_info=True)
        return False
