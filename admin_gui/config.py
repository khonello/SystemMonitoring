"""Administrator GUI configuration.

Connection details are remembered in QSettings (the Windows registry under
HKCU) rather than a config file — ordinary app preferences, not the
security-sensitive state the Client Agent keeps under %ProgramData%.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Final

from common.constants import DEFAULT_ENGINE_PORT
from common.tls import default_cert_path

ORGANISATION: Final[str] = "SystemMonitoring"
APPLICATION: Final[str] = "LabMonitorAdmin"

DEFAULT_HOST: Final[str] = os.environ.get("ENGINE_HOST", "127.0.0.1")
DEFAULT_PORT: Final[int] = int(os.environ.get("ENGINE_PORT", DEFAULT_ENGINE_PORT))

# Identifies this operator's session to the Engine, and is what lands in
# command_log.admin_id for every dispatched command.
ADMIN_ID: Final[str] = os.environ.get("ADMIN_ID") or f"admin-{socket.gethostname()}"

LOG_LEVEL: Final[str] = os.environ.get("ADMIN_LOG_LEVEL", "INFO")

_PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parent

QML_DIR: Final[Path] = _PACKAGE_DIR / "qml"

# The pinned, embeddable Python bundled with the Admin installer, used to
# syntax-check scripts before they are sent. Must be built from the same pinned
# version as the Client Agent's bundle, or a script that validates here can
# still fail on a lab machine (README "Bundled Runtime & Script Validation").
BUNDLED_PYTHON_PATH: Final[Path] = _PACKAGE_DIR / "runtime" / "python.exe"

# How many live samples to keep per client in the dashboard. Bounded because
# the Engine relays every client's data to every admin.
MAX_LIVE_SAMPLES: Final[int] = 200

SETTINGS_HOST: Final[str] = "engine/host"
SETTINGS_PORT: Final[str] = "engine/port"

# --- TLS -------------------------------------------------------------------
#
# Same pinned Engine certificate the Client Agent uses. Presence-based, so an
# admin console cannot end up talking plaintext to a TLS Engine by omission.
_REPO_ROOT: Final[Path] = _PACKAGE_DIR.parent

TLS_CERT_PATH: Final[Path] = Path(
    os.environ.get("ADMIN_TLS_CERT", default_cert_path(_REPO_ROOT))
)

_tls_override: Final[str] = os.environ.get("ADMIN_TLS", "").strip().lower()

TLS_ENABLED: Final[bool] = (
    False if _tls_override in {"0", "false", "no", "off"}
    else True if _tls_override in {"1", "true", "yes", "on"}
    else TLS_CERT_PATH.exists()
)
