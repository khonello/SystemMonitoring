"""Engine connection for the Administrator GUI.

Mirrors client/connection.py but registers with role=admin. Runs on the same
asyncio loop as the GUI, which qasync drives on top of Qt's — so there are no
threads here and no cross-thread marshalling to get wrong.

Unlike the Client Agent, this is a class rather than module-level state: an
admin session is owned by one Backend instance, and tests need to stand up
more than one at a time.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from admin_gui.config import ADMIN_ID
from common.constants import (
    HEARTBEAT_INTERVAL,
    MSG_ADMIN_COMMAND,
    MSG_CLIENT_LIST,
    MSG_HEARTBEAT,
    MSG_REGISTER,
    MSG_REGISTER_ACK,
    MSG_REGISTER_CHALLENGE,
    MSG_REGISTER_REJECT,
    MSG_REGISTER_RESPONSE,
    MSG_REPORT_REQUEST,
    REGISTRATION_TIMEOUT,
    ROLE_ADMIN,
    STREAM_LIMIT,
)
from common.protocol import (
    ProtocolError,
    create_message,
    decode_message,
    encode_message,
    get_payload,
)

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class EngineConnection:
    """One admin session against the Engine."""

    def __init__(self, admin_id: str = ADMIN_ID) -> None:
        self.admin_id = admin_id
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._on_message: MessageHandler | None = None
        self._on_disconnect: Callable[[str], None] | None = None

    # -- lifecycle ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self, host: str, port: int) -> bool:
        """Open a connection and complete registration."""
        try:
            self._reader, self._writer = await asyncio.open_connection(
                host, port, limit=STREAM_LIMIT
            )
        except OSError as exc:
            logger.error("Connection to %s:%s failed: %s", host, port, exc)
            self._reader = self._writer = None
            return False

        if not await self._register():
            await self.close()
            return False

        self._tasks = [
            asyncio.create_task(self._listen(), name="admin-listen"),
            asyncio.create_task(self._heartbeat(), name="admin-heartbeat"),
        ]
        return True

    async def close(self) -> None:
        """Tear down the session, cancelling its background tasks."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass

        self._reader = self._writer = None

    def set_handlers(
        self,
        on_message: MessageHandler,
        on_disconnect: Callable[[str], None] | None = None,
    ) -> None:
        self._on_message = on_message
        self._on_disconnect = on_disconnect

    # -- sending -----------------------------------------------------------

    async def send(self, message: dict[str, Any]) -> bool:
        if self._writer is None:
            logger.error("Cannot send %s: not connected", message.get("type"))
            return False
        try:
            self._writer.write(encode_message(message))
            await self._writer.drain()
            return True
        except (ConnectionError, RuntimeError) as exc:
            logger.error("Send failed: %s", exc)
            return False

    async def request_client_list(self) -> bool:
        return await self.send(create_message(MSG_CLIENT_LIST, {}, client_id=self.admin_id))

    async def request_report(self, report: str, client_id: str) -> bool:
        return await self.send(
            create_message(
                MSG_REPORT_REQUEST,
                {"report": report, "client_id": client_id},
                client_id=self.admin_id,
            )
        )

    async def send_command(
        self,
        command_type: str,
        target_clients: list[str],
        parameters: dict[str, Any] | None = None,
    ) -> bool:
        return await self.send(
            create_message(
                MSG_ADMIN_COMMAND,
                {
                    "command_type": command_type,
                    "target_clients": target_clients,
                    "parameters": parameters or {},
                },
                client_id=self.admin_id,
                admin_id=self.admin_id,
            )
        )

    # -- internals ---------------------------------------------------------

    async def _register(self) -> bool:
        hello = create_message(
            MSG_REGISTER, {"role": ROLE_ADMIN}, client_id=self.admin_id
        )
        if not await self.send(hello):
            return False

        try:
            reply = await self._read(timeout=REGISTRATION_TIMEOUT)
        except (asyncio.TimeoutError, ProtocolError) as exc:
            logger.error("Registration failed: %s", exc)
            return False

        if reply is None:
            logger.error("Engine closed the connection during registration")
            return False

        if reply.get("type") == MSG_REGISTER_CHALLENGE:
            # Admins answer the same nonce challenge clients do. The response
            # is a Phase 1 placeholder on both sides; Phase 6 makes it real.
            nonce = get_payload(reply).get("nonce", "")
            if not await self.send(
                create_message(
                    MSG_REGISTER_RESPONSE,
                    {"response": f"phase1-unauthenticated:{nonce[:8]}"},
                    client_id=self.admin_id,
                )
            ):
                return False
            try:
                reply = await self._read(timeout=REGISTRATION_TIMEOUT)
            except (asyncio.TimeoutError, ProtocolError) as exc:
                logger.error("Registration failed awaiting ack: %s", exc)
                return False

        if reply is None:
            return False

        if reply.get("type") == MSG_REGISTER_ACK:
            logger.info("Registered with Engine as %s", self.admin_id)
            return True

        if reply.get("type") == MSG_REGISTER_REJECT:
            logger.error("Engine rejected registration: %s", get_payload(reply).get("reason"))
        else:
            logger.error("Unexpected registration reply: %r", reply.get("type"))
        return False

    async def _read(self, timeout: float | None = None) -> dict[str, Any] | None:
        if self._reader is None:
            return None
        if timeout is None:
            raw = await self._reader.readline()
        else:
            raw = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
        if not raw:
            return None
        return decode_message(raw)

    async def _listen(self) -> None:
        """Dispatch inbound messages until the Engine goes away."""
        reason = "disconnected"
        try:
            while True:
                try:
                    message = await self._read()
                except ProtocolError as exc:
                    logger.error("Bad message from Engine: %s", exc)
                    continue
                except (ConnectionError, asyncio.IncompleteReadError) as exc:
                    reason = f"connection lost: {exc}"
                    return

                if message is None:
                    reason = "Engine closed the connection"
                    return

                if self._on_message is not None:
                    result = self._on_message(message)
                    if asyncio.iscoroutine(result):
                        await result
        except asyncio.CancelledError:
            raise
        finally:
            if self._on_disconnect is not None and reason != "disconnected":
                self._on_disconnect(reason)

    async def _heartbeat(self) -> None:
        """Keep the session alive.

        The Engine drops any peer silent for HEARTBEAT_TIMEOUT, admins
        included. Without this an operator reading a dashboard would be
        disconnected after a minute of not clicking anything.
        """
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.send(
                    create_message(
                        MSG_HEARTBEAT, {"status": "active"}, client_id=self.admin_id
                    )
                )
        except asyncio.CancelledError:
            raise
