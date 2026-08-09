"""What each message type means: the flow declarations and the steps they run.

engine.routing owns the mechanism — role checks, step ordering, trace logging,
fan-out. This module owns the policy: the `_ROUTES` table near the bottom is the
authoritative statement of how every inbound message travels, and the functions
above it are the individual steps that table refers to.

Read `_ROUTES` first. It is meant to answer "where does an APP_DATA go?" without
reading a single handler body.

Storage steps call engine.database, which owns every SQL statement in the
project. Those calls are synchronous and run directly on the event loop. That is
a measured decision, not an assumption: scripts/bench_database.py puts writes at
5-8ms each, which across 50 clients on their real collection intervals leaves
the loop blocked ~35ms per second — a 3.5% duty cycle. A thread would add
complexity for no gain at that level. If client count or collection frequency
grows, re-run the benchmark and wrap these calls in asyncio.to_thread;
database.py itself needs no change either way.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from common.constants import (
    CLIENT_COMMANDS,
    DURABLE_COMMANDS,
    MSG_ADMIN_COMMAND,
    MSG_APP_DATA,
    MSG_CLIENT_LIST,
    MSG_COMMAND_ACCEPTED,
    MSG_COMMAND_COMPLETE,
    MSG_COMMAND_OUTPUT,
    MSG_COMMAND_RESPONSE,
    MSG_HEARTBEAT,
    MSG_NETWORK_DATA,
    MSG_PAUSE_STATE,
    MSG_REPORT,
    MSG_REPORT_REQUEST,
    MSG_USB_EVENT,
    REPORT_APP_USAGE,
    REPORT_COMMAND_HISTORY,
    REPORT_NETWORK_24H,
    REPORT_NETWORK_WEEKLY,
    REPORT_USB_EVENTS,
    ROLE_ADMIN,
    STATUS_ERROR,
    STATUS_SUCCESS,
    VALID_REPORTS,
)
from common.protocol import create_message
from common.utils import new_command_id, new_trace_id
from engine import connection_manager, database, routing
from engine.config import OUTBOX_TTL
from engine.routing import (
    ADMINS,
    ANY_PEER,
    CLIENTS,
    FLOW_DISPATCH,
    FLOW_LIFECYCLE,
    FLOW_PRESENCE,
    FLOW_QUERY,
    FLOW_STREAM,
    FLOW_TELEMETRY,
    Context,
    Route,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persist steps — the storage half of a flow
# ---------------------------------------------------------------------------


def _persist_heartbeat(peer_id: str, payload: dict[str, Any]) -> None:
    """Refresh a client's liveness row. A no-op UPDATE for an admin peer."""
    database.update_client_last_seen(peer_id, payload.get("status", "active"))


def _persist_app_data(peer_id: str, payload: dict[str, Any]) -> None:
    stored = database.store_app_data(peer_id, payload.get("applications", []))
    logger.info("APP_DATA from %s: %d applications stored", peer_id, stored)


def _persist_network_data(peer_id: str, payload: dict[str, Any]) -> None:
    database.store_network_data(peer_id, payload)


def _persist_usb_event(peer_id: str, payload: dict[str, Any]) -> None:
    database.store_usb_event(peer_id, payload)


def _persist_command_response(peer_id: str, payload: dict[str, Any]) -> None:
    command_id = payload.get("command_id")
    if command_id:
        database.update_command_status(command_id, str(payload.get("status")))


def _persist_command_accepted(peer_id: str, payload: dict[str, Any]) -> None:
    command_id = payload.get("command_id")
    if command_id:
        database.update_command_status(command_id, "running")


def _persist_command_complete(peer_id: str, payload: dict[str, Any]) -> None:
    command_id = payload.get("command_id")
    if command_id:
        database.update_command_status(command_id, str(payload.get("status", "complete")))


# ---------------------------------------------------------------------------
# Handlers — steps that do not reduce to persist-then-relay
# ---------------------------------------------------------------------------


