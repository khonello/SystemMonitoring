"""Client Agent configuration."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Final

from common.constants import (
    APP_DATA_INTERVAL,
    DEFAULT_ENGINE_PORT,
    HEARTBEAT_INTERVAL,
    NETWORK_DATA_INTERVAL,
)
from common.tls import default_cert_path
from common.utils import generate_client_id

ENGINE_HOST: Final[str] = os.environ.get("ENGINE_HOST", "127.0.0.1")
ENGINE_PORT: Final[int] = int(os.environ.get("ENGINE_PORT", DEFAULT_ENGINE_PORT))

CLIENT_ID: Final[str] = os.environ.get("CLIENT_ID") or generate_client_id()

MONITOR_INTERVAL: Final[int] = APP_DATA_INTERVAL
NETWORK_INTERVAL: Final[int] = NETWORK_DATA_INTERVAL
HEARTBEAT_SECONDS: Final[int] = HEARTBEAT_INTERVAL

LOG_LEVEL: Final[str] = os.environ.get("CLIENT_LOG_LEVEL", "INFO")

# --- TLS -------------------------------------------------------------------
#
# The Engine's certificate, distributed with the client package. Public by
# design: pinning it is how the agent recognises the real Engine and refuses
# anything else, including a certificate signed by a public CA.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

TLS_CERT_PATH: Final[Path] = Path(
    os.environ.get("CLIENT_TLS_CERT", default_cert_path(_REPO_ROOT))
)

_tls_override: Final[str] = os.environ.get("CLIENT_TLS", "").strip().lower()

TLS_ENABLED: Final[bool] = (
    False if _tls_override in {"0", "false", "no", "off"}
    else True if _tls_override in {"1", "true", "yes", "on"}
    else TLS_CERT_PATH.exists()
)

_PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parent

# The pinned, embeddable Python shipped inside the Client Agent installer.
# Script validation and execution must never fall back to a system-installed
# interpreter (README "Bundled Runtime & Script Validation"). Absent until the
# Phase 8 packaging step — check exists() before use.
BUNDLED_PYTHON_PATH: Final[Path] = _PACKAGE_DIR / "runtime" / "python.exe"

# The two on-demand helper executables. Both are spawned like scripts rather
# than run in-process, so neither can block the agent's event loop. Absent
# until the Phase 8 packaging step; the agent falls back to running the modules
# directly and says so loudly.
DIALOG_EXE_PATH: Final[Path] = _PACKAGE_DIR / "bin" / "labmonitor-dialog.exe"
OVERLAY_EXE_PATH: Final[Path] = _PACKAGE_DIR / "bin" / "labmonitor-overlay.exe"

# Security-sensitive local state: the derived auth key and the tamper-protected
# lockout schedule. %ProgramData%, never %APPDATA% — it must not be writable by
# the logged-in user (README "Local State").
#
# ACLs are applied to this root and inherited, so a per-client directory created
# later is protected without a second icacls call.
STATE_ROOT: Final[Path] = (
    Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "SystemMonitoring"
)


def state_component(client_id: str) -> str:
    """Reduce a client id to one safe directory name.

    `CLIENT_ID` comes from the environment, so it reaches this unvalidated and
    must never be joined onto a path as-is — `../../Windows` would escape the
    state root entirely.

    Sanitising alone is not enough, because it is lossy: `lab1/pc-01` and
    `lab1_pc-01` both reduce to the same name, which would silently reunite two
    machines' state — the exact bug this directory split exists to prevent. The
    hash suffix restores distinctness, and being derived from the full original
    id it is stable across runs.
    """
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in client_id)
    safe = safe.strip("._-")[:40] or "client"
    digest = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}"


# Per client, not per machine. Several agents on one box would otherwise share
# one lockout schedule, one pause file and one cached blacklist, overwriting
# each other (issues.md B21).
#
# Anything reading this out of process — the watchdog under its Scheduled Task,
# the installer — must resolve the *same* client id, which is why both are given
# it explicitly rather than left to inherit an environment they do not get.
STATE_DIR: Final[Path] = STATE_ROOT / state_component(CLIENT_ID)

# Per-execution scratch space for script stdout/stderr. Cleared once each run
# reports COMMAND_COMPLETE (README "Script Execution Model").
SCRIPT_LOG_DIR: Final[Path] = _PACKAGE_DIR / "logs"
