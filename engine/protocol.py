"""Stream-level message framing for the Engine.

common.protocol turns messages into bytes and back; this module moves those
bytes over an asyncio stream pair.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from common.protocol import decode_message, encode_message

logger = logging.getLogger(__name__)


async def read_message(
    reader: asyncio.StreamReader,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    """Read one newline-delimited message.

    Returns:
        The decoded message, or None if the peer closed the connection cleanly.

    Raises:
        asyncio.TimeoutError: If `timeout` elapses first. Callers treat this as
            a dead peer, distinct from a clean close.
        ProtocolError: If the line is not a valid message. Callers generally
            log and continue rather than dropping the connection.
    """
    if timeout is None:
        raw = await reader.readline()
    else:
        raw = await asyncio.wait_for(reader.readline(), timeout=timeout)

    if not raw:
        return None

    return decode_message(raw)


async def write_message(
    writer: asyncio.StreamWriter,
    message: dict[str, Any],
) -> bool:
    """Send one message. Returns False if the peer has gone away."""
    try:
        writer.write(encode_message(message))
        await writer.drain()
        return True
    except (ConnectionError, RuntimeError) as exc:
        logger.error("Failed to send %s: %s", message.get("type"), exc)
        return False


async def close_writer(writer: asyncio.StreamWriter) -> None:
    """Close a writer, tolerating a peer that has already vanished."""
    try:
        writer.close()
        await writer.wait_closed()
    except (ConnectionError, RuntimeError):
        pass
