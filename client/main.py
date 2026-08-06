#!/usr/bin/env python3
"""Client Agent entry point.

    python -m client.main

Three concurrent loops run per connection — monitoring, heartbeat and command
listener — and the outer loop reconnects with backoff when any of them fails.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from client import connection
from client.config import (
    CLIENT_ID,
    ENGINE_HOST,
    ENGINE_PORT,
    HEARTBEAT_SECONDS,
    LOG_LEVEL,
    MONITOR_INTERVAL,
    NETWORK_INTERVAL,
)
from client.executor import handle_command
from client.monitors.network_monitor import collect_network_data
from client.monitors.process_monitor import collect_process_data
from client.monitors.usb_monitor import get_idle_time, poll_usb_events
from common.constants import (
    MSG_APP_DATA,
    MSG_HEARTBEAT,
    MSG_NETWORK_DATA,
    MSG_USB_EVENT,
)
from common.protocol import ProtocolError, create_message

logger = logging.getLogger(__name__)

_shutdown = asyncio.Event()


async def monitoring_loop() -> None:
    """Collect and send application data on a fixed interval."""
    while not _shutdown.is_set():
        try:
            # Offloaded, not awaited inline: psutil is synchronous and slow
            # enough to delay heartbeats if it runs on the event loop.
            processes = await asyncio.to_thread(collect_process_data)
            await connection.send(
                create_message(
                    MSG_APP_DATA, {"applications": processes}, client_id=CLIENT_ID
                )
            )

            for event in await asyncio.to_thread(poll_usb_events):
                await connection.send(
                    create_message(MSG_USB_EVENT, event, client_id=CLIENT_ID)
                )
        except Exception:
            logger.exception("Monitoring cycle failed")

        await _sleep_or_stop(MONITOR_INTERVAL)


async def network_loop() -> None:
    """Collect and send network usage on its own, slower interval."""
    while not _shutdown.is_set():
        try:
            network = await asyncio.to_thread(collect_network_data)
            await connection.send(
                create_message(MSG_NETWORK_DATA, network, client_id=CLIENT_ID)
            )
        except Exception:
            logger.exception("Network cycle failed")

        await _sleep_or_stop(NETWORK_INTERVAL)


async def heartbeat_loop() -> None:
    """Send liveness beats so the Engine does not reap this connection."""
    while not _shutdown.is_set():
        try:
            await connection.send(
                create_message(
                    MSG_HEARTBEAT,
                    {"status": "active", "idle_time": get_idle_time()},
                    client_id=CLIENT_ID,
                )
            )
        except Exception:
            logger.exception("Heartbeat failed")

        await _sleep_or_stop(HEARTBEAT_SECONDS)


async def command_listener() -> None:
    """Receive and dispatch Engine commands until the connection drops."""
    while not _shutdown.is_set():
        try:
            message = await connection.receive()
        except ProtocolError as exc:
            logger.error("Bad message from Engine: %s", exc)
            continue
        except (ConnectionError, asyncio.IncompleteReadError) as exc:
            logger.warning("Connection lost: %s", exc)
            return

        if message is None:
            logger.warning("Engine closed the connection")
            return

        await handle_command(message)


async def _sleep_or_stop(seconds: float) -> None:
    """Sleep, but wake immediately on shutdown."""
    try:
        await asyncio.wait_for(_shutdown.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _run_session() -> None:
    """Run all loops until the first one exits, then tear the rest down."""
    tasks = [
        asyncio.create_task(command_listener(), name="command_listener"),
        asyncio.create_task(monitoring_loop(), name="monitoring"),
        asyncio.create_task(network_loop(), name="network"),
        asyncio.create_task(heartbeat_loop(), name="heartbeat"),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    for task in done:
        exc = task.exception()
        if exc is not None:
            logger.error("Task %s failed: %s", task.get_name(), exc)


async def main_loop() -> None:
    """Connect, register, serve, reconnect on failure."""
    attempt = 0

    while not _shutdown.is_set():
        if await connection.connect() and await connection.register():
            attempt = 0
            await _run_session()

        await connection.close()

        if _shutdown.is_set():
            break

        attempt += 1
        delay = connection.reconnect_delay(attempt)
        logger.info("Reconnecting in %.0fs (attempt %d)", delay, attempt)
        await _sleep_or_stop(delay)


def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Starting Client Agent %s -> %s:%s", CLIENT_ID, ENGINE_HOST, ENGINE_PORT)

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception:
        logger.exception("Client Agent failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
