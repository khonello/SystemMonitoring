#!/usr/bin/env python3
"""Engine entry point — connection lifecycle and the registration handshake.

    python -m engine.main

Linux only in production: asyncio here is backed by epoll (README "Target
Environment"). It will run on Windows for development, on the selector loop.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from common.constants import (
    MSG_REGISTER,
    MSG_REGISTER_ACK,
    MSG_REGISTER_CHALLENGE,
    MSG_REGISTER_REJECT,
    MSG_REGISTER_RESPONSE,
    REGISTRATION_TIMEOUT,
    ROLE_CLIENT,
    STREAM_LIMIT,
    VALID_ROLES,
)
from common.protocol import ProtocolError, create_message, get_payload
from engine import connection_manager, database
from engine.auth import (
    generate_nonce,
    is_auth_bypassed,
    log_auth_state,
    verify_challenge_response,
)
from engine.command_handler import process_message
from engine.config import (
    CLIENT_HEARTBEAT_TIMEOUT,
    LOG_LEVEL,
    MAX_CLIENTS,
    REAP_INTERVAL,
    SERVER_HOST,
    SERVER_PORT,
)
from engine.protocol import close_writer, read_message, write_message

logger = logging.getLogger(__name__)

# Created lazily rather than at import. asyncio.Event.wait() binds the event to
# whichever loop first awaits it and raises RuntimeError from any other, so an
# import-time Event survives exactly one asyncio.run() — fine in production,
# but it makes every test after the first fail.
_shutdown: asyncio.Event | None = None


def _get_shutdown() -> asyncio.Event:
    """The shutdown event for the running loop, created on first use."""
    global _shutdown
    if _shutdown is None:
        _shutdown = asyncio.Event()
    return _shutdown


def request_shutdown() -> None:
    """Ask the Engine to stop serving."""
    _get_shutdown().set()


def reset_shutdown() -> None:
    """Discard the event so the next loop gets a fresh one. Used by tests."""
    global _shutdown
    _shutdown = None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def _reject(writer: asyncio.StreamWriter, reason: str) -> None:
    logger.error("Registration rejected: %s", reason)
    await write_message(writer, create_message(MSG_REGISTER_REJECT, {"reason": reason}))


async def perform_registration(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    address: Any,
) -> tuple[str, str, dict[str, Any]] | None:
    """Run the registration handshake.

    Returns:
        (peer_id, role, payload) on success, None if the peer was rejected.
        The payload carries the hostname and OS the peer reported, which the
        caller persists.
    """
    try:
        message = await read_message(reader, timeout=REGISTRATION_TIMEOUT)
    except asyncio.TimeoutError:
        await _reject(writer, "registration timed out")
        return None
    except ProtocolError as exc:
        await _reject(writer, f"malformed registration: {exc}")
        return None

    if message is None:
        logger.info("Peer at %s disconnected before registering", address)
        return None

    if message.get("type") != MSG_REGISTER:
        await _reject(writer, f"expected {MSG_REGISTER}, got {message.get('type')!r}")
        return None

    registration_payload = get_payload(message)
    peer_id = message.get("client_id")
    if not peer_id or not isinstance(peer_id, str):
        await _reject(writer, "missing client_id")
        return None

    role = registration_payload.get("role", ROLE_CLIENT)
    if role not in VALID_ROLES:
        await _reject(writer, f"invalid role {role!r}")
        return None

    if connection_manager.connection_count() >= MAX_CLIENTS:
        await _reject(writer, "server at capacity")
        return None

    # A hard, visible skip of the whole handshake - no nonce is sent and no
    # response is expected. Deliberately not a validation step that quietly
    # passes; see engine.auth for why that distinction matters.
    if is_auth_bypassed():
        logger.warning("Registered %s WITHOUT handshake (bypass active)", peer_id)
        return peer_id, role, registration_payload

    nonce = generate_nonce()
    if not await write_message(
        writer, create_message(MSG_REGISTER_CHALLENGE, {"nonce": nonce}, client_id=peer_id)
    ):
        return None

    try:
        reply = await read_message(reader, timeout=REGISTRATION_TIMEOUT)
    except asyncio.TimeoutError:
        await _reject(writer, "challenge response timed out")
        return None
    except ProtocolError as exc:
        await _reject(writer, f"malformed challenge response: {exc}")
        return None

    if reply is None:
        logger.info("Peer %s disconnected mid-handshake", peer_id)
        return None

    if reply.get("type") != MSG_REGISTER_RESPONSE:
        await _reject(writer, f"expected {MSG_REGISTER_RESPONSE}, got {reply.get('type')!r}")
        return None

    response = get_payload(reply).get("response", "")
    if not verify_challenge_response(peer_id, nonce, response):
        await _reject(writer, "challenge verification failed")
        return None

    return peer_id, role, registration_payload


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Serve one peer for the life of its connection."""
    address = writer.get_extra_info("peername")
    logger.info("Connection from %s", address)

    registration = await perform_registration(reader, writer, address)
    if registration is None:
        await close_writer(writer)
        return

    peer_id, role, registration_payload = registration
    connection_manager.register(peer_id, writer, role, address)

    if role == ROLE_CLIENT:
        database.store_client(
            client_id=peer_id,
            hostname=registration_payload.get("hostname", ""),
            ip_address=address[0] if isinstance(address, tuple) else str(address),
            os_type=registration_payload.get("os", ""),
        )

    try:
        await write_message(
            writer,
            create_message(MSG_REGISTER_ACK, {"status": "success"}, client_id=peer_id),
        )

        shutdown = _get_shutdown()
        while not shutdown.is_set():
            try:
                message = await read_message(reader, timeout=CLIENT_HEARTBEAT_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(
                    "No message from %s in %ss - dropping", peer_id, CLIENT_HEARTBEAT_TIMEOUT
                )
                break
            except ProtocolError as exc:
                # One bad line should not cost the peer its connection.
                logger.error("Bad message from %s: %s", peer_id, exc)
                continue

            if message is None:
                break

            connection_manager.touch(peer_id)
            await process_message(peer_id, role, message)

    except asyncio.CancelledError:
        logger.info("Handler for %s cancelled", peer_id)
        raise
    except Exception:
        logger.exception("Unhandled error serving %s", peer_id)
    finally:
        connection_manager.unregister(peer_id)
        if role == ROLE_CLIENT:
            database.mark_client_offline(peer_id)
        logger.info("Disconnected %s (%d live)", peer_id, connection_manager.connection_count())
        await close_writer(writer)


async def reap_stale_connections() -> None:
    """Drop peers that have gone silent past the heartbeat timeout."""
    shutdown = _get_shutdown()

    while not shutdown.is_set():
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=REAP_INTERVAL)
            return
        except asyncio.TimeoutError:
            pass

        for peer_id in connection_manager.find_stale(CLIENT_HEARTBEAT_TIMEOUT):
            logger.warning("Reaping stale peer %s", peer_id)
            writer = connection_manager.get_writer(peer_id)
            connection_manager.unregister(peer_id)
            if writer is not None:
                await close_writer(writer)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


async def start_server() -> None:
    """Bind the listener and serve until shutdown is requested."""
    database.init_database()
    log_auth_state()

    server = await asyncio.start_server(
        handle_client,
        SERVER_HOST,
        SERVER_PORT,
        limit=STREAM_LIMIT,
    )

    bound = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info("Engine listening on %s (max %d peers)", bound, MAX_CLIENTS)

    reaper = asyncio.create_task(reap_stale_connections())

    async with server:
        await _get_shutdown().wait()

    logger.info("Shutting down")
    reaper.cancel()
    try:
        await reaper
    except asyncio.CancelledError:
        pass


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Request shutdown on SIGINT/SIGTERM.

    loop.add_signal_handler is POSIX-only; on Windows (development only) fall
    back to signal.signal.
    """
    def on_signal() -> None:
        logger.info("Shutdown signal received")
        request_shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, on_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(on_signal))


async def _main() -> None:
    _install_signal_handlers(asyncio.get_running_loop())
    await start_server()


def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Starting Engine")

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception:
        logger.exception("Engine failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
