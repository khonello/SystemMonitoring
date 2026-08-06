"""Client Agent configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from common.constants import (
    APP_DATA_INTERVAL,
    DEFAULT_ENGINE_PORT,
    HEARTBEAT_INTERVAL,
    NETWORK_DATA_INTERVAL,
)
from common.utils import generate_client_id

ENGINE_HOST: Final[str] = os.environ.get("ENGINE_HOST", "127.0.0.1")
ENGINE_PORT: Final[int] = int(os.environ.get("ENGINE_PORT", DEFAULT_ENGINE_PORT))

CLIENT_ID: Final[str] = os.environ.get("CLIENT_ID") or generate_client_id()

MONITOR_INTERVAL: Final[int] = APP_DATA_INTERVAL
NETWORK_INTERVAL: Final[int] = NETWORK_DATA_INTERVAL
HEARTBEAT_SECONDS: Final[int] = HEARTBEAT_INTERVAL

LOG_LEVEL: Final[str] = os.environ.get("CLIENT_LOG_LEVEL", "INFO")

_PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parent

# The pinned, embeddable Python shipped inside the Client Agent installer.
# Script validation and execution must never fall back to a system-installed
# interpreter (README "Bundled Runtime & Script Validation"). Absent until the
# Phase 4 packaging step — check exists() before use.
BUNDLED_PYTHON_PATH: Final[Path] = _PACKAGE_DIR / "runtime" / "python.exe"

# The two on-demand helper executables. Both are spawned like scripts rather
# than run in-process, so neither can block the agent's event loop. Absent
# until the Phase 4 packaging step; the agent falls back to running the modules
# directly and says so loudly.
DIALOG_EXE_PATH: Final[Path] = _PACKAGE_DIR / "bin" / "labmonitor-dialog.exe"
OVERLAY_EXE_PATH: Final[Path] = _PACKAGE_DIR / "bin" / "labmonitor-overlay.exe"

# Security-sensitive local state: the derived auth key and the tamper-protected
# lockout schedule. %ProgramData%, never %APPDATA% — it must not be writable by
# the logged-in user (README "Local State").
STATE_DIR: Final[Path] = (
    Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "SystemMonitoring"
)

# Per-execution scratch space for script stdout/stderr. Cleared once each run
# reports COMMAND_COMPLETE (README "Script Execution Model").
SCRIPT_LOG_DIR: Final[Path] = _PACKAGE_DIR / "logs"
