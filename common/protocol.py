"""Message construction, serialisation and shape validation.

The wire format is newline-delimited JSON over TCP (README "Protocol Design").
json.dumps escapes newlines inside string values, so a serialised message can
never contain a bare b"\\n" of its own — the delimiter is unambiguous and a
readline()-based reader is safe.

This module is transport-agnostic: it turns messages into bytes and back.
Reading and writing those bytes over a stream lives in engine.protocol and
client.connection.
"""

from __future__ import annotations

import json
from typing import Any

from common.constants import ENCODING, MESSAGE_DELIMITER
from common.utils import utc_now_iso


class ProtocolError(ValueError):
    """A message could not be parsed, or failed envelope validation."""


def create_message(
    msg_type: str,
    payload: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build a protocol message.

    Args:
        msg_type: One of the MSG_* constants in common.constants.
        payload: Message-specific body. Defaults to an empty dict.
        **fields: Optional envelope fields such as client_id, command_id,
            admin_id or target_clients. Any passed as None are omitted.

    Returns:
        A message dict ready for encode_message.
    """
    message: dict[str, Any] = {
        "type": msg_type,
        "timestamp": utc_now_iso(),
        "payload": payload if payload is not None else {},
    }
    message.update({key: value for key, value in fields.items() if value is not None})
    return message


def encode_message(message: dict[str, Any]) -> bytes:
    """Serialise a message to a single delimited line of UTF-8 bytes.

    Raises:
        ProtocolError: If the message contains values JSON cannot represent.
    """
    try:
        line = json.dumps(message, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"Message is not JSON-serialisable: {exc}") from exc
    return line.encode(ENCODING) + MESSAGE_DELIMITER


def decode_message(raw: bytes) -> dict[str, Any]:
    """Parse one line of raw bytes into a validated message.

    Accepts the line with or without its trailing delimiter.

    Raises:
        ProtocolError: On bad encoding, malformed JSON, or a bad envelope.
    """
    try:
        text = raw.decode(ENCODING)
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"Message is not valid {ENCODING}: {exc}") from exc

    text = text.strip()
    if not text:
        raise ProtocolError("Empty message")

    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Malformed JSON: {exc}") from exc

    validate_message(message)
    return message


def validate_message(message: Any) -> None:
    """Check the envelope every message must have, regardless of type.

    Payload *contents* are the receiving handler's business; this only
    guarantees a handler can rely on `type` being a non-empty string and
    `payload` being a dict.

    Raises:
        ProtocolError: If the envelope is wrong.
    """
    if not isinstance(message, dict):
        raise ProtocolError(
            f"Expected a JSON object, got {type(message).__name__}"
        )

    msg_type = message.get("type")
    if not isinstance(msg_type, str) or not msg_type:
        raise ProtocolError("Message is missing a non-empty 'type'")

    payload = message.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError(
            f"'payload' must be an object, got {type(payload).__name__}"
        )


def get_payload(message: dict[str, Any]) -> dict[str, Any]:
    """Return a message's payload, defaulting to an empty dict."""
    payload = message.get("payload")
    return payload if isinstance(payload, dict) else {}
