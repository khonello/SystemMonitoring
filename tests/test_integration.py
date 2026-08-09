"""End-to-end tests: the real Engine handler and the real client and admin
connection modules, in one process.

Began as the Phase 1 exit criteria encoded as tests — that messages simply
*flow* — and grew with each phase rather than being replaced. It now also
covers registration and its refusals, capacity caps, telemetry reaching the
database, the command audit trail, a TLS round trip, the offline-command
outbox, and the stream limit at both ends of its range.

Anything asserting a client reply of "not implemented" is gone: the Client
Agent implements its commands as of Phase 4.
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
    MSG_SET_APP_BLACKLIST,
    MSG_TERMINATE_PROCESS,
    ROLE_ADMIN,
    ROLE_CLIENT,
    STATUS_ERROR,
    STREAM_LIMIT,
)
from common.protocol import create_message, decode_message, encode_message
from common.tls import CERT_FILE_NAME, KEY_FILE_NAME, TLS_IDENTITY, server_context
from engine import connection_manager, database
from engine.main import handle_client
from scripts.generate_cert import openssl_path

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
async def test_bypass_skips_the_handshake_entirely(engine_port, monkeypatch):
    """With the bypass on, no nonce is sent and no response is expected.

    This is the security-relevant distinction from a validation step that
    always passes: on the wire, bypassed traffic must look obviously different
    from working auth (README "Dev-Mode Auth Bypass").
    """
    monkeypatch.setattr("engine.main.is_auth_bypassed", lambda: True)

    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(writer, create_message(MSG_REGISTER, {"role": ROLE_ADMIN}, client_id="a1"))
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_ACK
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_failed_verification_is_rejected(engine_port, monkeypatch):
    """The Phase 1 stub accepts everything; when Phase 7 makes it discriminate,
    a wrong answer must close the door."""
    monkeypatch.setattr("engine.main.verify_challenge_response", lambda *_: False)

    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(writer, create_message(MSG_REGISTER, {"role": ROLE_ADMIN}, client_id="a1"))
        challenge = await _recv(reader)
        assert challenge["type"] == MSG_REGISTER_CHALLENGE

        await _send(
            writer, create_message(MSG_REGISTER_RESPONSE, {"response": "wrong"}, client_id="a1")
        )
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_REJECT
        assert "verification failed" in reply["payload"]["reason"]
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_wrong_message_instead_of_challenge_response(engine_port):
    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(writer, create_message(MSG_REGISTER, {"role": ROLE_ADMIN}, client_id="a1"))
        await _recv(reader)

        await _send(writer, create_message(MSG_HEARTBEAT, {}, client_id="a1"))
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_REJECT
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_malformed_registration_is_rejected(engine_port):
    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        writer.write(b"this is not json\n")
        await writer.drain()
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_REJECT
        assert "malformed" in reply["payload"]["reason"]
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_client_registration_refused_at_client_capacity(engine_port, monkeypatch):
    monkeypatch.setattr("engine.main.MAX_CLIENTS", 0)

    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(writer, create_message(MSG_REGISTER, {"role": ROLE_CLIENT}, client_id="pc-01"))
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_REJECT
        assert "client capacity" in reply["payload"]["reason"]
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_admin_registration_refused_at_admin_capacity(engine_port, monkeypatch):
    monkeypatch.setattr("engine.main.MAX_ADMINS", 0)

    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(writer, create_message(MSG_REGISTER, {"role": ROLE_ADMIN}, client_id="a1"))
        reply = await _recv(reader)

        assert reply["type"] == MSG_REGISTER_REJECT
        assert "admin capacity" in reply["payload"]["reason"]
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_admin_can_connect_when_clients_are_at_capacity(engine_port, monkeypatch):
    """The caps are separate so a full lab can still be administered — an
    operator must not be locked out exactly when they need to intervene."""
    monkeypatch.setattr("engine.main.MAX_CLIENTS", 0)

    reader, writer = await _open_admin(engine_port)
    writer.close()


@pytest.mark.asyncio
async def test_malformed_message_does_not_drop_the_connection(connected_client):
    """One bad line is logged and skipped; the peer stays registered."""
    reader, writer = await _open_admin(connected_client)
    try:
        writer.write(b"{not json at all}\n")
        await writer.drain()
        await asyncio.sleep(0.1)

        assert connection_manager.is_connected("admin-01")

        # And the connection still works afterwards.
        await _send(writer, create_message(MSG_CLIENT_LIST, {}, client_id="admin-01"))
        assert await _recv_until(reader, MSG_CLIENT_LIST)
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
    """Admin -> Engine -> Client -> Engine -> Admin, with real execution at the
    far end since Phase 4.

    A deliberately absent process is targeted so the assertion is about the
    round trip, not about what happens to be running on the test machine.
    """
    reader, writer = await _open_admin(connected_client)
    try:
        await _send(
            writer,
            create_message(
                MSG_ADMIN_COMMAND,
                {
                    "command_type": MSG_TERMINATE_PROCESS,
                    "target_clients": [CLIENT_ID],
                    "parameters": {"process_name": "no-such-process-xyz.exe"},
                },
                client_id="admin-01",
                admin_id="admin-01",
            ),
        )

        response = await _recv_until(reader, MSG_COMMAND_RESPONSE)

        assert response["client_id"] == CLIENT_ID
        assert response["payload"]["status"] == STATUS_ERROR
        assert "No process named" in response["payload"]["message"]
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


# ---------------------------------------------------------------------------
# TLS — the real client against the real Engine handler, encrypted
# ---------------------------------------------------------------------------
#
# The rest of this module runs plaintext deliberately (see conftest), because
# it is testing routing rather than transport. These two prove the encrypted
# path actually works end to end, and that pinning actually refuses an
# impostor — a TLS layer that accepts anything would pass every other test here.


def _generate_cert(directory):
    from scripts.generate_cert import generate

    assert generate(directory, days=1, identity=TLS_IDENTITY, force=True) == 0
    return directory / CERT_FILE_NAME, directory / KEY_FILE_NAME


@pytest.mark.asyncio
async def test_client_registers_over_tls(tmp_path_factory, monkeypatch):
    if openssl_path() is None:
        pytest.skip("openssl is required to generate a test certificate")

    certfile, keyfile = _generate_cert(tmp_path_factory.mktemp("tls-ok"))

    monkeypatch.setattr("client.connection.TLS_ENABLED", True)
    monkeypatch.setattr("client.connection.TLS_CERT_PATH", certfile)

    connection_manager.clear()
    server = await asyncio.start_server(
        handle_client, HOST, 0,
        limit=STREAM_LIMIT,
        ssl=server_context(certfile, keyfile),
    )
    port = server.sockets[0].getsockname()[1]

    try:
        assert await client_connection.connect(HOST, port)
        assert await client_connection.register()
        await asyncio.sleep(0.05)

        assert connection_manager.is_connected(CLIENT_ID)
    finally:
        await client_connection.close()
        server.close()
        await server.wait_closed()
        connection_manager.clear()


@pytest.mark.asyncio
async def test_client_refuses_an_engine_with_the_wrong_certificate(
    tmp_path_factory, monkeypatch
):
    """Pinning, exercised through the agent's own connect path rather than a
    bare socket: a machine impersonating the Engine gets refused."""
    if openssl_path() is None:
        pytest.skip("openssl is required to generate a test certificate")

    real_cert, _ = _generate_cert(tmp_path_factory.mktemp("tls-real"))
    fake_cert, fake_key = _generate_cert(tmp_path_factory.mktemp("tls-impostor"))

    # The agent trusts the real Engine; the server it reaches presents another.
    monkeypatch.setattr("client.connection.TLS_ENABLED", True)
    monkeypatch.setattr("client.connection.TLS_CERT_PATH", real_cert)

    server = await asyncio.start_server(
        handle_client, HOST, 0,
        limit=STREAM_LIMIT,
        ssl=server_context(fake_cert, fake_key),
    )
    port = server.sockets[0].getsockname()[1]

    try:
        assert await client_connection.connect(HOST, port) is False
    finally:
        await client_connection.close()
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# Persistence (Phase 2) — messages that arrive must reach the database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_persists_the_client(connected_client):
    stored = database.get_client(CLIENT_ID)

    assert stored is not None
    assert stored["status"] == "active"
    assert stored["ip_address"] == HOST


@pytest.mark.asyncio
async def test_app_data_is_persisted(connected_client):
    await client_connection.send(
        create_message(
            "APP_DATA",
            {
                "applications": [
                    {
                        "process_name": "chrome.exe",
                        "window_title": "Google Chrome",
                        "start_time": "2026-08-06T00:00:00.000Z",
                        "cpu_percent": 15.2,
                        "memory_mb": 450.5,
                    }
                ]
            },
            client_id=CLIENT_ID,
        )
    )
    await asyncio.sleep(0.1)

    stored = database.get_client_apps(CLIENT_ID)

    assert len(stored) == 1
    assert stored[0]["process_name"] == "chrome.exe"
    assert stored[0]["cpu_usage"] == 15.2


@pytest.mark.asyncio
async def test_network_data_is_persisted(connected_client):
    await client_connection.send(
        create_message(
            "NETWORK_DATA",
            {"bytes_sent": 1_048_576, "bytes_received": 5_242_880},
            client_id=CLIENT_ID,
        )
    )
    await asyncio.sleep(0.1)

    # A single sample yields no usage yet - deltas need two readings - but the
    # sample itself must have landed.
    assert database.get_network_summary(CLIENT_ID)["samples"] == 1


@pytest.mark.asyncio
async def test_usb_event_is_persisted(connected_client):
    await client_connection.send(
        create_message(
            "USB_EVENT",
            {"event": "inserted", "device_name": "USB Mass Storage"},
            client_id=CLIENT_ID,
        )
    )
    await asyncio.sleep(0.1)

    assert database.get_usb_events(CLIENT_ID)[0]["device_name"] == "USB Mass Storage"


@pytest.mark.asyncio
async def test_admin_command_is_audited_and_status_tracked(connected_client):
    """The dispatch is logged before it goes out, then updated by the reply."""
    reader, writer = await _open_admin(connected_client)
    try:
        await _send(
            writer,
            create_message(
                MSG_ADMIN_COMMAND,
                {
                    "command_type": MSG_TERMINATE_PROCESS,
                    "target_clients": [CLIENT_ID],
                    "parameters": {"process_name": "chrome.exe"},
                },
                client_id="admin-01",
            ),
        )
        await _recv_until(reader, MSG_COMMAND_RESPONSE)
        await asyncio.sleep(0.05)

        history = database.get_command_history(CLIENT_ID)

        assert len(history) == 1
        assert history[0]["admin_id"] == "admin-01"
        assert history[0]["command_type"] == MSG_TERMINATE_PROCESS
        # The client really did try and found no chrome.exe running, so it
        # answered with an error — and the audit row reflects the reply rather
        # than the dispatch. That round trip is the point of the test.
        assert history[0]["status"] == STATUS_ERROR
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_undeliverable_command_is_still_audited(connected_client):
    """A command for an absent client leaves a trail rather than vanishing."""
    reader, writer = await _open_admin(connected_client)
    try:
        await _send(
            writer,
            create_message(
                MSG_ADMIN_COMMAND,
                {
                    "command_type": MSG_TERMINATE_PROCESS,
                    "target_clients": ["pc-that-is-not-here"],
                    "parameters": {},
                },
                client_id="admin-01",
            ),
        )
        await asyncio.sleep(0.1)

        history = database.get_command_history("pc-that-is-not-here")

        assert history[0]["status"] == "undeliverable"
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_a_policy_set_while_offline_arrives_on_reconnect(engine_port):
    """The outbox flush is wired into registration, not merely callable.

    A blacklist set while the machine was switched off must be waiting for it
    the moment it comes back, before its first heartbeat.
    """
    database.store_client(CLIENT_ID, "host", HOST, "Windows")

    reader, writer = await _open_admin(engine_port)
    try:
        await _send(
            writer,
            create_message(
                MSG_ADMIN_COMMAND,
                {
                    "command_type": MSG_SET_APP_BLACKLIST,
                    "target_clients": [CLIENT_ID],
                    "parameters": {"apps": ["game.exe"]},
                },
                client_id="admin-01",
            ),
        )
        await asyncio.sleep(0.1)
        assert database.get_command_history(CLIENT_ID)[0]["status"] == (
            database.COMMAND_QUEUED
        )

        assert await client_connection.connect(HOST, engine_port)
        try:
            assert await client_connection.register()

            message = await asyncio.wait_for(client_connection.receive(), timeout=TIMEOUT)

            assert message["type"] == MSG_SET_APP_BLACKLIST
            assert message["payload"] == {"apps": ["game.exe"]}
            assert database.get_command_history(CLIENT_ID)[0]["status"] == (
                database.COMMAND_DISPATCHED
            )
        finally:
            await client_connection.close()
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_broadcast_gives_each_client_its_own_command_id(engine_port):
    """A shared id would duplicate audit rows and make status updates ambiguous."""
    assert await client_connection.connect(HOST, engine_port)
    try:
        assert await client_connection.register()
        reader, writer = await _open_admin(engine_port)
        try:
            await _send(
                writer,
                create_message(
                    MSG_ADMIN_COMMAND,
                    {"command_type": MSG_TERMINATE_PROCESS, "parameters": {}},
                    client_id="admin-01",
                ),
            )
            await asyncio.sleep(0.1)

            ids = [entry["command_id"] for entry in database.get_command_history()]

            assert len(ids) == len(set(ids))
        finally:
            writer.close()
    finally:
        await client_connection.close()


@pytest.mark.asyncio
async def test_disconnect_marks_the_client_offline(engine_port):
    assert await client_connection.connect(HOST, engine_port)
    assert await client_connection.register()
    await asyncio.sleep(0.05)
    assert database.get_client(CLIENT_ID)["status"] == "active"

    await client_connection.close()
    await asyncio.sleep(0.15)

    assert database.get_client(CLIENT_ID)["status"] == "offline"


# ---------------------------------------------------------------------------
# Stream limit
# ---------------------------------------------------------------------------
#
# Both ends open their streams with STREAM_LIMIT because asyncio caps a single
# line at 64KiB by default. Until now nothing had ever sent a message anywhere
# near either bound, so neither the working case nor the failure mode had been
# observed (issues.md B18).


@pytest.mark.asyncio
async def test_a_multi_megabyte_message_survives_the_stream_limit(connected_client):
    """Well past asyncio's 64KiB default line cap, well under STREAM_LIMIT.

    A base64 screen capture is the payload this exists for, so the test carries
    one shaped like it, relayed client -> Engine -> admin.
    """
    reader, writer = await _open_admin(connected_client)
    try:
        payload = "A" * (4 * 1024 * 1024)

        await client_connection.send(
            create_message(
                MSG_COMMAND_RESPONSE,
                {"command_id": "cmd_big", "status": "success", "image_base64": payload},
                client_id=CLIENT_ID,
            )
        )

        relayed = await _recv_until(reader, MSG_COMMAND_RESPONSE)

        assert relayed["payload"]["image_base64"] == payload
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_an_oversized_message_drops_the_peer_rather_than_hanging(engine_port):
    """Over the limit the reader raises, and the Engine must fail closed.

    Documents the failure mode rather than endorsing it: the client refuses to
    build a capture this large in the first place
    (test_capture_refuses_a_payload_over_the_message_budget), so reaching here
    means something else sent it.
    """
    reader, writer = await asyncio.open_connection(HOST, engine_port, limit=STREAM_LIMIT)
    try:
        await _send(
            writer, create_message(MSG_REGISTER, {"role": ROLE_CLIENT}, client_id="pc-big")
        )
        reply = await _recv(reader)
        if reply["type"] == MSG_REGISTER_CHALLENGE:
            await _send(
                writer,
                create_message(
                    MSG_REGISTER_RESPONSE, {"response": "test-response"}, client_id="pc-big"
                ),
            )
            reply = await _recv(reader)
        assert reply["type"] == MSG_REGISTER_ACK

        # One line comfortably past the 16MB ceiling.
        writer.write(b'{"type":"APP_DATA","payload":{"x":"' + b"A" * STREAM_LIMIT + b'"}}\n')
        await writer.drain()

        # The Engine drops the connection instead of leaving the peer waiting.
        assert await asyncio.wait_for(reader.read(), timeout=TIMEOUT) == b""
    finally:
        writer.close()