async def handle_heartbeat(context: Context, payload: dict[str, Any]) -> None:
    """Track presence, and tell admins when a client's pause state flips.

    Pause state is kept in the live registry rather than the database: it is
    ephemeral, self-expiring, and only ever interesting for clients that are
    currently connected. The relay is conditional, which is why this is a
    handler rather than a `relay_to` on the route.
    """
    peer_id = context.peer_id
    connection_manager.set_status(peer_id, payload.get("status", "active"))
    logger.debug(
        "[%s] heartbeat from %s (idle=%ss)", context.trace_id, peer_id, payload.get("idle_time")
    )

    was_paused = connection_manager.get_pause(peer_id).get("paused", False)
    now_paused = bool(payload.get("paused"))
    connection_manager.set_pause(peer_id, now_paused, payload.get("pause_until"))

    # Pushed the moment it changes, so a pause set from another console — or one
    # that lapsed on its own — shows up without waiting for a refresh.
    if was_paused != now_paused:
        await routing.relay(
            MSG_PAUSE_STATE,
            peer_id,
            {"paused": now_paused, "pause_until": payload.get("pause_until")},
            ROLE_ADMIN,
            context.trace_id,
        )


async def handle_admin_command(context: Context, payload: dict[str, Any]) -> None:
    """Route an ADMIN_COMMAND to its target clients."""
    command_type = payload.get("command_type", "")
    parameters = payload.get("parameters", {})
    targets = payload.get("target_clients") or []

    if command_type not in CLIENT_COMMANDS:
        logger.error(
            "[%s] admin %s sent unroutable command_type %r",
            context.trace_id, context.peer_id, command_type,
        )
        await _reply(
            context,
            MSG_COMMAND_RESPONSE,
            {"status": STATUS_ERROR, "message": f"Unknown command_type: {command_type!r}"},
        )
        return

    if not targets:
        delivered = await broadcast_command(
            command_type, parameters, admin_id=context.peer_id, trace_id=context.trace_id
        )
        logger.info("[%s] broadcast %s to %d clients", context.trace_id, command_type, delivered)
        return

    # An admin-supplied command_id is honoured only for a single target. Across
    # several it would name more than one execution, so each gets its own.
    supplied_id = payload.get("command_id")
    if supplied_id and len(targets) > 1:
        logger.warning(
            "[%s] ignoring supplied command_id %r: %d targets, each needs its own",
            context.trace_id, supplied_id, len(targets),
        )
        supplied_id = None

    for client_id in targets:
        await send_command_to_client(
            client_id,
            command_type,
            parameters,
            supplied_id,
            admin_id=context.peer_id,
            trace_id=context.trace_id,
        )


async def handle_client_list_request(context: Context, payload: dict[str, Any]) -> None:
    """Answer an admin's request for the current client roster.

    Merges the live registry with the database so clients that are known but
    currently offline still appear, rather than silently vanishing from the
    admin's list when they disconnect.
    """
    connected = {
        entry["client_id"]: entry for entry in connection_manager.get_connected_clients()
    }

    roster: list[dict[str, Any]] = []
    for stored in database.get_all_clients():
        client_id = stored["client_id"]
        live = connected.pop(client_id, None)
        roster.append({**stored, **(live or {}), "connected": live is not None})

    # Anything still connected but not yet written to the database.
    roster.extend({**entry, "connected": True} for entry in connected.values())

    await _reply(context, MSG_CLIENT_LIST, {"clients": roster})


_REPORT_QUERIES: dict[str, Callable[[str], Any]] = {
    REPORT_NETWORK_24H: lambda client_id: database.get_network_summary(client_id, hours=24),
    REPORT_NETWORK_WEEKLY: database.get_weekly_network_summary,
    REPORT_APP_USAGE: lambda client_id: database.get_app_usage_summary(client_id, hours=24),
    REPORT_USB_EVENTS: database.get_usb_events,
    REPORT_COMMAND_HISTORY: database.get_command_history,
}


