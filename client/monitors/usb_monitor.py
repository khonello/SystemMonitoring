"""USB device event collection.

PHASE 1 SCAFFOLD — yields nothing. Phase 4 fills this in.

Logging only: insertions are recorded, never blocked (README "USB Device
Monitoring").
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

EVENT_INSERTED: str = "inserted"
EVENT_REMOVED: str = "removed"


def poll_usb_events() -> list[dict[str, Any]]:
    """Return USB events observed since the previous poll.

    Returns:
        One dict per event: event, device_name, device_id, mount_point.
    """
    # TODO(Phase 4): Windows device notifications (WM_DEVICECHANGE via a
    #   message-only window, or a WMI __InstanceCreationEvent watcher). Both
    #   are synchronous, so call this via asyncio.to_thread like the others.
    return []


def get_idle_time() -> float:
    """Seconds since the last keyboard or mouse input.

    Lives here rather than in its own module because it shares the same
    Win32-input origin as device notifications.
    """
    # TODO(Phase 4): GetLastInputInfo via ctypes, subtract from GetTickCount.
    return 0.0
