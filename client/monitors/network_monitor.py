"""Network usage collection.

PHASE 1 SCAFFOLD — returns zeroes. Phase 4 fills this in with psutil.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def collect_network_data() -> dict[str, Any]:
    """Sample cumulative network counters.

    Returns:
        bytes_sent, bytes_received, packets_sent, packets_received,
        active_connections.
    """
    # TODO(Phase 4): psutil.net_io_counters() and net_connections(). Counters
    #   are cumulative since boot, so the Engine stores samples and differences
    #   them when reporting - do not try to reset them here.
    return {
        "bytes_sent": 0,
        "bytes_received": 0,
        "packets_sent": 0,
        "packets_received": 0,
        "active_connections": 0,
    }
