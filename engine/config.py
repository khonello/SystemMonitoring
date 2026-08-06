"""Engine configuration.

Values are read from the environment with sensible defaults so a deployment
can be retargeted without editing source.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from common.constants import (
    DEFAULT_ENGINE_HOST,
    DEFAULT_ENGINE_PORT,
    HEARTBEAT_TIMEOUT,
)

SERVER_HOST: Final[str] = os.environ.get("ENGINE_HOST", DEFAULT_ENGINE_HOST)
SERVER_PORT: Final[int] = int(os.environ.get("ENGINE_PORT", DEFAULT_ENGINE_PORT))

# SQLite file, bundled with the Engine rather than run as a separate service
# (README "Database"). Swapping to PostgreSQL is a change to database.py's
# internals, not to this setting's callers.
DATABASE_PATH: Final[Path] = Path(os.environ.get("ENGINE_DB", "monitoring.db"))

MAX_CLIENTS: Final[int] = 50

CLIENT_HEARTBEAT_TIMEOUT: Final[int] = HEARTBEAT_TIMEOUT

# How often the reaper sweeps for connections that have gone quiet.
REAP_INTERVAL: Final[int] = 15

LOG_LEVEL: Final[str] = os.environ.get("ENGINE_LOG_LEVEL", "INFO")

# Read from the environment rather than written as a literal here, deliberately:
# README "Dev-Mode Auth Bypass" requires this to need per-run activation rather
# than being a setting that persists quietly in a config file and is forgotten.
#
#   Linux:    DEV_BYPASS_AUTH=1 python -m engine.main
#   Windows:  $env:DEV_BYPASS_AUTH=1; python -m engine.main
DEV_BYPASS_AUTH: Final[bool] = os.environ.get(
    "DEV_BYPASS_AUTH", ""
).strip().lower() in {"1", "true", "yes", "on"}
