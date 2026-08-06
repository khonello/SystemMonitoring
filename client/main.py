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

from client import connection, lockout, policy
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
from client.monitors.process_monitor import collect_process_data, prime_cpu_percent
from client.monitors.usb_monitor import get_idle_time, is_screen_locked, poll_usb_events
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

            # Enforced on the collection cycle rather than once, because
            # blocking a launch means terminating it shortly after it starts —
            # there is no pre-launch hook without a kernel driver.
            await asyncio.to_thread(policy.enforce_app_blacklist)
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
                    {
                        "status": "active",
                        "idle_time": get_idle_time(),
                        "screen_locked": is_screen_locked(),
                    },
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


async def _run_agent() -> None:
    """Run the Engine session loop and the local watchdog together.

    The watchdog sits outside the connection loop deliberately: time-based
    restrictions are enforced from local state and must keep working while the
    Engine is unreachable. A machine does not become unrestricted because the
    network went down.
    """
    watchdog = asyncio.create_task(lockout.watchdog_loop(_shutdown), name="lockout")
    try:
        await main_loop()
    finally:
        watchdog.cancel()
        await asyncio.gather(watchdog, return_exceptions=True)


def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Starting Client Agent %s -> %s:%s", CLIENT_ID, ENGINE_HOST, ENGINE_PORT)

    # A reboot is not an escape hatch: re-apply any still-active lockout before
    # anything else, without needing the Engine.
    lockout.check_on_startup()

    # psutil measures CPU between calls, so priming here means the first batch
    # carries real numbers instead of a screen of zeroes.
    try:
        prime_cpu_percent()
    except Exception:
        logger.debug("Could not prime CPU counters", exc_info=True)

    try:
        asyncio.run(_run_agent())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception:
        logger.exception("Client Agent failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
