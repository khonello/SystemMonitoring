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
from common.tls import default_cert_path, default_key_path

SERVER_HOST: Final[str] = os.environ.get("ENGINE_HOST", DEFAULT_ENGINE_HOST)
SERVER_PORT: Final[int] = int(os.environ.get("ENGINE_PORT", DEFAULT_ENGINE_PORT))

# SQLite file, bundled with the Engine rather than run as a separate service
# (README "Database"). Swapping to PostgreSQL is a change to database.py's
# internals, not to this setting's callers.
DATABASE_PATH: Final[Path] = Path(os.environ.get("ENGINE_DB", "monitoring.db"))

# Client Agents only. Admins are capped separately so that a lab at its client
# ceiling can still be administered — counting them together would refuse the
# operator exactly when they most need to connect.
MAX_CLIENTS: Final[int] = 50
MAX_ADMINS: Final[int] = 5

CLIENT_HEARTBEAT_TIMEOUT: Final[int] = HEARTBEAT_TIMEOUT

# How often the reaper sweeps for connections that have gone quiet.
REAP_INTERVAL: Final[int] = 15

# Monitoring data older than this is deleted. app_logs grows at roughly 230k
# rows per day per client, so something has to bound it; 30 days keeps the
# README's "weekly aggregated statistics" and "historical trend data" workable
# without unbounded growth. Set ENGINE_RETENTION_DAYS=0 to disable pruning.
RETENTION_DAYS: Final[int] = int(os.environ.get("ENGINE_RETENTION_DAYS", 30))

# How often the pruner runs. Six hours: often enough to keep each sweep small,
# rare enough to stay off the critical path.
PRUNE_INTERVAL: Final[int] = int(os.environ.get("ENGINE_PRUNE_INTERVAL", 6 * 60 * 60))

# Rows deleted per statement before yielding to the event loop. A single
# unbounded DELETE across millions of rows would block the Engine for as long
# as it took.
PRUNE_BATCH_SIZE: Final[int] = 5_000

LOG_LEVEL: Final[str] = os.environ.get("ENGINE_LOG_LEVEL", "INFO")

# --- TLS -------------------------------------------------------------------
#
# Presence-based rather than opt-in: once certificates exist, TLS is on. That
# way a deployment cannot end up plaintext because someone forgot a flag, and
# the only route to an unencrypted Engine is deleting the certificate or
# setting ENGINE_TLS=0 deliberately. Either way the startup log says which.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

TLS_CERT_PATH: Final[Path] = Path(
    os.environ.get("ENGINE_TLS_CERT", default_cert_path(_REPO_ROOT))
)
TLS_KEY_PATH: Final[Path] = Path(
    os.environ.get("ENGINE_TLS_KEY", default_key_path(_REPO_ROOT))
)

_tls_override: Final[str] = os.environ.get("ENGINE_TLS", "").strip().lower()

TLS_ENABLED: Final[bool] = (
    False if _tls_override in {"0", "false", "no", "off"}
    else True if _tls_override in {"1", "true", "yes", "on"}
    else TLS_CERT_PATH.exists()
)

# Read from the environment rather than written as a literal here, deliberately:
# README "Dev-Mode Auth Bypass" requires this to need per-run activation rather
# than being a setting that persists quietly in a config file and is forgotten.
#
#   Linux:    DEV_BYPASS_AUTH=1 python -m engine.main
#   Windows:  $env:DEV_BYPASS_AUTH=1; python -m engine.main
DEV_BYPASS_AUTH: Final[bool] = os.environ.get(
    "DEV_BYPASS_AUTH", ""
).strip().lower() in {"1", "true", "yes", "on"}
