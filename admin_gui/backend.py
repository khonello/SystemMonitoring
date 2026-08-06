"""QML-facing backend — the bridge between Qt signals/slots and the Engine.

Event-loop integration is qasync: it drives asyncio on top of Qt's loop, so
the GUI, the socket and every background task share one thread. That was
chosen over a socket thread specifically to keep the README's concurrency
rule intact — sockets can signal readiness, so they belong on the event loop,
and threads are reserved for work that cannot.

Slots are synchronous because QML calls them directly; anything needing I/O
schedules a task via asyncio.ensure_future and returns immediately.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from admin_gui.config import ADMIN_ID, MAX_LIVE_SAMPLES
from admin_gui.connection import EngineConnection
from admin_gui.models import (
    ApplicationModel,
    ClientListModel,
    NetworkSampleModel,
    ReportModel,
    UsbEventModel,
)
from admin_gui.validation import validate_script
from common.constants import (
    MSG_APP_DATA,
    MSG_CLIENT_LIST,
    MSG_COMMAND_ACCEPTED,
    MSG_COMMAND_COMPLETE,
    MSG_COMMAND_OUTPUT,
    MSG_COMMAND_RESPONSE,
    MSG_NETWORK_DATA,
    MSG_REPORT,
    MSG_SCREEN_CAPTURE,
    MSG_SET_WEBSITE_POLICY,
    MSG_TERMINATE_PROCESS,
    MSG_TERMINATE_SCRIPT,
    MSG_USB_EVENT,
    REPORT_APP_USAGE,
    REPORT_COMMAND_HISTORY,
    REPORT_NETWORK_24H,
    REPORT_NETWORK_WEEKLY,
    REPORT_USB_EVENTS,
    STATUS_ERROR,
)
from common.protocol import get_payload

logger = logging.getLogger(__name__)


class Backend(QObject):
    """Owns the Engine session and the models QML binds to."""

    connectionStateChanged = Signal(bool)
    statusMessage = Signal(str)
    selectedClientChanged = Signal(str)
    commandOutput = Signal(str, str)          # command_id, chunk
    commandFinished = Signal(str, str, str)   # command_id, status, message
    validationFailed = Signal(str)
    reportReady = Signal(str)                 # report kind

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.clients = ClientListModel()
        self.applications = ApplicationModel()
        self.usbEvents = UsbEventModel()
        self.networkSamples = NetworkSampleModel()
        self.report = ReportModel()

        self._connection = EngineConnection(ADMIN_ID)
        self._connection.set_handlers(self._on_message, self._on_disconnect)

        self._connected = False
        self._status = "Not connected"
        self._selected_client = ""

        # Last address that connected successfully, persisted by main.py.
        self.engine_host = ""
        self.engine_port = 0

        # Per-client live buffers, so switching selection does not lose data
        # that already arrived for another machine.
        self._live_apps: dict[str, list[dict[str, Any]]] = {}
        self._live_usb: dict[str, list[dict[str, Any]]] = {}
        self._live_network: dict[str, list[dict[str, Any]]] = {}

        self._handlers = {
            MSG_CLIENT_LIST: self._handle_client_list,
            MSG_APP_DATA: self._handle_app_data,
            MSG_NETWORK_DATA: self._handle_network_data,
            MSG_USB_EVENT: self._handle_usb_event,
            MSG_REPORT: self._handle_report,
            MSG_COMMAND_RESPONSE: self._handle_command_response,
            MSG_COMMAND_ACCEPTED: self._handle_command_accepted,
            MSG_COMMAND_OUTPUT: self._handle_command_output,
            MSG_COMMAND_COMPLETE: self._handle_command_complete,
        }

    # -- properties --------------------------------------------------------

    def _is_connected(self) -> bool:
        return self._connected

    connected = Property(bool, _is_connected, notify=connectionStateChanged)

    def _status_text(self) -> str:
        return self._status

    status = Property(str, _status_text, notify=statusMessage)

    def _get_selected(self) -> str:
        return self._selected_client

    def _set_selected(self, client_id: str) -> None:
        if client_id == self._selected_client:
            return
        self._selected_client = client_id
        self._refresh_live_models()
        self.selectedClientChanged.emit(client_id)

    selectedClient = Property(
        str, _get_selected, _set_selected, notify=selectedClientChanged
    )

    # -- connection slots --------------------------------------------------

    @Slot(str, int)
    def connectToEngine(self, host: str, port: int) -> None:
        asyncio.ensure_future(self._connect(host, port))

    @Slot()
    def disconnectFromEngine(self) -> None:
        asyncio.ensure_future(self._disconnect())

    async def _connect(self, host: str, port: int) -> None:
        self._set_status(f"Connecting to {host}:{port}...")

        if await self._connection.connect(host, port):
            # Recorded so the address that actually worked is what gets
            # remembered, rather than whatever was prefilled at startup.
            self.engine_host = host
            self.engine_port = port
            self._set_connected(True)
            self._set_status(f"Connected to {host}:{port} as {ADMIN_ID}")
            await self._connection.request_client_list()
        else:
            self._set_connected(False)
            self._set_status(f"Could not connect to {host}:{port}")

    async def _disconnect(self) -> None:
        await self._connection.close()
        self._set_connected(False)
        self._set_status("Not connected")
        self.clients.clear()
        self._clear_live()

    # -- data slots --------------------------------------------------------

    @Slot()
    def refreshClients(self) -> None:
        asyncio.ensure_future(self._connection.request_client_list())

    @Slot(str)
    def requestReport(self, report: str) -> None:
        if not self._selected_client and report != REPORT_COMMAND_HISTORY:
            self._set_status("Select a client first")
            return
        asyncio.ensure_future(
            self._connection.request_report(report, self._selected_client)
        )

    # -- command slots -----------------------------------------------------

    @Slot(str, str)
    def sendScript(self, script: str, script_type: str) -> None:
        asyncio.ensure_future(self._send_script(script, script_type))

    async def _send_script(self, script: str, script_type: str) -> None:
        """Validate locally, then dispatch. Never send a script that will not
        compile — that is the entire reason this GUI ships an interpreter."""
        ok, message = await validate_script(script, script_type)
        if not ok:
            logger.warning("Script rejected before sending: %s", message)
            self.validationFailed.emit(message)
            self._set_status("Script failed validation - not sent")
            return

        if not self._selected_client:
            self._set_status("Select a client first")
            return

        from common.constants import MSG_EXECUTE_SCRIPT

        await self._connection.send_command(
            MSG_EXECUTE_SCRIPT,
            [self._selected_client],
            {"script": script, "script_type": script_type},
        )
        self._set_status(f"Script sent to {self._selected_client}")

    @Slot(str, bool)
    def terminateProcess(self, process_name: str, force: bool) -> None:
        if not self._require_selection():
            return
        asyncio.ensure_future(
            self._connection.send_command(
                MSG_TERMINATE_PROCESS,
                [self._selected_client],
                {"process_name": process_name, "force": force},
            )
        )

    @Slot(str, bool)
    def terminateScript(self, target_command_id: str, force: bool) -> None:
        if not self._require_selection():
            return
        asyncio.ensure_future(
            self._connection.send_command(
                MSG_TERMINATE_SCRIPT,
                [self._selected_client],
                {"target_command_id": target_command_id, "force": force},
            )
        )

    @Slot(int)
    def captureScreen(self, quality: int) -> None:
        if not self._require_selection():
            return
        asyncio.ensure_future(
            self._connection.send_command(
                MSG_SCREEN_CAPTURE, [self._selected_client], {"quality": quality}
            )
        )

    @Slot(str, str, str)
    def setWebsitePolicy(self, mode: str, urls: str, action: str) -> None:
        """Push a website filtering policy.

        `mode` is always explicit — blacklist and whitelist are both
        first-class, and which one is active must never be inferred
        (README "Access Control").
        """
        if not self._require_selection():
            return

        parsed = [line.strip() for line in urls.replace(",", "\n").splitlines() if line.strip()]
        asyncio.ensure_future(
            self._connection.send_command(
                MSG_SET_WEBSITE_POLICY,
                [self._selected_client],
                {"mode": mode, "urls": parsed, "action": action},
            )
        )
        self._set_status(f"{mode} policy ({len(parsed)} entries) sent")

    # -- inbound message handling -----------------------------------------

    def _on_message(self, message: dict[str, Any]) -> None:
        handler = self._handlers.get(message.get("type", ""))
        if handler is None:
            logger.debug("Ignoring %s", message.get("type"))
            return
        handler(message)

    def _on_disconnect(self, reason: str) -> None:
        self._set_connected(False)
        self._set_status(reason)

    def _handle_client_list(self, message: dict[str, Any]) -> None:
        clients = get_payload(message).get("clients", [])
        self.clients.setRows(clients)

        # Drop a selection whose machine is gone from the roster entirely.
        known = {entry.get("client_id") for entry in clients}
        if self._selected_client and self._selected_client not in known:
            self._set_selected("")

    def _handle_app_data(self, message: dict[str, Any]) -> None:
        client_id = message.get("client_id", "")
        apps = get_payload(message).get("applications", [])
        self._live_apps[client_id] = apps[:MAX_LIVE_SAMPLES]
        if client_id == self._selected_client:
            self.applications.setRows(self._live_apps[client_id])

    def _handle_network_data(self, message: dict[str, Any]) -> None:
        client_id = message.get("client_id", "")
        sample = {**get_payload(message), "timestamp": message.get("timestamp")}

        samples = self._live_network.setdefault(client_id, [])
        samples.append(sample)
        del samples[:-MAX_LIVE_SAMPLES]

        if client_id == self._selected_client:
            self.networkSamples.setRows(list(reversed(samples)))

    def _handle_usb_event(self, message: dict[str, Any]) -> None:
        client_id = message.get("client_id", "")
        event = {**get_payload(message), "timestamp": message.get("timestamp")}

        events = self._live_usb.setdefault(client_id, [])
        events.append(event)
        del events[:-MAX_LIVE_SAMPLES]

        if client_id == self._selected_client:
            self.usbEvents.setRows(list(reversed(events)))

    def _handle_report(self, message: dict[str, Any]) -> None:
        payload = get_payload(message)
        kind = payload.get("report", "")

        if payload.get("status") == STATUS_ERROR:
            self._set_status(f"Report failed: {payload.get('message')}")
            self.report.clear()
            return

        self.report.setRows(_flatten_report(kind, payload.get("data")))
        self.reportReady.emit(kind)
        self._set_status(f"Report ready: {kind}")

    def _handle_command_response(self, message: dict[str, Any]) -> None:
        payload = get_payload(message)
        command_id = payload.get("command_id", "")
        status = payload.get("status", "")
        text = payload.get("message") or payload.get("result") or ""
        self.commandFinished.emit(command_id, status, str(text))
        self._set_status(f"{message.get('client_id', '')}: {status} {text}".strip())

    def _handle_command_accepted(self, message: dict[str, Any]) -> None:
        payload = get_payload(message)
        self._set_status(f"Script accepted as {payload.get('command_id')}")

    def _handle_command_output(self, message: dict[str, Any]) -> None:
        payload = get_payload(message)
        self.commandOutput.emit(payload.get("command_id", ""), payload.get("chunk", ""))

    def _handle_command_complete(self, message: dict[str, Any]) -> None:
        payload = get_payload(message)
        self.commandFinished.emit(
            payload.get("command_id", ""),
            str(payload.get("status", "")),
            f"exit {payload.get('returncode')}",
        )

    # -- internals ---------------------------------------------------------

    def _require_selection(self) -> bool:
        if not self._selected_client:
            self._set_status("Select a client first")
            return False
        return True

    def _refresh_live_models(self) -> None:
        client_id = self._selected_client
        self.applications.setRows(self._live_apps.get(client_id, []))
        self.usbEvents.setRows(list(reversed(self._live_usb.get(client_id, []))))
        self.networkSamples.setRows(list(reversed(self._live_network.get(client_id, []))))

    def _clear_live(self) -> None:
        self._live_apps.clear()
        self._live_usb.clear()
        self._live_network.clear()
        self.applications.clear()
        self.usbEvents.clear()
        self.networkSamples.clear()
        self.report.clear()

    def _set_status(self, text: str) -> None:
        self._status = text
        logger.info(text)
        self.statusMessage.emit(text)

    def _set_connected(self, state: bool) -> None:
        if state != self._connected:
            self._connected = state
            self.connectionStateChanged.emit(state)


def _format_bytes(value: Any) -> str:
    """Human-readable byte count."""
    try:
        size = float(value)
    except (TypeError, ValueError):
        return str(value)

    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size:.0f} B"
        size /= 1024
    return f"{size:.1f} GB"


def _flatten_report(kind: str, data: Any) -> list[dict[str, str]]:
    """Turn a report payload into label/detail/value rows.

    Each report has a different shape, and QML should not have to branch on
    which one it is showing.
    """
    if data is None:
        return []

    if kind == REPORT_NETWORK_24H:
        return [
            {"label": "Sent", "detail": "last 24 hours",
             "value": _format_bytes(data.get("bytes_sent"))},
            {"label": "Received", "detail": "last 24 hours",
             "value": _format_bytes(data.get("bytes_received"))},
            {"label": "Samples", "detail": "readings recorded",
             "value": str(data.get("samples", 0))},
        ]

    if kind == REPORT_NETWORK_WEEKLY:
        return [
            {
                "label": row.get("day", ""),
                "detail": f"{_format_bytes(row.get('bytes_received'))} in",
                "value": f"{_format_bytes(row.get('bytes_sent'))} out",
            }
            for row in data
        ]

    if kind == REPORT_APP_USAGE:
        return [
            {
                "label": row.get("process_name", ""),
                "detail": f"{row.get('samples', 0)} samples, "
                          f"peak {row.get('peak_memory_mb') or 0:.0f} MB",
                "value": f"avg {row.get('avg_cpu') or 0:.1f}% CPU",
            }
            for row in data
        ]

    if kind == REPORT_USB_EVENTS:
        return [
            {
                "label": row.get("device_name", ""),
                "detail": str(row.get("timestamp", "")),
                "value": row.get("event_type", ""),
            }
            for row in data
        ]

    if kind == REPORT_COMMAND_HISTORY:
        return [
            {
                "label": row.get("command_type", ""),
                "detail": f"{row.get('client_id', '')} - {row.get('timestamp', '')}",
                "value": row.get("status", ""),
            }
            for row in data
        ]

    return [{"label": str(data), "detail": "", "value": ""}]
