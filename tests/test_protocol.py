"""Tests for common.protocol.

The protocol module is the one piece of Phase 1 with real logic rather than
stubs, so it gets real tests immediately.
"""

from __future__ import annotations

import json

import pytest

from common.constants import MESSAGE_DELIMITER, MSG_HEARTBEAT, MSG_REGISTER
from common.protocol import (
    ProtocolError,
    create_message,
    decode_message,
    encode_message,
    get_payload,
    validate_message,
)


# ---------------------------------------------------------------------------
# create_message
# ---------------------------------------------------------------------------


def test_create_message_has_required_envelope():
    message = create_message(MSG_HEARTBEAT, {"status": "active"})

    assert message["type"] == MSG_HEARTBEAT
    assert message["payload"] == {"status": "active"}
    assert message["timestamp"].endswith("Z")


def test_create_message_defaults_payload_to_empty_dict():
    assert create_message(MSG_HEARTBEAT)["payload"] == {}


def test_create_message_includes_supplied_envelope_fields():
    message = create_message(MSG_REGISTER, {}, client_id="pc-01", command_id="cmd_1")

    assert message["client_id"] == "pc-01"
    assert message["command_id"] == "cmd_1"


def test_create_message_omits_none_fields():
    """A None command_id must be absent, not present-and-null - handlers use
    `message.get("command_id")` and would otherwise read a null as a value."""
    message = create_message(MSG_REGISTER, {}, client_id="pc-01", command_id=None)

    assert "command_id" not in message


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_message():
    original = create_message(MSG_HEARTBEAT, {"status": "active", "idle_time": 12.5},
                              client_id="pc-01")

    assert decode_message(encode_message(original)) == original


def test_encoded_message_ends_with_delimiter():
    encoded = encode_message(create_message(MSG_HEARTBEAT))

    assert encoded.endswith(MESSAGE_DELIMITER)


def test_encoded_message_is_exactly_one_line():
    """Framing depends on this: json.dumps escapes newlines inside strings, so
    even payload text containing newlines must not split the line."""
    message = create_message(MSG_HEARTBEAT, {"chunk": "line one\nline two\r\nline three"})

    encoded = encode_message(message)

    assert encoded.count(MESSAGE_DELIMITER) == 1
    assert decode_message(encoded)["payload"]["chunk"] == "line one\nline two\r\nline three"


def test_decode_accepts_line_without_delimiter():
    encoded = encode_message(create_message(MSG_HEARTBEAT))

    assert decode_message(encoded.rstrip(MESSAGE_DELIMITER))["type"] == MSG_HEARTBEAT


def test_round_trip_preserves_non_ascii():
    message = create_message(MSG_HEARTBEAT, {"window_title": "Página — café"})

    assert decode_message(encode_message(message))["payload"]["window_title"] == "Página — café"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_encode_rejects_unserialisable_payload():
    with pytest.raises(ProtocolError, match="not JSON-serialisable"):
        encode_message(create_message(MSG_HEARTBEAT, {"when": object()}))


def test_decode_rejects_malformed_json():
    with pytest.raises(ProtocolError, match="Malformed JSON"):
        decode_message(b'{"type": "HEARTBEAT"')


def test_decode_rejects_empty_line():
    with pytest.raises(ProtocolError, match="Empty message"):
        decode_message(b"   \n")


def test_decode_rejects_invalid_utf8():
    with pytest.raises(ProtocolError, match="not valid utf-8"):
        decode_message(b"\xff\xfe\n")


def test_decode_rejects_non_object():
    with pytest.raises(ProtocolError, match="Expected a JSON object"):
        decode_message(b"[1, 2, 3]\n")


def test_decode_rejects_missing_type():
    with pytest.raises(ProtocolError, match="missing a non-empty 'type'"):
        decode_message(json.dumps({"payload": {}}).encode() + MESSAGE_DELIMITER)


def test_decode_rejects_empty_type():
    with pytest.raises(ProtocolError, match="missing a non-empty 'type'"):
        decode_message(json.dumps({"type": "", "payload": {}}).encode() + MESSAGE_DELIMITER)


def test_decode_rejects_non_object_payload():
    with pytest.raises(ProtocolError, match="'payload' must be an object"):
        decode_message(json.dumps({"type": "X", "payload": []}).encode() + MESSAGE_DELIMITER)


def test_validate_allows_missing_payload():
    """Payload is optional on the wire; handlers get {} via get_payload."""
    validate_message({"type": "X"})


# ---------------------------------------------------------------------------
# get_payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", [{"type": "X"}, {"type": "X", "payload": None},
                                     {"type": "X", "payload": "nope"}])
def test_get_payload_defaults_to_empty_dict(message):
    assert get_payload(message) == {}


def test_get_payload_returns_payload():
    assert get_payload({"type": "X", "payload": {"a": 1}}) == {"a": 1}
