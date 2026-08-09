"""Registration authentication.

PHASE 1 SCAFFOLD — the handshake's *motions* are real (the Engine issues a
nonce, the peer answers, the answer is checked) but `verify_challenge_response`
is a stub that accepts anything. Phase 7 replaces that single function body
with real HMAC verification; no message shape and no call site changes.
That is the whole point of scaffolding it now (README "Scaffolding Auth:
Motions First, Logic Last").

Separately, DEV_BYPASS_AUTH skips the handshake *entirely* — no nonce is sent
and no response is expected. That is deliberately not the same thing as a
validation step that quietly always passes: a bypass that still emitted
auth-shaped traffic would be indistinguishable from working auth in a packet
capture, which is far more dangerous if the flag is left on by accident.
"""

from __future__ import annotations

import logging
import secrets

from engine.config import DEV_BYPASS_AUTH

logger = logging.getLogger(__name__)

BYPASS_BANNER: str = "AUTH BYPASS ACTIVE - DO NOT USE ON A REAL NETWORK"

NONCE_BYTES: int = 16


def is_auth_bypassed() -> bool:
    """Whether the handshake should be skipped outright."""
    return DEV_BYPASS_AUTH


def generate_nonce() -> str:
    """Generate a fresh challenge nonce.

    Real now rather than stubbed: a nonce only has to be unpredictable and
    single-use, neither of which depends on the Phase 7 key material.
    """
    return secrets.token_hex(NONCE_BYTES)


def verify_challenge_response(client_id: str, nonce: str, response: str) -> bool:
    """Check a peer's answer to the nonce challenge.

    PHASE 1 STUB: accepts anything, so the handshake round-trip can be
    exercised during integration testing before key material exists.

    Phase 7 replaces the body with:
        derived_key = hmac.new(master_secret, client_id.encode(), sha256).digest()
        expected = hmac.new(derived_key, nonce.encode(), sha256).hexdigest()
        return hmac.compare_digest(expected, response)

    Use compare_digest, not ==, when that lands.

    Args:
        client_id: The identity the peer claims.
        nonce: The nonce this Engine issued for this connection.
        response: The peer's answer.

    Returns:
        True if the peer may register as client_id.
    """
    logger.debug(
        "Auth stub accepting %s (response=%r) - real check lands in Phase 7",
        client_id,
        response[:16],
    )
    return True


def log_auth_state() -> None:
    """Announce the auth posture at startup, loudly when bypassed."""
    if DEV_BYPASS_AUTH:
        logger.warning("=" * 64)
        logger.warning(BYPASS_BANNER)
        logger.warning("=" * 64)
    else:
        logger.info(
            "Auth handshake enabled (verification is a Phase 1 stub - "
            "accepts any response)"
        )
