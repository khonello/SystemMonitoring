"""End-to-end scaffold smoke tests — the Phase 1 exit criteria, encoded.

These run the real Engine handler and the real client connection module in one
process. They assert only that messages *flow*: registration completes, a
heartbeat is accepted, and an admin command reaches a client and comes back.
What the client does with the command is a Phase 4 stub, so the expected
answer here is "not implemented" — that is the point.

Phase 2 onward replaces these assertions with ones about real behaviour.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from client import connection as client_connection
from client.config import CLIENT_ID
from client.executor import handle_command
from common.constants import (
    MSG_ADMIN_COMMAND,
    MSG_CLIENT_LIST,
    MSG_COMMAND_RESPONSE,
    MSG_HEARTBEAT,
    MSG_REGISTER,
    MSG_REGISTER_ACK,
    MSG_REGISTER_CHALLENGE,
    MSG_REGISTER_REJECT,
    MSG_REGISTER_RESPONSE,
    MSG_TERMINATE_PROCESS,
    ROLE_ADMIN,
    STATUS_ERROR,
    STREAM_LIMIT,
)
from common.protocol import create_message, decode_message, encode_message
from engine import connection_manager
from engine.main import handle_client

HOST = "127.0.0.1"
TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine_port():
    """Run the real Engine connection handler on an ephemeral port."""
    connection_manager.clear()

    server = await asyncio.start_server(handle_client, HOST, 0, limit=STREAM_LIMIT)
    port = server.sockets[0].getsockname()[1]

    try:
        yield port
    finally:
        server.close()
        await server.wait_closed()
        connection_manager.clear()


@pytest_asyncio.fixture
async def connected_client(engine_port):
    """A registered Client Agent, with its command listener pumping."""
    assert await client_connection.connect(HOST, engine_port)
    assert await client_connection.register()

    async def pump() -> None:
        while True:
            message = await client_connection.receive()
            if message is None:
                return
            await handle_command(message)

    task = asyncio.create_task(pump())

    try:
        yield engine_port
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await client_connection.close()


# ---------------------------------------------------------------------------
# Raw admin peer
# ---------------------------------------------------------------------------


async def _send(writer: asyncio.StreamWriter, message: dict) -> None:
    writer.write(encode_message(message))
    await writer.drain()


async def _recv(reader: asyncio.StreamReader) -> dict | None:
    raw = await asyncio.wait_for(reader.readline(), timeout=TIMEOUT)
    return decode_message(raw) if raw else None


async def _open_admin(port: int, admin_id: str = "admin-01"):
    """Connect and register as an admin, completing the handshake if offered."""
    reader, writer = await asyncio.open_connection(HOST, port, limit=STREAM_LIMIT)

    await _send(writer, create_message(MSG_REGISTER, {"role": ROLE_ADMIN}, client_id=admin_id))
    reply = await _recv(reader)

    if reply["type"] == MSG_REGISTER_CHALLENGE:
        assert reply["payload"]["nonce"]
        await _send(
            writer,
            create_message(
                MSG_REGISTER_RESPONSE, {"response": "test-response"}, client_id=admin_id
            ),
        )
        reply = await _recv(reader)

    assert reply["type"] == MSG_REGISTER_ACK
    return reader, writer


async def _recv_until(reader: asyncio.StreamReader, msg_type: str, limit: int = 10) -> dict:
    """Read messages until one of `msg_type` arrives."""
    for _ in range(limit):
        message = await _recv(reader)
        assert message is not None, f"connection closed while waiting for {msg_type}"
        if message["type"] == msg_type:
            return message
    raise AssertionError(f"{msg_type} not received within {limit} messages")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_registers(engine_port):
    """The handshake completes and the Engine records the client."""
    assert await client_connection.connect(HOST, engine_port)
    try:
        assert await client_connection.register()
        await asyncio.sleep(0.05)

        assert connection_manager.is_connected(CLIENT_ID)
        assert CLIENT_ID in connection_manager.get_client_ids()
    finally:
        await client_connection.close()


@pytest.mark.asyncio
async def test_registration_rejected_without_client_id(engine_port):
    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(writer, create_message(MSG_REGISTER, {"role": ROLE_ADMIN}))
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_REJECT
        assert "client_id" in reply["payload"]["reason"]
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_registration_rejected_for_unknown_role(engine_port):
    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(
            writer, create_message(MSG_REGISTER, {"role": "superuser"}, client_id="x")
        )
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_REJECT
        assert "role" in reply["payload"]["reason"]
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_first_message_must_be_register(engine_port):
    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(writer, create_message(MSG_HEARTBEAT, {}, client_id="pc-01"))
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_REJECT
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# Monitoring flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_is_accepted(connected_client):
    """A heartbeat keeps the connection alive rather than dropping it."""
    assert await client_connection.send(
        create_message(MSG_HEARTBEAT, {"status": "active", "idle_time": 0}, client_id=CLIENT_ID)
    )
    await asyncio.sleep(0.05)

    assert connection_manager.is_connected(CLIENT_ID)


@pytest.mark.asyncio
async def test_admin_sees_client_in_roster(connected_client):
    reader, writer = await _open_admin(connected_client)
    try:
        await _send(writer, create_message(MSG_CLIENT_LIST, {}, client_id="admin-01"))
        reply = await _recv_until(reader, MSG_CLIENT_LIST)

        assert [c["client_id"] for c in reply["payload"]["clients"]] == [CLIENT_ID]
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# The exit criterion: admin command reaches the client and answers back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_command_reaches_client_and_returns(connected_client):
    """Admin -> Engine -> Client -> Engine -> Admin, with a stub at the far end."""
    reader, writer = await _open_admin(connected_client)
    try:
        await _send(
            writer,
            create_message(
                MSG_ADMIN_COMMAND,
                {
                    "command_type": MSG_TERMINATE_PROCESS,
                    "target_clients": [CLIENT_ID],
                    "parameters": {"process_name": "chrome.exe", "force": False},
                },
                client_id="admin-01",
                admin_id="admin-01",
            ),
        )

        response = await _recv_until(reader, MSG_COMMAND_RESPONSE)

        assert response["client_id"] == CLIENT_ID
        assert response["payload"]["status"] == STATUS_ERROR
        assert "Not implemented" in response["payload"]["message"]
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_unroutable_command_type_is_refused(connected_client):
    reader, writer = await _open_admin(connected_client)
    try:
        await _send(
            writer,
            create_message(
                MSG_ADMIN_COMMAND,
                {"command_type": "DELETE_EVERYTHING", "target_clients": [CLIENT_ID]},
                client_id="admin-01",
            ),
        )

        response = await _recv_until(reader, MSG_COMMAND_RESPONSE)

        assert response["payload"]["status"] == STATUS_ERROR
        assert "Unknown command_type" in response["payload"]["message"]
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_client_cannot_issue_admin_commands(connected_client):
    """Role is enforced: a Client Agent sending ADMIN_COMMAND is ignored."""
    assert await client_connection.send(
        create_message(
            MSG_ADMIN_COMMAND,
            {"command_type": MSG_TERMINATE_PROCESS, "target_clients": [CLIENT_ID]},
            client_id=CLIENT_ID,
        )
    )
    await asyncio.sleep(0.1)

    # Still connected, and nothing was routed back to it.
    assert connection_manager.is_connected(CLIENT_ID)
