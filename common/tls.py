"""TLS for the Engine's TCP listener and the two client types.

The transport was plain JSON over TCP, readable by anyone who could observe LAN
traffic — script contents, screen captures, lockout schedules. Authentication
(Phase 6) stops impersonation but does nothing about confidentiality; these are
separate problems and both need solving.

Design
------
**Self-signed, pinned.** There is one server — the Engine — and every client
gets an install package anyway, so a certificate authority buys nothing here.
Clients trust exactly the Engine's certificate and nothing else, which is
strictly narrower than trusting a CA that could sign others. The upgrade path
if certificate rotation ever becomes routine is a small internal CA; that is a
change to this module and the install step, not to any protocol.

**Identity is a fixed name, not an address.** The certificate is issued for
`labmonitor-engine`, and clients pass that as `server_hostname` while
connecting to whatever IP the Engine happens to have. Hostname verification
therefore stays ON — the usual reason people disable it is that the server's
address changes, and this sidesteps that without weakening anything. A lab
Engine on DHCP can move without reissuing certificates or touching clients.

**Fails loudly, not silently.** A missing or unreadable certificate raises
rather than quietly falling back to plaintext. Silent downgrade is how a
system ends up unencrypted in production while everyone believes otherwise.
"""

from __future__ import annotations

import logging
import os
import ssl
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

# The name the Engine's certificate is issued for. Clients present this as
# server_hostname regardless of the address they dial, so verification is
# pinned to the identity rather than to a possibly-changing IP.
TLS_IDENTITY: Final[str] = os.environ.get("LABMONITOR_TLS_IDENTITY", "labmonitor-engine")

# Default locations, relative to the repository root or install directory.
CERT_DIR_NAME: Final[str] = "certs"
CERT_FILE_NAME: Final[str] = "engine-cert.pem"
KEY_FILE_NAME: Final[str] = "engine-key.pem"

# TLS 1.2 floor. 1.3 is negotiated when both ends support it, which they do
# here — both are the same Python version by construction.
MINIMUM_VERSION: Final[ssl.TLSVersion] = ssl.TLSVersion.TLSv1_2


class TLSConfigurationError(Exception):
    """TLS was requested but cannot be set up."""


def default_cert_dir(base: Path) -> Path:
    return base / CERT_DIR_NAME


def default_cert_path(base: Path) -> Path:
    return default_cert_dir(base) / CERT_FILE_NAME


def default_key_path(base: Path) -> Path:
    return default_cert_dir(base) / KEY_FILE_NAME


def server_context(certfile: Path, keyfile: Path) -> ssl.SSLContext:
    """Build the Engine's TLS context.

    Raises:
        TLSConfigurationError: If the certificate or key is missing or invalid.
            Deliberately fatal — an Engine that silently served plaintext after
            being told to use TLS would be worse than one that refuses to start.
    """
    if not certfile.exists():
        raise TLSConfigurationError(
            f"Certificate not found: {certfile}. Generate one with "
            f"`python -m scripts.generate_cert`."
        )
    if not keyfile.exists():
        raise TLSConfigurationError(f"Private key not found: {keyfile}")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = MINIMUM_VERSION

    try:
        context.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    except (ssl.SSLError, OSError) as exc:
        raise TLSConfigurationError(f"Could not load {certfile}: {exc}") from exc

    logger.info("TLS enabled (certificate %s)", certfile)
    return context


def client_context(cafile: Path) -> ssl.SSLContext:
    """Build a client's TLS context, pinned to the Engine's certificate.

    `create_default_context` gives certificate verification and hostname
    checking on by default; passing the Engine's own certificate as the trust
    root means no other certificate is accepted, including one signed by a
    public CA.

    Raises:
        TLSConfigurationError: If the pinned certificate is missing or invalid.
    """
    if not cafile.exists():
        raise TLSConfigurationError(
            f"Engine certificate not found: {cafile}. Copy it from the Engine, "
            f"or run without TLS for local development."
        )

    try:
        context = ssl.create_default_context(cafile=str(cafile))
    except (ssl.SSLError, OSError) as exc:
        raise TLSConfigurationError(f"Could not load {cafile}: {exc}") from exc

    context.minimum_version = MINIMUM_VERSION

    # Both are already the defaults; set explicitly so that a future edit
    # weakening them is visible in the diff rather than implied by omission.
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    return context


def describe(enabled: bool, certfile: Path | None = None) -> str:
    """One line for the startup log, so the transport's state is never a guess."""
    if enabled:
        return f"TLS ENABLED - traffic encrypted (certificate {certfile})"
    return (
        "TLS DISABLED - traffic is plaintext and readable by anyone on this "
        "network. Acceptable for local development only."
    )
