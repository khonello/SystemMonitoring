"""Running-application collection.

PHASE 1 SCAFFOLD — returns an empty list. Phase 4 fills this in with psutil.

collect_process_data is SYNCHRONOUS on purpose. psutil.process_iter has no
async equivalent and can take a noticeable amount of time on a busy machine,
so it must be called via asyncio.to_thread and never awaited inline, or it
stalls the event loop and delays heartbeats (README "Concurrency Model").
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Noise that would otherwise dominate every batch.
IGNORED_PROCESSES: frozenset[str] = frozenset({
    "System",
    "System Idle Process",
    "svchost.exe",
})


def collect_process_data() -> list[dict[str, Any]]:
    """Enumerate running processes.

    Returns:
        One dict per process: process_name, pid, window_title, cpu_percent,
        memory_mb, start_time.
    """
    # TODO(Phase 4): psutil.process_iter over pid/name/cpu_percent/memory_info/
    #   create_time, skipping IGNORED_PROCESSES and swallowing NoSuchProcess /
    #   AccessDenied per process. Window titles need EnumWindows via ctypes.
    return []