async def handle_report_request(context: Context, payload: dict[str, Any]) -> None:
    """Run one aggregation query on an admin's behalf.

    Admins never touch the database directly — every read goes through the
    Engine, which is what keeps the storage layer swappable.
    """
    report = payload.get("report", "")
    client_id = payload.get("client_id", "")

    if report not in VALID_REPORTS:
        logger.error("[%s] admin %s requested unknown report %r",
                     context.trace_id, context.peer_id, report)
        await _reply(
            context,
            MSG_REPORT,
            {"report": report, "status": STATUS_ERROR, "message": f"Unknown report: {report!r}"},
        )
        return

    try:
        data = _REPORT_QUERIES[report](client_id)
    except Exception as exc:  # noqa: BLE001 - reported back, not swallowed
        logger.exception("[%s] report %s failed for %s", context.trace_id, report, client_id)
        await _reply(
            context,
            MSG_REPORT,
            {"report": report, "client_id": client_id,
             "status": STATUS_ERROR, "message": str(exc)},
        )
        return

    await _reply(
        context,
        MSG_REPORT,
        {"report": report, "client_id": client_id, "status": STATUS_SUCCESS, "data": data},
    )


async def _reply(context: Context, msg_type: str, payload: dict[str, Any]) -> bool:
    """Answer the peer that sent the message being handled, on its trace."""
    message = create_message(msg_type, payload, trace_id=context.trace_id)
    if await routing.send_to_peer(context.peer_id, message):
        return True
    logger.error(
        "[%s] could not answer %s with %s: peer has gone away",
        context.trace_id, context.peer_id, msg_type,
    )
    return False


# ---------------------------------------------------------------------------
# The routing table
# ---------------------------------------------------------------------------
#
# One row per inbound message type. Steps run persist -> handler -> relay_to;
# `senders` is enforced before any of them. Adding a message type means adding a
# row here, and a type absent from this table is refused with a logged reason
# rather than silently ignored.

_ROUTES: dict[str, Route] = {
    # Admins heartbeat exactly like clients — nothing else makes an idle Admin
    # GUI send traffic, and the reaper applies to every peer regardless of role.
    MSG_HEARTBEAT: Route(
        FLOW_PRESENCE, ANY_PEER, persist=_persist_heartbeat, handler=handle_heartbeat
    ),

    MSG_APP_DATA: Route(
        FLOW_TELEMETRY, CLIENTS, persist=_persist_app_data, relay_to=ROLE_ADMIN
    ),
    MSG_NETWORK_DATA: Route(
        FLOW_TELEMETRY, CLIENTS, persist=_persist_network_data, relay_to=ROLE_ADMIN
    ),
    MSG_USB_EVENT: Route(
        FLOW_TELEMETRY, CLIENTS, persist=_persist_usb_event, relay_to=ROLE_ADMIN
    ),

    MSG_COMMAND_RESPONSE: Route(
        FLOW_LIFECYCLE, CLIENTS, persist=_persist_command_response, relay_to=ROLE_ADMIN
    ),
    MSG_COMMAND_ACCEPTED: Route(
        FLOW_LIFECYCLE, CLIENTS, persist=_persist_command_accepted, relay_to=ROLE_ADMIN
    ),
    MSG_COMMAND_COMPLETE: Route(
        FLOW_LIFECYCLE, CLIENTS, persist=_persist_command_complete, relay_to=ROLE_ADMIN
    ),

    # Nothing stored: the client's log file is per-execution scratch space and
    # is deleted on completion (README "Script Execution Model").
    MSG_COMMAND_OUTPUT: Route(FLOW_STREAM, CLIENTS, relay_to=ROLE_ADMIN),

    MSG_CLIENT_LIST: Route(FLOW_QUERY, ADMINS, handler=handle_client_list_request),
    MSG_REPORT_REQUEST: Route(FLOW_QUERY, ADMINS, handler=handle_report_request),

    MSG_ADMIN_COMMAND: Route(FLOW_DISPATCH, ADMINS, handler=handle_admin_command),
}


async def process_message(peer_id: str, role: str, message: dict[str, Any]) -> None:
    """Dispatch one inbound message through its declared flow."""
    await routing.dispatch(_ROUTES, peer_id, role, message)


# ---------------------------------------------------------------------------
# Outbound routing
# ---------------------------------------------------------------------------


