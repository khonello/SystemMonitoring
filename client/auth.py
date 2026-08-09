"""Client side of the registration handshake.

PHASE 1 SCAFFOLD, mirroring engine.auth. The client answers the Engine's nonce
challenge with a placeholder; Phase 7 swaps this one function body for a real
HMAC over the locally stored derived key. Because the message shape already
exists, that change touches nothing else.
"""

from __future__ import annotations

import logging

from client.config import STATE_DIR

logger = logging.getLogger(__name__)

# Provisioned per machine at install time as HMAC(master_secret, client_id) and
# stored ACL-restricted under %ProgramData%. Absent until Phase 7.
KEY_FILE = STATE_DIR / "client.key"

_PLACEHOLDER_RESPONSE = "phase1-unauthenticated"


def load_client_key() -> bytes | None:
    """Read this machine's derived key.

    Returns None in Phase 1, where no key has been provisioned.
    """
    # TODO(Phase 7): read KEY_FILE, verify ACLs, return the raw key.
    return None


def compute_challenge_response(nonce: str) -> str:
    """Answer the Engine's nonce challenge.

    PHASE 1 STUB: returns a fixed placeholder, which the Engine's matching stub
    accepts. Phase 7 replaces the body with:
        return hmac.new(load_client_key(), nonce.encode(), sha256).hexdigest()
    """
    logger.debug("Answering challenge with Phase 1 placeholder")
    return _PLACEHOLDER_RESPONSE
