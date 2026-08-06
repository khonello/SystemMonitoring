"""QML-facing backend.

PHASE 1 SCAFFOLD. Signals and slots exist and are bound in QML, but nothing
talks to the Engine yet.

The blocking question is deferred on purpose: Qt runs its own event loop and
so does asyncio, and reconciling them (qasync, a QTimer pump, or a socket
thread posting back via signals) is a Phase 3 decision that shapes this whole
module. Committing to one here would prejudge it. Until then the slots log
and emit, so the QML can be built and clicked through.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot

logger = logging.getLogger(__name__)


class Backend(QObject):
    """Bridge between QML and the Engine connection."""

    connectionStateChanged = Signal(bool)
    statusMessage = Signal(str)
    clientListUpdated = Signal(list)
    commandOutput = Signal(str, str)  # command_id, chunk

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._status = "Not connected"

    # -- properties --------------------------------------------------------

    def _is_connected(self) -> bool:
        return self._connected

    connected = Property(bool, _is_connected, notify=connectionStateChanged)

    def _status_text(self) -> str:
        return self._status

    status = Property(str, _status_text, notify=statusMessage)

    # -- slots -------------------------------------------------------------

    @Slot(str, int)
    def connectToEngine(self, host: str, port: int) -> None:
        """Open a connection to the Engine."""
        # TODO(Phase 3): resolve the asyncio/Qt integration, then connect and
        #   register with role=admin.
        logger.info("connectToEngine(%s, %d) - not wired until Phase 3", host, port)
        self._set_status(f"Would connect to {host}:{port}")

    @Slot()
    def disconnectFromEngine(self) -> None:
        # TODO(Phase 3)
        logger.info("disconnectFromEngine - not wired until Phase 3")
        self._set_status("Not connected")

    @Slot()
    def refreshClients(self) -> None:
        """Ask the Engine for the current client roster."""
        # TODO(Phase 3): send CLIENT_LIST, feed the reply to ClientListModel.
        logger.info("refreshClients - not wired until Phase 3")

    @Slot(str, str, str)
    def sendScript(self, client_id: str, script: str, script_type: str) -> None:
        """Validate a script locally, then send it for execution."""
        # TODO(Phase 3): validate with the bundled interpreter (py_compile)
        #   BEFORE sending, so authoring mistakes surface here and not on a lab
        #   machine (README "Bundled Runtime & Script Validation").
        logger.info("sendScript(%s, %s) - not wired until Phase 3", client_id, script_type)

    @Slot(str, str, bool)
    def terminateProcess(self, client_id: str, process_name: str, force: bool) -> None:
        # TODO(Phase 3)
        logger.info("terminateProcess(%s, %s, force=%s)", client_id, process_name, force)

    @Slot(str, int)
    def captureScreen(self, client_id: str, quality: int) -> None:
        # TODO(Phase 3)
        logger.info("captureScreen(%s, quality=%d)", client_id, quality)

    @Slot(str, str, list, str)
    def setWebsitePolicy(
        self,
        client_id: str,
        mode: str,
        urls: list[str],
        action: str,
    ) -> None:
        """Push a website filtering policy.

        `mode` is passed explicitly rather than inferred - blacklist and
        whitelist are both first-class (README "Access Control").
        """
        # TODO(Phase 3)
        logger.info("setWebsitePolicy(%s, mode=%s, %d urls)", client_id, mode, len(urls))

    # -- internals ---------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusMessage.emit(text)

    def _set_connected(self, state: bool) -> None:
        if state != self._connected:
            self._connected = state
            self.connectionStateChanged.emit(state)

    def _on_message(self, message: dict[str, Any]) -> None:
        """Handle one message from the Engine."""
        # TODO(Phase 3): dispatch CLIENT_LIST, APP_DATA, COMMAND_OUTPUT, ...
