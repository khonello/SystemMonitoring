"""Protocol constants shared by the Engine, Client Agent and Admin GUI.

Deliberately free of platform- and component-specific imports so all three
deployable units can depend on it.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

DEFAULT_ENGINE_HOST: Final[str] = "0.0.0.0"
DEFAULT_ENGINE_PORT: Final[int] = 5000

ENCODING: Final[str] = "utf-8"
MESSAGE_DELIMITER: Final[bytes] = b"\n"

# asyncio's StreamReader caps a single line at 64 KiB by default and raises
# ValueError once that is exceeded. A base64-encoded screen capture travels as
# one JSON line and will blow past it, so BOTH ends must be opened with this
# limit — asyncio.start_server(limit=...) and asyncio.open_connection(limit=...).
STREAM_LIMIT: Final[int] = 16 * 1024 * 1024

# ---------------------------------------------------------------------------
# Timing, in seconds — README "Data Collection Intervals"
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL: Final[int] = 15
APP_DATA_INTERVAL: Final[int] = 30
NETWORK_DATA_INTERVAL: Final[int] = 60
IDLE_CHECK_INTERVAL: Final[int] = 30

# A client that sends nothing at all for this long is treated as gone. Must
# stay comfortably above HEARTBEAT_INTERVAL or healthy clients get dropped.
HEARTBEAT_TIMEOUT: Final[int] = 60

# How long the Engine waits for a peer to finish registering before hanging up.
REGISTRATION_TIMEOUT: Final[int] = 30

RECONNECT_DELAY: Final[int] = 5
RECONNECT_MAX_DELAY: Final[int] = 60

# ---------------------------------------------------------------------------
# Message types — registration and auth handshake
# ---------------------------------------------------------------------------

MSG_REGISTER: Final[str] = "REGISTER"
MSG_REGISTER_CHALLENGE: Final[str] = "REGISTER_CHALLENGE"
MSG_REGISTER_RESPONSE: Final[str] = "REGISTER_RESPONSE"
MSG_REGISTER_ACK: Final[str] = "REGISTER_ACK"
MSG_REGISTER_REJECT: Final[str] = "REGISTER_REJECT"

# ---------------------------------------------------------------------------
# Message types — Client to Engine (monitoring)
# ---------------------------------------------------------------------------

MSG_HEARTBEAT: Final[str] = "HEARTBEAT"
MSG_APP_DATA: Final[str] = "APP_DATA"
MSG_NETWORK_DATA: Final[str] = "NETWORK_DATA"
MSG_USB_EVENT: Final[str] = "USB_EVENT"

# ---------------------------------------------------------------------------
# Message types — Client to Engine (command lifecycle)
# ---------------------------------------------------------------------------

MSG_COMMAND_RESPONSE: Final[str] = "COMMAND_RESPONSE"
MSG_COMMAND_ACCEPTED: Final[str] = "COMMAND_ACCEPTED"
MSG_COMMAND_OUTPUT: Final[str] = "COMMAND_OUTPUT"
MSG_COMMAND_COMPLETE: Final[str] = "COMMAND_COMPLETE"

# ---------------------------------------------------------------------------
# Message types — Engine to Client (commands)
# ---------------------------------------------------------------------------

MSG_EXECUTE_SCRIPT: Final[str] = "EXECUTE_SCRIPT"
MSG_TERMINATE_SCRIPT: Final[str] = "TERMINATE_SCRIPT"
MSG_TERMINATE_PROCESS: Final[str] = "TERMINATE_PROCESS"
MSG_SCREEN_CAPTURE: Final[str] = "SCREEN_CAPTURE"
MSG_SET_WEBSITE_POLICY: Final[str] = "SET_WEBSITE_POLICY"

# Added in Phase 4 alongside the enforcement that gives them meaning. The
# README describes both behaviours under Access Control but names no message
# for either.
MSG_SET_APP_BLACKLIST: Final[str] = "SET_APP_BLACKLIST"
MSG_SET_TIME_RESTRICTION: Final[str] = "SET_TIME_RESTRICTION"
MSG_SHOW_DIALOG: Final[str] = "SHOW_DIALOG"
MSG_SET_PAUSE: Final[str] = "SET_PAUSE"

# An indeterminate pause: the admin holds the lab's screens with no stated end
# time, and drops it when ready. To the student it is simply "paused" — no
# countdown, because there is no deadline to show.
#
# Internally it IS bounded, at one hour. That cap is a fail-safe against the
# admin rather than a policy shown to the user: if the operator closes the GUI,
# goes home, or the network dies mid-pause, the machines must not stay frozen
# indefinitely. As the cap approaches the Admin GUI warns so it can be extended
# deliberately, which keeps a long pause an explicit choice rather than a
# side effect of nobody noticing.
PAUSE_MAX_SECONDS: Final[int] = 3600

# How long before a pause lapses that the Admin GUI starts warning.
PAUSE_WARN_SECONDS: Final[int] = 300

# Overlay presentation modes. "scheduled" shows the countdown a time-based
# restriction has; "pause" deliberately shows none.
OVERLAY_MODE_SCHEDULED: Final[str] = "scheduled"
OVERLAY_MODE_PAUSE: Final[str] = "pause"

# ---------------------------------------------------------------------------
# Message types — Admin to Engine, Engine to Admin
# ---------------------------------------------------------------------------

MSG_ADMIN_COMMAND: Final[str] = "ADMIN_COMMAND"
MSG_CLIENT_LIST: Final[str] = "CLIENT_LIST"
MSG_REPORT_REQUEST: Final[str] = "REPORT_REQUEST"
MSG_REPORT: Final[str] = "REPORT"

# Engine to Admin: a client's pause state changed. Pushed on change rather
# than polled, so a pause set from another console — or one that lapsed on its
# own — appears without waiting for a roster refresh.
MSG_PAUSE_STATE: Final[str] = "PAUSE_STATE"

# Report kinds an admin may request. Each maps to one engine.database query.
REPORT_NETWORK_24H: Final[str] = "network_24h"
REPORT_NETWORK_WEEKLY: Final[str] = "network_weekly"
REPORT_APP_USAGE: Final[str] = "app_usage"
REPORT_USB_EVENTS: Final[str] = "usb_events"
REPORT_COMMAND_HISTORY: Final[str] = "command_history"

VALID_REPORTS: Final[frozenset[str]] = frozenset({
    REPORT_NETWORK_24H,
    REPORT_NETWORK_WEEKLY,
    REPORT_APP_USAGE,
    REPORT_USB_EVENTS,
    REPORT_COMMAND_HISTORY,
})

# Every command the Engine may forward to a Client Agent. Used to validate an
# ADMIN_COMMAND's command_type before routing it.
CLIENT_COMMANDS: Final[frozenset[str]] = frozenset({
    MSG_EXECUTE_SCRIPT,
    MSG_TERMINATE_SCRIPT,
    MSG_TERMINATE_PROCESS,
    MSG_SCREEN_CAPTURE,
    MSG_SET_WEBSITE_POLICY,
    MSG_SET_APP_BLACKLIST,
    MSG_SET_TIME_RESTRICTION,
    MSG_SHOW_DIALOG,
    MSG_SET_PAUSE,
})

# ---------------------------------------------------------------------------
# Connection roles
# ---------------------------------------------------------------------------

# The Engine serves Client Agents and the Admin GUI on the same port, so a
# registering peer must say which it is. Not spelled out in the README's
# protocol section; added here because routing an ADMIN_COMMAND requires
# knowing which connections are admins and which are targets.
ROLE_CLIENT: Final[str] = "client"
ROLE_ADMIN: Final[str] = "admin"

VALID_ROLES: Final[frozenset[str]] = frozenset({ROLE_CLIENT, ROLE_ADMIN})

# ---------------------------------------------------------------------------
# Payload enumerations
# ---------------------------------------------------------------------------

# Website filtering supports both modes; applications are blacklist-only by
# deliberate design (README "Access Control").
POLICY_MODE_BLACKLIST: Final[str] = "blacklist"
POLICY_MODE_WHITELIST: Final[str] = "whitelist"

SCRIPT_TYPE_PYTHON: Final[str] = "python"
SCRIPT_TYPE_POWERSHELL: Final[str] = "powershell"

# Predefined scripts are extensions for small routine tasks, not long-running
# jobs, so execution is clamped. This bounds the damage a runaway script can do
# across a lab: without it, one bad loop leaves a process on every machine.
#
# The ceiling exists so an admin cannot simply opt out. A script needing longer
# than 15 minutes is doing something this mechanism was not meant for and
# belongs in a scheduled task on the machine itself.
#
# Note this does NOT remove the need for the non-blocking execution model: even
# a 5-minute script cannot be waited on inside the response cycle, so
# COMMAND_ACCEPTED, output streaming and TERMINATE_SCRIPT all still apply.
DEFAULT_SCRIPT_TIMEOUT: Final[int] = 300
MAX_SCRIPT_TIMEOUT: Final[int] = 900

# Grace period between asking a timed-out script to stop and forcing it.
# Honest caveat: on Windows both terminate() and kill() are TerminateProcess,
# so the child gets no chance to clean up either way. Scripts should be written
# to be safely interruptible — a run killed mid-write leaves a partial file.
SCRIPT_KILL_GRACE: Final[float] = 5.0

VALID_SCRIPT_TYPES: Final[frozenset[str]] = frozenset({
    SCRIPT_TYPE_PYTHON,
    SCRIPT_TYPE_POWERSHELL,
})

STATUS_SUCCESS: Final[str] = "success"
STATUS_ERROR: Final[str] = "error"

# A script stopped at the cap is reported distinctly rather than as a generic
# error, so the operator can tell "your script is too slow" from "your script
# crashed" without reading the output.
STATUS_TIMEOUT: Final[str] = "timeout"
