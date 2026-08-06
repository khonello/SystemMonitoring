"""Registry of live peer connections.

State is module-level rather than wrapped in a class, matching the functional
style the README asks for. All client sockets are multiplexed onto one event
loop thread, so no locking is needed — these dicts are only ever touched from
loop callbacks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from common.constants import ROLE_ADMIN, ROLE_CLIENT
from common.utils import utc_now_ts

logger = logging.getLogger(__name__)

# peer_id -> writer
_connections: dict[str, asyncio.StreamWriter] = {}

# peer_id -> {role, address, connected_at, last_seen, status}
_peer_info: dict[str, dict[str, Any]] = {}


def register(
    peer_id: str,
    writer: asyncio.StreamWriter,
    role: str,
    address: Any = None,
) -> None:
    """Add a peer to the registry, replacing any prior connection for it."""
    if peer_id in _connections:
        logger.warning("Peer %s reconnected; replacing previous connection", peer_id)

    now = utc_now_ts()
    _connections[peer_id] = writer
    _peer_info[peer_id] = {
        "role": role,
        "address": str(address) if address is not None else None,
        "connected_at": now,
        "last_seen": now,
        "status": "active",
    }
    logger.info("Registered %s '%s' (%d live)", role, peer_id, len(_connections))


def unregister(peer_id: str) -> None:
    """Remove a peer from the registry. Safe to call for unknown peers."""
    _connections.pop(peer_id, None)
    _peer_info.pop(peer_id, None)


def get_writer(peer_id: str) -> asyncio.StreamWriter | None:
    """Return a peer's writer, or None if it is not connected."""
    return _connections.get(peer_id)


def is_connected(peer_id: str) -> bool:
    return peer_id in _connections


def connection_count() -> int:
    return len(_connections)


def touch(peer_id: str) -> None:
    """Record that a peer was heard from just now."""
    info = _peer_info.get(peer_id)
    if info is not None:
        info["last_seen"] = utc_now_ts()


def set_status(peer_id: str, status: str) -> None:
    info = _peer_info.get(peer_id)
    if info is not None:
        info["status"] = status


def set_pause(peer_id: str, paused: bool, pause_until: str | None) -> None:
    """Record a client's pause state, as reported in its heartbeat.

    Live registry only, never the database: a pause is ephemeral, expires on
    its own, and only matters for a client that is currently connected.
    """
    info = _peer_info.get(peer_id)
    if info is not None:
        info["paused"] = paused
        info["pause_until"] = pause_until if paused else None


def get_pause(peer_id: str) -> dict[str, Any]:
    info = _peer_info.get(peer_id)
    if info is None:
        return {"paused": False, "pause_until": None}
    return {
        "paused": info.get("paused", False),
        "pause_until": info.get("pause_until"),
    }


def get_peer_ids(role: str | None = None) -> list[str]:
    """List connected peer ids, optionally filtered by role."""
    if role is None:
        return list(_connections)
    return [pid for pid, info in _peer_info.items() if info["role"] == role]


def get_client_ids() -> list[str]:
    return get_peer_ids(ROLE_CLIENT)


def get_admin_ids() -> list[str]:
    return get_peer_ids(ROLE_ADMIN)


def get_connected_clients() -> list[dict[str, Any]]:
    """Snapshot of connected Client Agents, for the admin's client list."""
    return [
        {"client_id": peer_id, **info}
        for peer_id, info in _peer_info.items()
        if info["role"] == ROLE_CLIENT
    ]


def find_stale(timeout: float) -> list[str]:
    """Peer ids that have sent nothing for longer than `timeout` seconds."""
    cutoff = utc_now_ts() - timeout
    return [pid for pid, info in _peer_info.items() if info["last_seen"] < cutoff]


def clear() -> None:
    """Drop all registry state. Used by tests between cases."""
    _connections.clear()
    _peer_info.clear()
