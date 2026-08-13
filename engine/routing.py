"""Flows: the declared path each inbound message takes through the Engine.

This module is the *mechanism*. It knows how to run a flow — check the sender's
role, persist, hand off to a bespoke step, fan out — and how to narrate each hop
under one trace id. It does not know what any particular message means; the
routes themselves are declared in engine.command_handler, which is what keeps
this module free of any dependency on it.

Why a table rather than a handler per message
---------------------------------------------
Every telemetry handler used to end in the same two steps: write it down, then
push it to the admins. Written out longhand in each handler that pattern was
real but invisible — you could only learn a message's route by reading its
function body, nothing stated the contract, and nothing logged the hops in a
uniform way. When an admin stopped seeing a client's data there was no way to
tell "never arrived" from "arrived, stored, and the relay failed silently".

So a route declares the flow instead of implementing it:

    MSG_APP_DATA: Route(FLOW_TELEMETRY, CLIENTS, persist=..., relay_to=ROLE_ADMIN)

`dispatch` is then the single place that runs those steps, which is also the
single place that logs them. A message that goes missing now leaves a trail
naming the flow it was on and the step it died at.

Deliberately not a pipeline framework: stages are not registrable, there is no
middleware chain and flows do not compose. Three fixed steps in a fixed order
cover every message this protocol has, and a debugger stepping through
`dispatch` lands in real code rather than in an abstraction.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, NamedTuple

from common.constants import MAX_TRACE_ID_LENGTH, ROLE_ADMIN, ROLE_CLIENT, VALID_ROLES
from common.protocol import create_message, get_payload
from common.utils import new_trace_id
from engine import connection_manager
from engine.protocol import write_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flow names
# ---------------------------------------------------------------------------
#
# A flow is a shape, not a message type — several types share one. The name
# exists to be logged: it turns "APP_DATA went missing" into "APP_DATA went
# missing on the telemetry flow, after the persist step".

# Client reports something; the Engine stores it and shows it to the operators.
FLOW_TELEMETRY: str = "telemetry"

# Client reports on a command it was given; status is updated, admins told.
FLOW_LIFECYCLE: str = "lifecycle"

# Client output passing straight through to admins, stored nowhere. The log
# file on the client is the scratch space, and it is deleted on completion.
FLOW_STREAM: str = "stream"

# Admin asks the Engine a question and the Engine alone answers it. No client
# is involved and nothing leaves the Engine except the reply.
FLOW_QUERY: str = "query"

# Admin acts on clients. The only flow that fans out away from the Engine.
FLOW_DISPATCH: str = "dispatch"

# Liveness and presence bookkeeping, which relays only when something changed.
FLOW_PRESENCE: str = "presence"


# ---------------------------------------------------------------------------
# Route definition
# ---------------------------------------------------------------------------


class Context(NamedTuple):
    """Who sent the message being handled, and the trace it belongs to."""

    peer_id: str
    role: str
    trace_id: str


# Storage steps are synchronous by measurement, not oversight — see the note at
# the top of command_handler.py.
PersistFn = Callable[[str, dict[str, Any]], Any]
Handler = Callable[[Context, dict[str, Any]], Awaitable[None]]


class Route(NamedTuple):
    """One message type's declared path through the Engine.

    Steps run in order: `persist`, then `handler`, then the `relay_to` fan-out.
    Any of the three may be absent. A route with all three absent would be a
    message the Engine accepts and ignores, which is why none exists.

    Attributes:
        flow: One of the FLOW_* names, for logging and for reading the table.
        senders: Roles permitted to send this type. A message from any other
            role is refused before any step runs.
        persist: Synchronous storage step, called with (peer_id, payload).
        handler: Bespoke step for routes that need one, called with the
            Context and payload.
        relay_to: Role to forward the message on to, unchanged.
        relay_targets: Optional resolver from the sender's id to the exact peer
            ids that should receive the relay. Used by telemetry so a client's
            data reaches the admins watching it rather than all of them. Absent
            means every peer of `relay_to`, which stays right for anything an
            operator needs regardless of what they have selected.
    """

    flow: str
    senders: frozenset[str]
    persist: PersistFn | None = None
    handler: Handler | None = None
    relay_to: str | None = None
    relay_targets: Callable[[str], list[str]] | None = None


CLIENTS: frozenset[str] = frozenset({ROLE_CLIENT})
ADMINS: frozenset[str] = frozenset({ROLE_ADMIN})
ANY_PEER: frozenset[str] = VALID_ROLES


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


async def send_to_peer(peer_id: str, message: dict[str, Any]) -> bool:
    """Send one message to one connected peer. False if it has gone away."""
    writer = connection_manager.get_writer(peer_id)
    if writer is None:
        return False
    return await write_message(writer, message)


async def relay(
    msg_type: str,
    source_id: str,
    payload: dict[str, Any],
    role: str,
    trace_id: str,
    targets: list[str] | None = None,
) -> int:
    """Forward a message to peers of `role`. Returns how many received it.

    `targets` narrows the fan-out to an explicit set — used by the telemetry
    routes to reach only the admins watching this client, rather than every
    console connected (`issues.md` D5). Absent, every peer of the role gets it,
    which is still right for anything an operator needs whether or not they
    happen to have that machine selected.

    Failures are counted and logged rather than discarded. Previously this
    ignored the result of every send, so an admin whose socket had gone away
    stopped receiving telemetry with nothing anywhere saying so — the exact
    silent-drop this trace id exists to make visible.
    """
    message = create_message(msg_type, payload, client_id=source_id, trace_id=trace_id)

    if targets is None:
        targets = connection_manager.get_peer_ids(role)
    else:
        # A watcher that has since disconnected is not an error worth logging as
        # a relay failure: it is a stale subscription, and clear_watch tidies it
        # on disconnect anyway. Filtering here keeps the failure count meaning
        # "a live peer did not receive this".
        connected = set(connection_manager.get_peer_ids(role))
        targets = [peer for peer in targets if peer in connected]

    if not targets:
        logger.debug(
            "[%s] %s from %s relayed to nobody: no %s peer is watching it",
            trace_id, msg_type, source_id, role,
        )
        return 0

    failed: list[str] = []
    for peer_id in targets:
        if not await send_to_peer(peer_id, message):
            failed.append(peer_id)

    if failed:
        logger.error(
            "[%s] relay of %s from %s failed for %d of %d %s peers: %s",
            trace_id, msg_type, source_id, len(failed), len(targets), role,
            ", ".join(failed),
        )
    else:
        logger.debug(
            "[%s] relayed %s from %s to %d %s peers",
            trace_id, msg_type, source_id, len(targets), role,
        )

    return len(targets) - len(failed)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def trace_id_of(message: dict[str, Any]) -> str:
    """Take the message's trace id, or mint one.

    Honouring an inbound trace means a client that stamps its own messages gets
    one id spanning both components. It is peer-supplied text, so it is length
    bounded here rather than trusted into every log line downstream.
    """
    supplied = message.get("trace_id")
    if isinstance(supplied, str) and supplied.strip():
        return supplied.strip()[:MAX_TRACE_ID_LENGTH]
    return new_trace_id()


async def dispatch(
    routes: dict[str, Route],
    peer_id: str,
    role: str,
    message: dict[str, Any],
) -> None:
    """Run one inbound message through its declared flow.

    Every refusal and every step is logged against the message's trace id, so a
    message that produces no visible effect still produces an explanation.
    """
    msg_type = message.get("type", "")
    payload = get_payload(message)
    trace_id = trace_id_of(message)

    route = routes.get(msg_type)
    if route is None:
        logger.warning("[%s] no route for %r from %s", trace_id, msg_type, peer_id)
        return

    # Role is checked before any step runs, so a client cannot reach an
    # admin-only flow — nor an admin fabricate telemetry attributed to a client.
    if role not in route.senders:
        logger.error(
            "[%s] refused %s on flow %s: sender %s is a %s",
            trace_id, msg_type, route.flow, peer_id, role,
        )
        return

    logger.debug("[%s] %s: %s from %s", trace_id, route.flow, msg_type, peer_id)
    context = Context(peer_id=peer_id, role=role, trace_id=trace_id)

    if route.persist is not None:
        try:
            route.persist(peer_id, payload)
        except Exception:
            # The relay is still attempted. Losing a sample to a storage fault
            # should not also blank the operator's live view.
            logger.exception(
                "[%s] persist step failed for %s on flow %s", trace_id, msg_type, route.flow
            )

    if route.handler is not None:
        await route.handler(context, payload)

    if route.relay_to is not None:
        targets = route.relay_targets(peer_id) if route.relay_targets else None
        await relay(msg_type, peer_id, payload, route.relay_to, trace_id, targets)
