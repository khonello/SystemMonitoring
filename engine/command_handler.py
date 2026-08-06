"""Inbound message dispatch and outbound command routing.

PHASE 1 SCAFFOLD. Every handler exists and is wired into `process_message`'s
dispatch table, but the monitoring handlers only log — persistence lands in
Phase 2, where each `# TODO(Phase 2)` becomes a call into engine.database.

Routing itself (admin -> client, and the broadcast fan-out) is implemented
rather than stubbed: it is plumbing, and the Phase 1 exit criteria require a
command to actually reach a client.
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
from engine import connection_manager
from engine.protocol import write_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inbound handlers - Client Agent monitoring data
# ---------------------------------------------------------------------------


async def handle_heartbeat(peer_id: str, payload: dict[str, Any]) -> None:
    """Record liveness. `touch` already ran in the read loop."""
    connection_manager.set_status(peer_id, payload.get("status", "active"))
    logger.debug("Heartbeat from %s (idle=%ss)", peer_id, payload.get("idle_time"))
    # TODO(Phase 2): database.update_client_last_seen(peer_id)


async def handle_app_data(peer_id: str, payload: dict[str, Any]) -> None:
    apps = payload.get("applications", [])
    logger.info("APP_DATA from %s: %d applications", peer_id, len(apps))
    # TODO(Phase 2): database.store_app_data(peer_id, apps)


async def handle_network_data(peer_id: str, payload: dict[str, Any]) -> None:
    logger.info(
        "NETWORK_DATA from %s: sent=%s recv=%s",
        peer_id,
        payload.get("bytes_sent"),
        payload.get("bytes_received"),
    )
    # TODO(Phase 2): database.store_network_data(peer_id, payload)


async def handle_usb_event(peer_id: str, payload: dict[str, Any]) -> None:
    logger.info(
        "USB_EVENT from %s: %s %s",
        peer_id,
        payload.get("event"),
        payload.get("device_name"),
    )
    # TODO(Phase 2): database.store_usb_event(peer_id, payload)


# ---------------------------------------------------------------------------
# Inbound handlers - command lifecycle, relayed back to admins
# ---------------------------------------------------------------------------


async def handle_command_response(peer_id: str, payload: dict[str, Any]) -> None:
    logger.info(
        "COMMAND_RESPONSE from %s for %s: %s",
        peer_id,
        payload.get("command_id"),
        payload.get("status"),
    )
    # TODO(Phase 2): database.update_command_status(...)
    await _relay_to_admins(MSG_COMMAND_RESPONSE, peer_id, payload)


async def handle_command_accepted(peer_id: str, payload: dict[str, Any]) -> None:
    logger.info("Script %s accepted by %s", payload.get("command_id"), peer_id)
    await _relay_to_admins(MSG_COMMAND_ACCEPTED, peer_id, payload)


async def handle_command_output(peer_id: str, payload: dict[str, Any]) -> None:
    """Stream a chunk of script output onward. Deliberately not persisted:
    the log file is per-execution scratch space (README "Script Execution
    Model")."""
    await _relay_to_admins(MSG_COMMAND_OUTPUT, peer_id, payload)


async def handle_command_complete(peer_id: str, payload: dict[str, Any]) -> None:
    logger.info(
        "Script %s finished on %s: rc=%s",
        payload.get("command_id"),
        peer_id,
        payload.get("returncode"),
    )
    # TODO(Phase 2): database.update_command_status(...)
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

    command_id = payload.get("command_id") or new_command_id()

    if not targets:
        delivered = await broadcast_command(command_type, parameters, command_id)
        logger.info("Broadcast %s as %s to %d clients", command_type, command_id, delivered)
        return

    for client_id in targets:
        await send_command_to_client(client_id, command_type, parameters, command_id)


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
) -> bool:
    """Send one command to one client. Returns False if it is not connected."""
    writer = connection_manager.get_writer(client_id)
    if writer is None:
        logger.error("Cannot send %s: client %s not connected", command_type, client_id)
        return False

    command = create_message(
        command_type,
        parameters,
        client_id=client_id,
        command_id=command_id or new_command_id(),
    )
    # TODO(Phase 2): database.log_command(...) before dispatch
    return await write_message(writer, command)


async def broadcast_command(
    command_type: str,
    parameters: dict[str, Any],
    command_id: str | None = None,
) -> int:
    """Send one command to every connected client. Returns the delivered count."""
    delivered = 0
    for client_id in connection_manager.get_client_ids():
        if await send_command_to_client(client_id, command_type, parameters, command_id):
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
