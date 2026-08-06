"""Network usage collection."""

from __future__ import annotations

import logging
from typing import Any

import psutil

logger = logging.getLogger(__name__)


def collect_network_data() -> dict[str, Any]:
    """Sample network counters and connection count.

    The byte counters are cumulative since boot and are sent as-is. The Engine
    differences consecutive samples when reporting usage, and treats a drop as
    a reboot rather than negative traffic — so nothing here needs to track a
    baseline or reset anything.
    """
    counters = psutil.net_io_counters()

    return {
        "bytes_sent": counters.bytes_sent,
        "bytes_received": counters.bytes_recv,
        "packets_sent": counters.packets_sent,
        "packets_received": counters.packets_recv,
        "active_connections": _active_connections(),
    }


def _active_connections() -> int:
    """Count established connections.

    Needs elevation to see other users' sockets; without it psutil raises
    AccessDenied. Reporting 0 is better than failing the whole collection
    cycle over a number that is only indicative.
    """
    try:
        return sum(
            1 for conn in psutil.net_connections(kind="inet")
            if conn.status == psutil.CONN_ESTABLISHED
        )
    except (psutil.AccessDenied, PermissionError):
        logger.debug("Connection enumeration needs elevation; reporting 0")
        return 0
    except Exception:
        logger.debug("Connection enumeration failed", exc_info=True)
        return 0


def interface_status() -> dict[str, bool]:
    """Which network interfaces are currently up."""
    try:
        return {name: stats.isup for name, stats in psutil.net_if_stats().items()}
    except Exception:
        logger.debug("Interface enumeration failed", exc_info=True)
        return {}
