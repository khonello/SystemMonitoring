"""Flow dispatch, trace propagation and the offline-command outbox.

These cover the three things that were previously invisible: which flow a
message is on, whether its relay actually landed, and what happens to a command
issued while its client was away.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from common.constants import (
    MAX_TRACE_ID_LENGTH,
    MSG_ADMIN_COMMAND,
    MSG_APP_DATA,
    MSG_REPORT_REQUEST,
    MSG_SET_APP_BLACKLIST,
    MSG_TERMINATE_PROCESS,
    ROLE_ADMIN,
    ROLE_CLIENT,
)
from common.protocol import create_message, decode_message
from engine import connection_manager, database, routing
from engine.command_handler import (
    broadcast_command,
    flush_outbox,
    process_message,
    send_command_to_client,
)

CLIENT = "pc-01"
ADMIN = "admin-01"


@pytest.fixture(autouse=True)
def clear_registry():
    connection_manager.clear()
    yield
    connection_manager.clear()


def _capturing_writer() -> MagicMock:
    """A StreamWriter stand-in that decodes everything written to it."""
    writer = MagicMock()
    writer.sent = []
    writer.write = lambda raw: writer.sent.append(decode_message(raw))
    writer.drain = AsyncMock()
    return writer


def _broken_writer() -> MagicMock:
    """A peer whose socket has gone away mid-send."""
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock(side_effect=ConnectionResetError("gone"))
    return writer


def _connect_admin(writer: MagicMock | None = None) -> MagicMock:
    writer = writer or _capturing_writer()
    connection_manager.register(ADMIN, writer, ROLE_ADMIN)
    return writer


# ---------------------------------------------------------------------------
# The routing table
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_message_type_is_refused_with_a_reason(caplog):
    """An unrouted type is logged, not silently dropped."""
    with caplog.at_level(logging.WARNING, logger="engine.routing"):
        await process_message(CLIENT, ROLE_CLIENT, create_message("NOT_A_REAL_TYPE", {}))

    assert "no route for" in caplog.text


@pytest.mark.asyncio
async def test_an_admin_cannot_fabricate_telemetry():
    """APP_DATA is declared client-only, so an admin sending it is refused."""
    database.store_client(CLIENT, "host", "127.0.0.1", "Windows")

    await process_message(
        ADMIN,
        ROLE_ADMIN,
        create_message(MSG_APP_DATA, {"applications": [{"process_name": "chrome.exe"}]}),
    )

    assert database.get_client_apps(CLIENT) == []


@pytest.mark.asyncio
async def test_a_client_cannot_reach_an_admin_only_flow():
    """REPORT_REQUEST is admin-only: a client asking gets no answer at all."""
    writer = _capturing_writer()
    connection_manager.register(CLIENT, writer, ROLE_CLIENT)

    await process_message(
        CLIENT, ROLE_CLIENT, create_message(MSG_REPORT_REQUEST, {"report": "app_usage"})
    )

    assert writer.sent == []


@pytest.mark.asyncio
async def test_a_client_cannot_issue_an_admin_command():
    """The role gate that used to be a special case is now a table column."""
    target = _capturing_writer()
    connection_manager.register("pc-02", target, ROLE_CLIENT)

    await process_message(
        CLIENT,
        ROLE_CLIENT,
        create_message(
            MSG_ADMIN_COMMAND,
            {"command_type": MSG_TERMINATE_PROCESS, "target_clients": ["pc-02"]},
        ),
    )

    assert target.sent == []


@pytest.mark.asyncio
async def test_a_failed_persist_step_still_relays(monkeypatch):
    """Losing a sample to a storage fault must not blank the live view too."""
    monkeypatch.setattr(
        database, "store_app_data", MagicMock(side_effect=RuntimeError("disk full"))
    )
    admin = _connect_admin()

    await process_message(
        CLIENT,
        ROLE_CLIENT,
        create_message(MSG_APP_DATA, {"applications": [{"process_name": "chrome.exe"}]}),
    )

    assert [message["type"] for message in admin.sent] == [MSG_APP_DATA]


# ---------------------------------------------------------------------------
# Trace ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relayed_telemetry_carries_a_trace_id():
    database.store_client(CLIENT, "host", "127.0.0.1", "Windows")
    admin = _connect_admin()

    await process_message(
        CLIENT,
        ROLE_CLIENT,
        create_message(MSG_APP_DATA, {"applications": [{"process_name": "chrome.exe"}]}),
    )

    assert admin.sent[0]["trace_id"].startswith("trc_")


@pytest.mark.asyncio
async def test_a_supplied_trace_id_is_honoured():
    """One id spanning both components is the point of accepting an inbound one."""
    database.store_client(CLIENT, "host", "127.0.0.1", "Windows")
    admin = _connect_admin()

    message = create_message(MSG_APP_DATA, {"applications": []}, trace_id="trc_fromclient")
    await process_message(CLIENT, ROLE_CLIENT, message)

    assert admin.sent[0]["trace_id"] == "trc_fromclient"


def test_a_supplied_trace_id_is_length_bounded():
    """Peer-supplied text, so it is bounded before it reaches any log line."""
    trace_id = routing.trace_id_of({"trace_id": "x" * 500})

    assert len(trace_id) == MAX_TRACE_ID_LENGTH


def test_a_blank_trace_id_is_replaced_rather_than_propagated():
    assert routing.trace_id_of({"trace_id": "   "}).startswith("trc_")
    assert routing.trace_id_of({}).startswith("trc_")


# ---------------------------------------------------------------------------
# Relay failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_relay_is_counted_and_logged(caplog):
    """The silent drop this whole trace id exists to expose."""
    _connect_admin(_broken_writer())

    with caplog.at_level(logging.ERROR, logger="engine.routing"):
        delivered = await routing.relay(MSG_APP_DATA, CLIENT, {}, ROLE_ADMIN, "trc_test")

    assert delivered == 0
    assert "trc_test" in caplog.text
    assert ADMIN in caplog.text


@pytest.mark.asyncio
async def test_relay_reports_partial_delivery():
    """One dead admin must not stop the others being served."""
    connection_manager.register("admin-ok", _capturing_writer(), ROLE_ADMIN)
    connection_manager.register("admin-dead", _broken_writer(), ROLE_ADMIN)

    delivered = await routing.relay(MSG_APP_DATA, CLIENT, {}, ROLE_ADMIN, "trc_test")

    assert delivered == 1


# ---------------------------------------------------------------------------
# The outbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_durable_command_is_queued_for_an_absent_client():
    sent = await send_command_to_client(
        CLIENT, MSG_SET_APP_BLACKLIST, {"apps": ["game.exe"]}, admin_id=ADMIN
    )

    assert sent is False
    assert database.get_command_history(CLIENT)[0]["status"] == database.COMMAND_QUEUED


@pytest.mark.asyncio
async def test_a_transient_command_for_an_absent_client_is_not_queued():
    """A screen capture or a kill has a moment, and it has passed."""
    await send_command_to_client(CLIENT, MSG_TERMINATE_PROCESS, {}, admin_id=ADMIN)

    assert database.get_command_history(CLIENT)[0]["status"] == (
        database.COMMAND_UNDELIVERABLE
    )


@pytest.mark.asyncio
async def test_a_newer_queued_command_supersedes_the_earlier_one():
    """Durable commands declare state, so only the last one is worth replaying."""
    await send_command_to_client(CLIENT, MSG_SET_APP_BLACKLIST, {"apps": ["a.exe"]})
    await send_command_to_client(CLIENT, MSG_SET_APP_BLACKLIST, {"apps": ["b.exe"]})

    statuses = [entry["status"] for entry in database.get_command_history(CLIENT)]
    pending = database.take_queued_commands(CLIENT, 3600)

    assert sorted(statuses) == [database.COMMAND_QUEUED, database.COMMAND_SUPERSEDED]
    assert len(pending) == 1
    assert '"b.exe"' in pending[0]["command_data"]


@pytest.mark.asyncio
async def test_queued_commands_are_delivered_on_reconnect():
    await send_command_to_client(CLIENT, MSG_SET_APP_BLACKLIST, {"apps": ["game.exe"]})

    writer = _capturing_writer()
    connection_manager.register(CLIENT, writer, ROLE_CLIENT)
    delivered = await flush_outbox(CLIENT)

    assert delivered == 1
    assert writer.sent[0]["type"] == MSG_SET_APP_BLACKLIST
    assert writer.sent[0]["payload"] == {"apps": ["game.exe"]}
    assert database.get_command_history(CLIENT)[0]["status"] == (
        database.COMMAND_DISPATCHED
    )


@pytest.mark.asyncio
async def test_a_flush_that_fails_leaves_the_command_queued():
    """An optimistic status update would lose the command outright."""
    await send_command_to_client(CLIENT, MSG_SET_APP_BLACKLIST, {"apps": ["game.exe"]})

    connection_manager.register(CLIENT, _broken_writer(), ROLE_CLIENT)
    delivered = await flush_outbox(CLIENT)

    assert delivered == 0
    assert database.get_command_history(CLIENT)[0]["status"] == database.COMMAND_QUEUED


@pytest.mark.asyncio
async def test_queued_commands_expire():
    """A zero TTL stands in for a client that stayed away past the window."""
    await send_command_to_client(CLIENT, MSG_SET_APP_BLACKLIST, {"apps": ["game.exe"]})

    assert database.take_queued_commands(CLIENT, 0) == []
    assert database.get_command_history(CLIENT)[0]["status"] == database.COMMAND_EXPIRED


@pytest.mark.asyncio
async def test_nothing_queued_means_nothing_sent():
    writer = _capturing_writer()
    connection_manager.register(CLIENT, writer, ROLE_CLIENT)

    assert await flush_outbox(CLIENT) == 0
    assert writer.sent == []


@pytest.mark.asyncio
async def test_a_durable_broadcast_reaches_known_offline_clients():
    """"Apply this policy to the lab" should mean the machines that are off too."""
    database.store_client(CLIENT, "host", "127.0.0.1", "Windows")
    database.store_client("pc-02", "host2", "127.0.0.2", "Windows")
    connection_manager.register("pc-02", _capturing_writer(), ROLE_CLIENT)

    delivered = await broadcast_command(MSG_SET_APP_BLACKLIST, {"apps": ["game.exe"]})

    assert delivered == 1
    assert database.get_command_history(CLIENT)[0]["status"] == database.COMMAND_QUEUED


@pytest.mark.asyncio
async def test_a_transient_broadcast_stays_connected_only():
    database.store_client(CLIENT, "host", "127.0.0.1", "Windows")

    await broadcast_command(MSG_TERMINATE_PROCESS, {})

    assert database.get_command_history(CLIENT) == []
