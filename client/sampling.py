"""How often this agent collects, and the fast rate used while it is watched.

The recording intervals (`MONITOR_INTERVAL`, `NETWORK_INTERVAL`) are what this
agent reports on normally, and they are what the Engine writes down. When an
operator selects this machine in the Admin console the Engine asks for a faster
rate, and the collection loops pick it up on their next pass.

Two rules this module exists to enforce, both about failing safe rather than
failing fast:

**Fast sampling expires by itself.** Every `SET_SAMPLE_RATE` carries a TTL, and
the Engine renews it while the watch is live. If the Engine dies, the network
drops, or the operator's machine is unplugged, this agent returns to its
recording intervals on its own. Without that, a vanished console could leave a
student's PC collecting every three seconds indefinitely — the same hazard the
indeterminate pause is capped against, and the same answer.

**Nothing here affects what is recorded.** The Engine persists every sample it
receives regardless of rate; this only changes how often one is produced, and
only for the machine somebody is actually looking at. The cost of fast sampling
lands on the monitored computer, which is exactly why it is scoped to a
selection rather than switched on for a fleet.
"""

from __future__ import annotations

import logging
import time

from client.config import MONITOR_INTERVAL, NETWORK_INTERVAL
from common.constants import (
    WATCH_APP_DATA_INTERVAL,
    WATCH_NETWORK_DATA_INTERVAL,
    WATCH_TTL,
)

logger = logging.getLogger(__name__)


# Monotonic deadline after which fast sampling lapses. Monotonic, not wall
# clock: a clock correction must not extend or cancel it, and this machine's
# clock is the one thing a lockout test deliberately fiddles with.
_fast_until: float = 0.0


def apply_command(payload: dict[str, object]) -> dict[str, str]:
    """Handle SET_SAMPLE_RATE. Returns a status result like every command."""
    global _fast_until

    fast = bool(payload.get("fast", False))
    if not fast:
        was_fast = is_fast()
        _fast_until = 0.0
        if was_fast:
            logger.info("Sampling: back to recording intervals")
        return {"status": "success", "message": "sampling at recording intervals"}

    try:
        ttl = int(payload.get("ttl", WATCH_TTL))
    except (TypeError, ValueError):
        ttl = WATCH_TTL

    # Bounded on arrival rather than trusted. A TTL of a day would defeat the
    # entire point of having one.
    ttl = max(1, min(ttl, WATCH_TTL))

    if not is_fast():
        logger.info("Sampling: fast mode for %ss (an operator is watching)", ttl)
    _fast_until = time.monotonic() + ttl
    return {"status": "success", "message": f"sampling fast for {ttl}s"}


def is_fast() -> bool:
    """True while fast sampling is in force and has not lapsed."""
    return time.monotonic() < _fast_until


def app_interval() -> int:
    """Seconds to wait before the next application collection."""
    return WATCH_APP_DATA_INTERVAL if is_fast() else MONITOR_INTERVAL


def network_interval() -> int:
    """Seconds to wait before the next network collection."""
    return WATCH_NETWORK_DATA_INTERVAL if is_fast() else NETWORK_INTERVAL


def reset() -> None:
    """Drop fast mode. For tests, and for a fresh agent process."""
    global _fast_until
    _fast_until = 0.0