async def send_command_to_client(
    client_id: str,
    command_type: str,
    parameters: dict[str, Any],
    command_id: str | None = None,
    admin_id: str | None = None,
    trace_id: str | None = None,
) -> bool:
    """Send one command to one client. Returns False if it did not go out now.

    The command is recorded before dispatch, so an attempt that fails mid-write
    still leaves an audit trail rather than vanishing.

    A command for a client that is not connected does not simply fail. If it is
    one of DURABLE_COMMANDS it is queued for delivery on that client's next
    registration; anything else is a point-in-time action whose moment has
    passed, and is marked undeliverable as before. Either way the return is
    False — the caller asked for delivery now, and now did not happen.
    """
    resolved_id = command_id or new_command_id()
    trace = trace_id or new_trace_id()

    database.log_command(admin_id, client_id, resolved_id, command_type, parameters)

    writer = connection_manager.get_writer(client_id)
    if writer is None:
        if command_type in DURABLE_COMMANDS:
            database.queue_command(client_id, resolved_id, command_type)
            logger.info(
                "[%s] client %s absent: %s queued as %s",
                trace, client_id, command_type, resolved_id,
            )
        else:
            logger.error(
                "[%s] cannot send %s: client %s not connected", trace, command_type, client_id
            )
            database.update_command_status(resolved_id, database.COMMAND_UNDELIVERABLE)
        return False

    command = create_message(
        command_type,
        parameters,
        client_id=client_id,
        command_id=resolved_id,
        trace_id=trace,
    )
    if await routing.send_to_peer(client_id, command):
        return True

    logger.error("[%s] write of %s to %s failed", trace, command_type, client_id)
    database.update_command_status(resolved_id, database.COMMAND_UNDELIVERABLE)
    return False


async def broadcast_command(
    command_type: str,
    parameters: dict[str, Any],
    admin_id: str | None = None,
    trace_id: str | None = None,
) -> int:
    """Send one command to every client. Returns the count delivered now.

    Each client gets its own command_id, deliberately: a shared id would put
    duplicate rows in command_log, make update_command_status hit all of them
    at once, and leave TERMINATE_SCRIPT unable to name one execution.

    A durable command also targets clients that are known but offline, so they
    pick it up when they next register. "Apply this policy to the lab" should
    mean the whole lab, not just the machines that happened to be switched on.
    Transient commands stay connected-only — there is nothing useful to queue.
    """
    targets = list(connection_manager.get_client_ids())
    if command_type in DURABLE_COMMANDS:
        known = [entry["client_id"] for entry in database.get_all_clients()]
        targets = list(dict.fromkeys(targets + known))

    delivered = 0
    for client_id in targets:
        if await send_command_to_client(
            client_id, command_type, parameters, admin_id=admin_id, trace_id=trace_id
        ):
            delivered += 1
    return delivered


async def flush_outbox(client_id: str) -> int:
    """Deliver commands queued while `client_id` was away. Returns the count.

    Called once the client has registered and been acknowledged. A command is
    marked dispatched only after its write succeeds, so a client that drops
    mid-flush keeps the rest queued for next time.
    """
    pending = database.take_queued_commands(client_id, OUTBOX_TTL)
    if not pending:
        return 0

    delivered = 0
    for entry in pending:
        trace = new_trace_id()
        try:
            parameters = json.loads(entry["command_data"] or "{}")
        except json.JSONDecodeError:
            logger.exception(
                "[%s] queued command %s has unreadable parameters - discarding",
                trace, entry["command_id"],
            )
            database.update_command_status(entry["command_id"], STATUS_ERROR)
            continue

        command = create_message(
            entry["command_type"],
            parameters,
            client_id=client_id,
            command_id=entry["command_id"],
            trace_id=trace,
        )
        if not await routing.send_to_peer(client_id, command):
            logger.error(
                "[%s] outbox flush to %s stopped: peer went away", trace, client_id
            )
            break

        database.update_command_status(entry["command_id"], database.COMMAND_DISPATCHED)
        delivered += 1

    logger.info("Delivered %d queued command(s) to %s", delivered, client_id)
    return delivered
