"""Engine connection: connect, register, send, receive, reconnect.

Module-level stream state, matching the functional style used throughout.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import socket
from typing import Any

from client.auth import compute_challenge_response
from client.config import CLIENT_ID, ENGINE_HOST, ENGINE_PORT
from common.constants import (
    MSG_REGISTER,
    MSG_REGISTER_ACK,
    MSG_REGISTER_CHALLENGE,
    MSG_REGISTER_REJECT,
    MSG_REGISTER_RESPONSE,
    RECONNECT_DELAY,
    RECONNECT_MAX_DELAY,
    REGISTRATION_TIMEOUT,
    ROLE_CLIENT,
    STREAM_LIMIT,
)
from common.protocol import (
    ProtocolError,
    create_message,
    decode_message,
    encode_message,
    get_payload,
)

logger = logging.getLogger(__name__)

_reader: asyncio.StreamReader | None = None
_writer: asyncio.StreamWriter | None = None


def is_connected() -> bool:
    return _writer is not None and not _writer.is_closing()


async def connect(host: str = ENGINE_HOST, port: int = ENGINE_PORT) -> bool:
    """Open a connection to the Engine."""
    global _reader, _writer

    try:
        _reader, _writer = await asyncio.open_connection(host, port, limit=STREAM_LIMIT)
    except OSError as exc:
        logger.error("Connection to %s:%s failed: %s", host, port, exc)
        _reader = _writer = None
        return False

    logger.info("Connected to Engine at %s:%s", host, port)
    return True


async def send(message: dict[str, Any]) -> bool:
    """Send one message to the Engine."""
    if _writer is None:
        logger.error("Cannot send %s: not connected", message.get("type"))
        return False

    try:
        _writer.write(encode_message(message))
        await _writer.drain()
        return True
    except (ConnectionError, RuntimeError) as exc:
        logger.error("Send failed: %s", exc)
        return False


async def receive(timeout: float | None = None) -> dict[str, Any] | None:
    """Read one message from the Engine.

    Returns None if the Engine closed the connection.

    Raises:
        asyncio.TimeoutError: If `timeout` elapses.
        ProtocolError: If the line is malformed.
    """
    if _reader is None:
        return None

    if timeout is None:
        raw = await _reader.readline()
    else:
        raw = await asyncio.wait_for(_reader.readline(), timeout=timeout)

    if not raw:
        return None

    return decode_message(raw)


async def register() -> bool:
    """Run the registration handshake.

    Two shapes are accepted, and which one occurs is the Engine's decision:
      - bypass active:  REGISTER -> REGISTER_ACK
      - handshake on:   REGISTER -> REGISTER_CHALLENGE -> REGISTER_RESPONSE -> ACK
    """
    hello = create_message(
        MSG_REGISTER,
        {
            "role": ROLE_CLIENT,
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "version": platform.version(),
        },
        client_id=CLIENT_ID,
    )
    if not await send(hello):
        return False

    try:
        reply = await receive(timeout=REGISTRATION_TIMEOUT)
    except (asyncio.TimeoutError, ProtocolError) as exc:
        logger.error("Registration failed awaiting Engine reply: %s", exc)
        return False

    if reply is None:
        logger.error("Engine closed the connection during registration")
        return False

    if reply.get("type") == MSG_REGISTER_CHALLENGE:
        nonce = get_payload(reply).get("nonce", "")
        answer = create_message(
            MSG_REGISTER_RESPONSE,
            {"response": compute_challenge_response(nonce)},
            client_id=CLIENT_ID,
        )
        if not await send(answer):
            return False

        try:
            reply = await receive(timeout=REGISTRATION_TIMEOUT)
        except (asyncio.TimeoutError, ProtocolError) as exc:
            logger.error("Registration failed awaiting ack: %s", exc)
            return False

        if reply is None:
            logger.error("Engine closed the connection after the challenge")
            return False

    if reply.get("type") == MSG_REGISTER_ACK:
        logger.info("Registered with Engine as %s", CLIENT_ID)
        return True

    if reply.get("type") == MSG_REGISTER_REJECT:
        logger.error("Engine rejected registration: %s", get_payload(reply).get("reason"))
        return False

    logger.error("Unexpected registration reply: %r", reply.get("type"))
    return False


async def close() -> None:
    """Close the connection, tolerating an Engine that already went away."""
    global _reader, _writer

    if _writer is not None:
        try:
            _writer.close()
            await _writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass

    _reader = _writer = None


def reconnect_delay(attempt: int) -> float:
    """Exponential backoff, capped (README "Performance Optimization")."""
    return float(min(RECONNECT_DELAY * (2 ** max(attempt - 1, 0)), RECONNECT_MAX_DELAY))
