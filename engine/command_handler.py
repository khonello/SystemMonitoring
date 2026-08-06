"""Inbound message dispatch and outbound command routing.

Handlers persist through engine.database, which owns every SQL statement in
the project.

Those calls are synchronous and run directly on the event loop. That is a
measured decision, not an assumption: scripts/bench_database.py puts writes at
5-8ms each, which across 50 clients on their real collection intervals leaves
the loop blocked ~35ms per second — a 3.5% duty cycle. A thread would add
complexity for no gain at that level. If client count or collection frequency
grows, re-run the benchmark and wrap these calls in asyncio.to_thread;
database.py itself needs no change either way.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from common.constants import (
    CLIENT_COMMANDS,
    MSG_ADMIN_COMMAND,
    MSG_APP_DATA,
    MSG_CLIENT_LIST,
    MSG_COMMAND_ACCEPTED,
    MSG_COMMAND_COMPLETE,
    MSG_COMMAND_OUTPUT,
    MSG_COMMAND_RESPONSE,
    MSG_HEARTBEAT,
    MSG_NETWORK_DATA,
    MSG_USB_EVENT,
    ROLE_ADMIN,
    STATUS_ERROR,
)
from common.protocol import create_message, get_payload
from common.utils import new_command_id
from engine import connection_manager, database
from engine.protocol import write_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inbound handlers - Client Agent monitoring data
# ---------------------------------------------------------------------------


async def handle_heartbeat(peer_id: str, payload: dict[str, Any]) -> None:
    """Record liveness. `touch` already ran in the read loop."""
    status = payload.get("status", "active")
    connection_manager.set_status(peer_id, status)
    logger.debug("Heartbeat from %s (idle=%ss)", peer_id, payload.get("idle_time"))
    database.update_client_last_seen(peer_id, status)


async def handle_app_data(peer_id: str, payload: dict[str, Any]) -> None:
    apps = payload.get("applications", [])
    stored = database.store_app_data(peer_id, apps)
    logger.info("APP_DATA from %s: %d applications stored", peer_id, stored)


async def handle_network_data(peer_id: str, payload: dict[str, Any]) -> None:
    logger.info(
        "NETWORK_DATA from %s: sent=%s recv=%s",
        peer_id,
        payload.get("bytes_sent"),
        payload.get("bytes_received"),
    )
    database.store_network_data(peer_id, payload)


async def handle_usb_event(peer_id: str, payload: dict[str, Any]) -> None:
    logger.info(
        "USB_EVENT from %s: %s %s",
        peer_id,
        payload.get("event"),
        payload.get("device_name"),
    )
    database.store_usb_event(peer_id, payload)


# ---------------------------------------------------------------------------
# Inbound handlers - command lifecycle, relayed back to admins
# ---------------------------------------------------------------------------


async def handle_command_response(peer_id: str, payload: dict[str, Any]) -> None:
    command_id = payload.get("command_id")
    status = payload.get("status")
    logger.info("COMMAND_RESPONSE from %s for %s: %s", peer_id, command_id, status)

    if command_id:
        database.update_command_status(command_id, str(status))

    await _relay_to_admins(MSG_COMMAND_RESPONSE, peer_id, payload)


async def handle_command_accepted(peer_id: str, payload: dict[str, Any]) -> None:
    command_id = payload.get("command_id")
    logger.info("Script %s accepted by %s", command_id, peer_id)

    if command_id:
        database.update_command_status(command_id, "running")

    await _relay_to_admins(MSG_COMMAND_ACCEPTED, peer_id, payload)


async def handle_command_output(peer_id: str, payload: dict[str, Any]) -> None:
    """Stream a chunk of script output onward. Deliberately not persisted:
    the log file is per-execution scratch space (README "Script Execution
    Model")."""
    await _relay_to_admins(MSG_COMMAND_OUTPUT, peer_id, payload)


async def handle_command_complete(peer_id: str, payload: dict[str, Any]) -> None:
    command_id = payload.get("command_id")
    logger.info(
        "Script %s finished on %s: rc=%s", command_id, peer_id, payload.get("returncode")
    )

    if command_id:
        database.update_command_status(command_id, str(payload.get("status", "complete")))

    await _relay_to_admins(MSG_COMMAND_COMPLETE, peer_id, payload)


# ---------------------------------------------------------------------------
# Inbound handlers - Admin GUI
# ---------------------------------------------------------------------------


async def handle_admin_command(peer_id: str, payload: dict[str, Any]) -> None:
    """Route an ADMIN_COMMAND to its target clients.

    Wired end-to-end in Phase 1 so a command genuinely reaches a client; what
    the client then *does* with it is the Phase 4 stub.
    """
    command_type = payload.get("command_type", "")
    parameters = payload.get("parameters", {})
    targets = payload.get("target_clients") or []

    if command_type not in CLIENT_COMMANDS:
        logger.error("Admin %s sent unroutable command_type %r", peer_id, command_type)
        await _send_to_peer(
            peer_id,
            create_message(
                MSG_COMMAND_RESPONSE,
                {
                    "status": STATUS_ERROR,
                    "message": f"Unknown command_type: {command_type!r}",
                },
            ),
        )
        return

    if not targets:
        delivered = await broadcast_command(command_type, parameters, admin_id=peer_id)
        logger.info("Broadcast %s to %d clients", command_type, delivered)
        return

    # An admin-supplied command_id is honoured only for a single target. Across
    # several it would name more than one execution, so each gets its own.
    supplied_id = payload.get("command_id")
    if supplied_id and len(targets) > 1:
        logger.warning(
            "Ignoring supplied command_id %r: %d targets, each needs its own",
            supplied_id,
            len(targets),
        )
        supplied_id = None

    for client_id in targets:
        await send_command_to_client(
            client_id, command_type, parameters, supplied_id, admin_id=peer_id
        )


async def handle_client_list_request(peer_id: str, payload: dict[str, Any]) -> None:
    """Answer an admin's request for the current client roster."""
    await _send_to_peer(
        peer_id,
        create_message(MSG_CLIENT_LIST, {"clients": connection_manager.get_connected_clients()}),
    )


# ---------------------------------------------------------------------------
# Outbound routing
# ---------------------------------------------------------------------------


async def send_command_to_client(
    client_id: str,
    command_type: str,
    parameters: dict[str, Any],
    command_id: str | None = None,
    admin_id: str | None = None,
) -> bool:
    """Send one command to one client. Returns False if it is not connected.

    The command is recorded before dispatch, so an attempt that fails mid-write
    still leaves an audit trail rather than vanishing.
    """
    resolved_id = command_id or new_command_id()

    database.log_command(admin_id, client_id, resolved_id, command_type, parameters)

    writer = connection_manager.get_writer(client_id)
    if writer is None:
        logger.error("Cannot send %s: client %s not connected", command_type, client_id)
        database.update_command_status(resolved_id, "undeliverable")
        return False

    command = create_message(
        command_type,
        parameters,
        client_id=client_id,
        command_id=resolved_id,
    )
    return await write_message(writer, command)


async def broadcast_command(
    command_type: str,
    parameters: dict[str, Any],
    admin_id: str | None = None,
) -> int:
    """Send one command to every connected client. Returns the delivered count.

    Each client gets its own command_id, deliberately: a shared id would put
    duplicate rows in command_log, make update_command_status hit all of them
    at once, and leave TERMINATE_SCRIPT unable to name one execution.
    """
    delivered = 0
    for client_id in connection_manager.get_client_ids():
        if await send_command_to_client(
            client_id, command_type, parameters, admin_id=admin_id
        ):
            delivered += 1
    return delivered


async def _send_to_peer(peer_id: str, message: dict[str, Any]) -> bool:
    writer = connection_manager.get_writer(peer_id)
    if writer is None:
        return False
    return await write_message(writer, message)


async def _relay_to_admins(
    msg_type: str,
    source_client_id: str,
    payload: dict[str, Any],
) -> None:
    """Forward a client-originated message to every connected admin."""
    message = create_message(msg_type, payload, client_id=source_client_id)
    for admin_id in connection_manager.get_peer_ids(ROLE_ADMIN):
        await _send_to_peer(admin_id, message)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

Handler = Callable[[str, dict[str, Any]], Any]

_HANDLERS: dict[str, Handler] = {
    MSG_HEARTBEAT: handle_heartbeat,
    MSG_APP_DATA: handle_app_data,
    MSG_NETWORK_DATA: handle_network_data,
    MSG_USB_EVENT: handle_usb_event,
    MSG_COMMAND_RESPONSE: handle_command_response,
    MSG_COMMAND_ACCEPTED: handle_command_accepted,
    MSG_COMMAND_OUTPUT: handle_command_output,
    MSG_COMMAND_COMPLETE: handle_command_complete,
    MSG_CLIENT_LIST: handle_client_list_request,
}

# ADMIN_COMMAND is intentionally absent from _HANDLERS: it is dispatched
# separately in process_message so that role can be checked first, stopping a
# Client Agent from issuing admin commands by sending the type itself.


async def process_message(
    peer_id: str,
    role: str,
    message: dict[str, Any],
) -> None:
    """Dispatch one inbound message to its handler."""
    msg_type = message.get("type", "")
    payload = get_payload(message)

    if msg_type == MSG_ADMIN_COMMAND:
        if role != ROLE_ADMIN:
            logger.error("Client %s attempted ADMIN_COMMAND - refused", peer_id)
            return
        await handle_admin_command(peer_id, payload)
        return

    handler = _HANDLERS.get(msg_type)
    if handler is None:
        logger.warning("Unknown message type %r from %s", msg_type, peer_id)
        return

    await handler(peer_id, payload)
