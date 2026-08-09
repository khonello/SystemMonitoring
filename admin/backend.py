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
from datetime import datetime, timedelta, timezone
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from admin.config import ADMIN_ID, MAX_LIVE_SAMPLES
from admin.connection import EngineConnection
from admin.models import (
    ApplicationModel,
    ClientListModel,
    NetworkSampleModel,
    ReportModel,
    UsbEventModel,
)
from admin.validation import analyse_script
from common.constants import (
    DEFAULT_SCRIPT_TIMEOUT,
    MAX_BLOCK_HOURS,
    MAX_SCRIPT_TIMEOUT,
    MSG_APP_DATA,
    MSG_CLIENT_LIST,
    MSG_COMMAND_ACCEPTED,
    MSG_COMMAND_COMPLETE,
    MSG_COMMAND_OUTPUT,
    MSG_COMMAND_RESPONSE,
    MSG_EXECUTE_SCRIPT,
    MSG_NETWORK_DATA,
    MSG_PAUSE_STATE,
    MSG_REPORT,
    MSG_SCREEN_CAPTURE,
    MSG_SET_APP_BLACKLIST,
    MSG_SET_PAUSE,
    MSG_SET_TIME_RESTRICTION,
    MSG_SET_WEBSITE_POLICY,
    MSG_TERMINATE_PROCESS,
    MSG_TERMINATE_SCRIPT,
    MSG_USB_EVENT,
    PAUSE_MAX_SECONDS,
    PAUSE_WARN_SECONDS,
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
    pauseExpiring = Signal(str, int)          # client_id, seconds remaining
    scriptChecked = Signal(str, bool)         # human-readable summary, passed

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

        # client_id -> when its pause lapses, learned from heartbeat-reported
        # state rather than from what this GUI asked for.
        self._pause_until: dict[str, datetime] = {}
        self._warned: set[str] = set()

        self._pause_timer = QTimer(self)
        self._pause_timer.setInterval(10_000)
        self._pause_timer.timeout.connect(self._check_pause_expiry)
        self._pause_timer.start()

        self._handlers = {
            MSG_CLIENT_LIST: self._handle_client_list,
            MSG_PAUSE_STATE: self._handle_pause_state,
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

    def _max_block_hours(self) -> int:
        return MAX_BLOCK_HOURS

    # Exposed so the policy editor states the cap the client actually enforces,
    # rather than repeating the number and drifting from it.
    maxBlockHours = Property(int, _max_block_hours, constant=True)

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

    @Slot(str, str, int)
    def sendScript(self, script: str, script_type: str, timeout: int) -> None:
        asyncio.ensure_future(self._send_script(script, script_type, timeout))

    @Slot(str, str)
    def checkScript(self, script: str, script_type: str) -> None:
        """Analyse a script without sending it, so the operator can see what
        the policy makes of it before committing."""
        asyncio.ensure_future(self._check_script(script, script_type))

    async def _check_script(self, script: str, script_type: str) -> dict[str, Any]:
        result = await analyse_script(script, script_type)
        self.scriptChecked.emit(_describe_check(result), result["ok"])
        return result

    async def _send_script(
        self, script: str, script_type: str, timeout: int = DEFAULT_SCRIPT_TIMEOUT
    ) -> None:
        """Validate locally, then dispatch. Never send a script that will not
        compile or that breaks the stdlib-only policy — that is the entire
        reason this GUI ships an interpreter."""
        result = await self._check_script(script, script_type)

        if not result["ok"]:
            detail = "\n".join(result["errors"])
            logger.warning("Script rejected before sending: %s", detail)
            self.validationFailed.emit(detail)
            self._set_status("Script failed validation - not sent")
            return

        if not self._selected_client:
            self._set_status("Select a client first")
            return

        # Clamped here too, so the operator sees the effective value in the
        # status line rather than discovering it from the client's reply.
        effective = max(1, min(int(timeout or DEFAULT_SCRIPT_TIMEOUT), MAX_SCRIPT_TIMEOUT))

        await self._connection.send_command(
            MSG_EXECUTE_SCRIPT,
            [self._selected_client],
            {
                "script": script,
                "script_type": script_type,
                "timeout_seconds": effective,
            },
        )
        self._set_status(
            f"Script sent to {self._selected_client} (limit {effective}s)"
        )

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

    # -- pause -------------------------------------------------------------

    @Slot()
    def pauseSelected(self) -> None:
        """Pause the selected client's screen, indefinitely from its point of
        view."""
        if not self._require_selection():
            return
        self._send_pause([self._selected_client], "pause")

    @Slot()
    def pauseAll(self) -> None:
        """Pause every connected client — the 'hold the room' case."""
        targets = [row["client_id"] for row in self.clients.rows if row.get("connected")]
        if not targets:
            self._set_status("No connected clients to pause")
            return
        self._send_pause(targets, "pause")

    @Slot()
    def resumeSelected(self) -> None:
        if not self._require_selection():
            return
        self._send_pause([self._selected_client], "resume")

    @Slot()
    def resumeAll(self) -> None:
        targets = [row["client_id"] for row in self.clients.rows if row.get("connected")]
        if not targets:
            self._set_status("No connected clients to resume")
            return
        self._send_pause(targets, "resume")

    @Slot(str)
    def extendPause(self, client_id: str) -> None:
        """Push a paused client's internal expiry back out to the full cap.

        Extending is deliberately an explicit act. The cap exists so an
        unattended pause lapses; renewing it silently would defeat that.
        """
        target = client_id or self._selected_client
        if not target:
            self._set_status("Select a client first")
            return
        self._send_pause([target], "pause")
        self._warned.discard(target)

    def _send_pause(self, targets: list[str], action: str) -> None:
        asyncio.ensure_future(
            self._connection.send_command(
                MSG_SET_PAUSE, targets, {"action": action, "seconds": PAUSE_MAX_SECONDS}
            )
        )
        verb = "Pausing" if action == "pause" else "Resuming"
        self._set_status(f"{verb} {len(targets)} client(s)")

    def _check_pause_expiry(self) -> None:
        """Warn before a pause lapses, once per client per pause.

        Driven off what the clients actually report rather than what this GUI
        asked for, so a pause set from another console is tracked too, and a
        restarted GUI recovers the state instead of losing it.
        """
        now = datetime.now(timezone.utc)

        for client_id, until in list(self._pause_until.items()):
            remaining = (until - now).total_seconds()

            if remaining <= 0:
                self._pause_until.pop(client_id, None)
                self._warned.discard(client_id)
                continue

            if remaining <= PAUSE_WARN_SECONDS and client_id not in self._warned:
                self._warned.add(client_id)
                self.pauseExpiring.emit(client_id, int(remaining))
                self._set_status(
                    f"{client_id}: pause lapses in {int(remaining // 60)} min - "
                    f"extend it or it will resume on its own"
                )

    def _record_pause(self, client_id: str, paused: bool, until: str | None) -> None:
        if not paused or not until:
            self._pause_until.pop(client_id, None)
            self._warned.discard(client_id)
            return

        parsed = _parse_iso(until)
        if parsed is not None:
            self._pause_until[client_id] = parsed

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

    @Slot(str)
    def setAppBlacklist(self, names: str) -> None:
        """Push the standing application blacklist.

        Not the same action as terminateProcess, which kills one process once.
        This is the list the agent re-enforces on every collection cycle:
        blocking a launch means terminating it shortly after it starts, because
        there is no pre-launch hook without a kernel driver.

        Blacklist-only by design — whitelisting applications cannot reliably
        enumerate the OS and helper processes legitimate work depends on
        (README "Access Control"), so unlisted applications are allowed.

        An empty list is a valid instruction: it clears the blacklist.
        """
        if not self._require_selection():
            return

        parsed = [line.strip() for line in names.replace(",", "\n").splitlines() if line.strip()]
        asyncio.ensure_future(
            self._connection.send_command(
                MSG_SET_APP_BLACKLIST,
                [self._selected_client],
                {"process_names": parsed},
            )
        )

        if parsed:
            self._set_status(f"App blacklist ({len(parsed)} entries) sent")
        else:
            self._set_status("App blacklist cleared")

    # -- time restrictions -------------------------------------------------
    #
    # A *scheduled* block, which is not the same thing as a pause: it has a
    # known end and the student sees it counting down. The pause controls above
    # are the other mechanism, deliberately without a countdown.
    #
    # The client stores one window at a time and caps it at MAX_BLOCK_HOURS, so
    # what is sent here is a single start/end pair rather than a recurring rule.

    @Slot(int, int, bool)
    def setTimeRestriction(self, minutes: int, delayMinutes: int, toAll: bool) -> None:
        """Block a machine, or the room, for `minutes` starting after a delay.

        A delay lets an exam lockout be set up beforehand: the client stores the
        window immediately and its watchdog raises the overlay when the window
        opens, with no further contact from here.

        The client shortens anything longer than its cap and reports the end it
        actually stored, so this warns rather than silently sending more.
        """
        targets = self._restriction_targets(toAll)
        if targets is None:
            return

        duration = max(1, minutes)
        start = datetime.now(timezone.utc) + timedelta(minutes=max(0, delayMinutes))
        end = start + timedelta(minutes=duration)

        asyncio.ensure_future(
            self._connection.send_command(
                MSG_SET_TIME_RESTRICTION,
                targets,
                {"start": start.isoformat(), "end": end.isoformat()},
            )
        )

        capped = " - the client will shorten it to %dh" % MAX_BLOCK_HOURS
        self._set_status(
            f"Blocking {len(targets)} client(s) for {duration} min"
            f"{capped if duration > MAX_BLOCK_HOURS * 60 else ''}"
        )

    @Slot(bool)
    def clearTimeRestriction(self, toAll: bool) -> None:
        """Lift a scheduled block early.

        Does not touch a pause: if one is active the machine stays held, which
        is the same precedence the client applies.
        """
        targets = self._restriction_targets(toAll)
        if targets is None:
            return

        asyncio.ensure_future(
            self._connection.send_command(
                MSG_SET_TIME_RESTRICTION, targets, {"clear": True}
            )
        )
        self._set_status(f"Clearing the block on {len(targets)} client(s)")

    def _restriction_targets(self, to_all: bool) -> list[str] | None:
        """Who a restriction applies to, or None with a status set if nobody."""
        if not to_all:
            return [self._selected_client] if self._require_selection() else None

        targets = self._connected_client_ids()
        if not targets:
            self._set_status("No connected clients")
            return None
        return targets

    def _connected_client_ids(self) -> list[str]:
        return [row["client_id"] for row in self.clients.rows if row.get("connected")]

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

    def _handle_pause_state(self, message: dict[str, Any]) -> None:
        payload = get_payload(message)
        client_id = message.get("client_id", "")
        paused = bool(payload.get("paused"))

        self._record_pause(client_id, paused, payload.get("pause_until"))
        self._set_status(f"{client_id}: {'paused' if paused else 'resumed'}")

        # Keep the roster's badge honest without waiting for a manual refresh.
        asyncio.ensure_future(self._connection.request_client_list())

    def _handle_client_list(self, message: dict[str, Any]) -> None:
        clients = get_payload(message).get("clients", [])
        self.clients.setRows(clients)

        for row in clients:
            self._record_pause(
                row.get("client_id", ""),
                bool(row.get("paused")),
                row.get("pause_until"),
            )

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


def _describe_check(result: dict[str, Any]) -> str:
    """Turn a validation result into something worth reading.

    Shows the accepted imports as well as the rejected ones — an operator who
    can see the policy agreed with them learns the rule, whereas a bare "OK"
    teaches nothing.
    """
    lines: list[str] = []

    if result["ok"]:
        if result["stdlib"]:
            lines.append(
                f"OK - {len(result['stdlib'])} stdlib import(s): "
                + ", ".join(result["stdlib"])
            )
        else:
            lines.append("OK - no imports")
    else:
        lines.extend(result["errors"])

        if result["stdlib"]:
            lines.append("Allowed: " + ", ".join(result["stdlib"]))

    lines.extend(result["warnings"])
    return "\n".join(lines)


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating the trailing Z form."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
