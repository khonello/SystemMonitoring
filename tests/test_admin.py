"""Administrator GUI tests.

The transport, validation, models and report flattening are tested against a
real Engine where possible. Rendering QML is not tested — that needs a display
and would only prove Qt works.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from admin.backend import Backend, _describe_check, _flatten_report, _format_bytes
from admin.connection import EngineConnection
from admin.models import ApplicationModel, ClientListModel
from admin.validation import (
    analyse_script,
    classify_imports,
    extract_imports,
    validate_script,
)
from common.constants import (
    MAX_BLOCK_HOURS,
    MSG_SET_APP_BLACKLIST,
    MSG_SET_TIME_RESTRICTION,
    MSG_TERMINATE_PROCESS,
    REPORT_APP_USAGE,
    REPORT_NETWORK_24H,
    REPORT_NETWORK_WEEKLY,
    ROLE_CLIENT,
    SCRIPT_TYPE_POWERSHELL,
    SCRIPT_TYPE_PYTHON,
    STREAM_LIMIT,
)
from common.protocol import create_message
from engine import connection_manager, database
from engine.main import handle_client

HOST = "127.0.0.1"


@pytest_asyncio.fixture
async def engine_port():
    connection_manager.clear()
    server = await asyncio.start_server(handle_client, HOST, 0, limit=STREAM_LIMIT)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.close()
        await server.wait_closed()
        connection_manager.clear()


@pytest_asyncio.fixture
async def admin(engine_port):
    """A registered admin session against a live Engine."""
    connection = EngineConnection("admin-test")
    received: list[dict] = []
    connection.set_handlers(lambda message: received.append(message))

    assert await connection.connect(HOST, engine_port)
    try:
        yield connection, received, engine_port
    finally:
        await connection.close()


async def _wait_for(received: list[dict], msg_type: str, timeout: float = 3.0) -> dict:
    """Wait until a message of `msg_type` arrives."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        for message in received:
            if message.get("type") == msg_type:
                return message
        await asyncio.sleep(0.02)
    raise AssertionError(f"{msg_type} not received; got {[m.get('type') for m in received]}")


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_registers_and_is_recognised(admin):
    connection, _, _ = admin

    assert connection.connected
    assert "admin-test" in connection_manager.get_admin_ids()


@pytest.mark.asyncio
async def test_admin_receives_client_roster(admin):
    connection, received, _ = admin
    database.store_client("pc-01", "lab1-pc-01", "10.0.0.5", "Windows")

    await connection.request_client_list()
    message = await _wait_for(received, "CLIENT_LIST")

    listed = [entry["client_id"] for entry in message["payload"]["clients"]]
    assert "pc-01" in listed


@pytest.mark.asyncio
async def test_roster_includes_offline_clients(admin):
    """A client that disconnects must not vanish from the admin's list."""
    connection, received, _ = admin
    database.store_client("pc-offline", "old-host", "10.0.0.9", "Windows")
    database.mark_client_offline("pc-offline")

    await connection.request_client_list()
    message = await _wait_for(received, "CLIENT_LIST")

    entry = next(c for c in message["payload"]["clients"] if c["client_id"] == "pc-offline")
    assert entry["connected"] is False


@pytest.mark.asyncio
async def test_admin_heartbeat_keeps_the_session_alive(admin, monkeypatch):
    """Issue #1: nothing else makes an admin send traffic, so without its own
    heartbeat an idle operator is dropped after HEARTBEAT_TIMEOUT."""
    connection, _, _ = admin

    # The heartbeat task exists and is running rather than having exited.
    names = {task.get_name() for task in connection._tasks}
    assert "admin-heartbeat" in names
    assert all(not task.done() for task in connection._tasks)


@pytest.mark.asyncio
async def test_admin_command_reaches_the_engine(admin):
    connection, received, _ = admin

    await connection.send_command(MSG_TERMINATE_PROCESS, ["nobody"], {"process_name": "x.exe"})
    await asyncio.sleep(0.15)

    # No client is connected, so it is recorded as undeliverable rather than lost.
    history = database.get_command_history("nobody")
    assert history[0]["status"] == "undeliverable"
    assert history[0]["admin_id"] == "admin-test"


@pytest.mark.asyncio
async def test_report_request_returns_data(admin):
    connection, received, _ = admin
    database.store_client("pc-01", "lab1-pc-01", "10.0.0.5", "Windows")
    database.store_network_data("pc-01", {"bytes_sent": 100, "bytes_received": 200})

    await connection.request_report(REPORT_NETWORK_24H, "pc-01")
    message = await _wait_for(received, "REPORT")

    assert message["payload"]["status"] == "success"
    assert message["payload"]["data"]["samples"] == 1


@pytest.mark.asyncio
async def test_unknown_report_is_refused(admin):
    connection, received, _ = admin

    await connection.request_report("drop_tables", "pc-01")
    message = await _wait_for(received, "REPORT")

    assert message["payload"]["status"] == "error"


@pytest.mark.asyncio
async def test_monitoring_data_is_relayed_to_admins(admin):
    """The dashboard is push-based: the Engine forwards client telemetry."""
    connection, received, port = admin

    from client import connection as client_connection
    from client.config import CLIENT_ID

    assert await client_connection.connect(HOST, port)
    try:
        assert await client_connection.register()

        # Selection is the subscription: telemetry reaches the admins watching
        # that client, not every console connected (issues.md D5). The pause is
        # for the Engine to process this before the sample arrives — they are
        # two sockets, so nothing orders them for us.
        assert await connection.declare_watch(CLIENT_ID)
        await asyncio.sleep(0.2)

        await client_connection.send(
            create_message(
                "APP_DATA",
                {"applications": [{"process_name": "chrome.exe", "pid": 42}]},
                client_id=CLIENT_ID,
            )
        )
        message = await _wait_for(received, "APP_DATA")

        assert message["client_id"] == CLIENT_ID
        assert message["payload"]["applications"][0]["process_name"] == "chrome.exe"
    finally:
        await client_connection.close()


@pytest.mark.asyncio
async def test_telemetry_does_not_reach_an_admin_watching_nobody(admin):
    """The fan-out this replaced pushed every client's data to every console.

    An admin that has selected nothing has nothing on screen to update, so it
    receives no telemetry — at the 50-client ceiling the old behaviour was
    roughly 4,000 application rows every 30 seconds to each console for nothing
    (issues.md D5). What is *recorded* is unaffected, which the assertion on the
    database is there to state rather than imply.
    """
    connection, received, port = admin

    from client import connection as client_connection
    from client.config import CLIENT_ID

    assert await client_connection.connect(HOST, port)
    try:
        assert await client_connection.register()
        await client_connection.send(
            create_message(
                "APP_DATA",
                {"applications": [{"process_name": "chrome.exe", "pid": 42}]},
                client_id=CLIENT_ID,
            )
        )
        await asyncio.sleep(0.4)

        assert [m for m in received if m.get("type") == "APP_DATA"] == []
        assert database.get_client_apps(CLIENT_ID) != []
    finally:
        await client_connection.close()


# ---------------------------------------------------------------------------
# Script validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_python_passes():
    ok, message = await validate_script("print('hello')\n", SCRIPT_TYPE_PYTHON)

    assert ok
    assert message == ""


@pytest.mark.asyncio
async def test_python_syntax_error_is_caught_before_sending():
    ok, message = await validate_script("print('unterminated\n", SCRIPT_TYPE_PYTHON)

    assert not ok
    assert "SyntaxError" in message or "Error" in message


@pytest.mark.asyncio
async def test_empty_script_is_rejected():
    ok, message = await validate_script("   \n", SCRIPT_TYPE_PYTHON)

    assert not ok
    assert "empty" in message.lower()


@pytest.mark.asyncio
async def test_unknown_script_type_is_rejected():
    ok, message = await validate_script("echo hi", "bash")

    assert not ok
    assert "Unsupported" in message


@pytest.mark.asyncio
async def test_balanced_powershell_passes():
    ok, _ = await validate_script("if ($true) { Write-Output 'ok' }", SCRIPT_TYPE_POWERSHELL)

    assert ok


@pytest.mark.asyncio
async def test_unbalanced_powershell_is_caught():
    ok, message = await validate_script("if ($true) { Write-Output 'ok'", SCRIPT_TYPE_POWERSHELL)

    assert not ok
    assert "Unbalanced" in message


@pytest.mark.asyncio
async def test_powershell_validation_does_not_execute():
    """Validation must never run the script. A command that would be
    obviously destructive still only gets parsed."""
    ok, _ = await validate_script("Remove-Item C:\\ -Recurse", SCRIPT_TYPE_POWERSHELL)

    assert ok  # balanced, so it parses - but nothing ran


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def test_extracts_plain_imports():
    assert extract_imports("import os\nimport sys\n") == ["os", "sys"]


def test_extracts_multiple_names_on_one_line():
    """A regex over `^import (\\w+)` would catch only the first of these."""
    assert extract_imports("import os, sys, json\n") == ["json", "os", "sys"]


def test_extracts_from_imports_as_the_module():
    assert extract_imports("from pathlib import Path\n") == ["pathlib"]


def test_extracts_parenthesised_multiline_imports():
    """The case a line-oriented regex gets most obviously wrong."""
    script = "from os import (\n    path,\n    sep,\n)\n"

    assert extract_imports(script) == ["os"]


def test_extracts_dotted_imports():
    assert extract_imports("import os.path\nfrom xml.etree import ElementTree\n") == [
        "os.path", "xml.etree",
    ]


def test_ignores_imports_inside_strings_and_comments():
    """The decisive advantage of parsing over pattern matching."""
    script = (
        '"""This docstring says import requests, which is not an import."""\n'
        "# import numpy\n"
        "message = 'import pandas'\n"
        "import os\n"
    )

    assert extract_imports(script) == ["os"]


def test_finds_imports_nested_in_functions():
    """Deferred imports are still imports."""
    script = "def work():\n    import subprocess\n    return subprocess\n"

    assert extract_imports(script) == ["subprocess"]


def test_skips_relative_imports():
    """A script is a lone file with no package around it."""
    assert extract_imports("from . import sibling\n") == []


def test_extraction_raises_on_bad_syntax():
    with pytest.raises(SyntaxError):
        extract_imports("import \n")


# ---------------------------------------------------------------------------
# Import policy
# ---------------------------------------------------------------------------


def test_classifies_stdlib_third_party_and_posix():
    result = classify_imports(["os", "requests", "fcntl", "json"])

    assert result["stdlib"] == ["os", "json"]
    assert result["third_party"] == ["requests"]
    assert result["posix_only"] == ["fcntl"]


def test_dotted_stdlib_is_classified_by_its_root():
    assert classify_imports(["os.path"])["stdlib"] == ["os.path"]


@pytest.mark.asyncio
async def test_stdlib_only_script_passes():
    result = await analyse_script(
        "import os\nimport subprocess\nprint(os.getcwd())\n", SCRIPT_TYPE_PYTHON
    )

    assert result["ok"], result["errors"]
    assert result["stdlib"] == ["os", "subprocess"]


@pytest.mark.asyncio
async def test_third_party_import_is_rejected():
    result = await analyse_script("import requests\n", SCRIPT_TYPE_PYTHON)

    assert not result["ok"]
    assert result["third_party"] == ["requests"]
    assert "no pip" in " ".join(result["errors"])


@pytest.mark.asyncio
async def test_unix_only_import_is_rejected_with_an_explanation():
    """The client is Windows; this compiles fine but could never run there."""
    result = await analyse_script("import fcntl\n", SCRIPT_TYPE_PYTHON)

    assert not result["ok"]
    assert result["posix_only"] == ["fcntl"]

    detail = " ".join(result["errors"])
    assert "Unix-only" in detail
    assert "msvcrt" in detail, "should point at the Windows alternative"


@pytest.mark.asyncio
async def test_unix_only_import_without_an_equivalent_still_explains():
    result = await analyse_script("import pwd\n", SCRIPT_TYPE_PYTHON)

    assert not result["ok"]
    assert "Unix-only" in " ".join(result["errors"])


@pytest.mark.asyncio
async def test_hidden_third_party_import_is_still_caught():
    """Buried inside a function, past a docstring mentioning other modules."""
    script = (
        '"""Uses only os and sys."""\n'
        "def go():\n"
        "    import numpy\n"
        "    return numpy\n"
    )

    result = await analyse_script(script, SCRIPT_TYPE_PYTHON)

    assert not result["ok"]
    assert result["third_party"] == ["numpy"]


@pytest.mark.asyncio
async def test_syntax_error_is_reported_before_import_analysis():
    result = await analyse_script("import requests\nif True\n", SCRIPT_TYPE_PYTHON)

    assert not result["ok"]
    assert "SyntaxError" in result["errors"][0]


@pytest.mark.asyncio
async def test_script_with_no_imports_passes():
    result = await analyse_script("print('hello')\n", SCRIPT_TYPE_PYTHON)

    assert result["ok"]
    assert result["stdlib"] == []


@pytest.mark.asyncio
async def test_powershell_skips_the_import_policy():
    """The policy is about Python's runtime; PowerShell ships with Windows."""
    result = await analyse_script("Get-Process | Stop-Process", SCRIPT_TYPE_POWERSHELL)

    assert result["ok"]


@pytest.mark.asyncio
async def test_development_fallback_is_flagged_as_a_warning():
    """Validating against the wrong interpreter is a caveat, not a silent
    assumption."""
    result = await analyse_script("import os\n", SCRIPT_TYPE_PYTHON)

    if not result["bundled"]:
        assert any("bundled runtime" in w for w in result["warnings"])


def test_check_summary_lists_accepted_imports():
    """Showing what passed teaches the rule; a bare OK does not."""
    summary = _describe_check({
        "ok": True, "errors": [], "warnings": [],
        "stdlib": ["os", "json"], "third_party": [], "posix_only": [],
        "unavailable": [], "bundled": True,
    })

    assert "os" in summary and "json" in summary


def test_check_summary_reports_failures():
    summary = _describe_check({
        "ok": False, "errors": ["Third-party imports are not allowed: requests"],
        "warnings": [], "stdlib": ["os"], "third_party": ["requests"],
        "posix_only": [], "unavailable": [], "bundled": True,
    })

    assert "requests" in summary
    assert "Allowed: os" in summary


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_client_model_exposes_rows():
    model = ClientListModel()
    model.setRows([{"client_id": "pc-01", "hostname": "lab1", "connected": True}])

    assert model.rowCount() == 1
    assert model.rows[0]["client_id"] == "pc-01"


def test_model_role_names_match_keys():
    model = ApplicationModel()
    names = {value.decode() for value in model.roleNames().values()}

    assert "process_name" in names
    assert "memory_mb" in names


def test_setting_rows_replaces_previous_contents():
    model = ApplicationModel()
    model.setRows([{"process_name": "a.exe"}, {"process_name": "b.exe"}])
    model.setRows([{"process_name": "c.exe"}])

    assert model.rowCount() == 1


# ---------------------------------------------------------------------------
# Report flattening
# ---------------------------------------------------------------------------


def test_format_bytes_scales_units():
    assert _format_bytes(512) == "512 B"
    assert _format_bytes(2048) == "2.0 KB"
    assert _format_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_format_bytes_tolerates_nonsense():
    assert _format_bytes(None) == "None"


def test_flatten_network_summary():
    rows = _flatten_report(
        REPORT_NETWORK_24H, {"bytes_sent": 1024, "bytes_received": 2048, "samples": 7}
    )

    assert [row["label"] for row in rows] == ["Sent", "Received", "Samples"]
    assert rows[0]["value"] == "1.0 KB"


def test_flatten_weekly_summary():
    rows = _flatten_report(
        REPORT_NETWORK_WEEKLY,
        [{"day": "2026-08-05", "bytes_sent": 1024, "bytes_received": 2048, "samples": 3}],
    )

    assert rows[0]["label"] == "2026-08-05"


def test_flatten_app_usage_handles_null_aggregates():
    """AVG() over no rows returns NULL; formatting must not blow up."""
    rows = _flatten_report(
        REPORT_APP_USAGE,
        [{"process_name": "chrome.exe", "samples": 2, "avg_cpu": None,
          "peak_memory_mb": None}],
    )

    assert rows[0]["label"] == "chrome.exe"
    assert "0.0% CPU" in rows[0]["value"]


def test_flatten_empty_report():
    assert _flatten_report(REPORT_NETWORK_24H, None) == []


# ---------------------------------------------------------------------------
# Backend behaviour that does not need a window
# ---------------------------------------------------------------------------


def test_backend_starts_disconnected():
    backend = Backend()

    assert backend.connected is False
    assert backend.selectedClient == ""


def test_selecting_a_client_swaps_the_live_view():
    """Per-client buffers mean switching selection does not lose data that
    already arrived for another machine."""
    backend = Backend()
    backend._live_apps = {
        "pc-01": [{"process_name": "a.exe"}],
        "pc-02": [{"process_name": "b.exe"}],
    }

    backend.selectedClient = "pc-01"
    assert backend.applications.rows[0]["process_name"] == "a.exe"

    backend.selectedClient = "pc-02"
    assert backend.applications.rows[0]["process_name"] == "b.exe"


def test_client_list_clears_a_selection_that_disappeared():
    backend = Backend()
    backend.selectedClient = "pc-gone"

    backend._handle_client_list(
        create_message("CLIENT_LIST", {"clients": [{"client_id": "pc-01"}]})
    )

    assert backend.selectedClient == ""


def test_commands_require_a_selected_client():
    backend = Backend()

    backend.terminateProcess("chrome.exe", False)

    assert "Select a client" in backend.status


# ---------------------------------------------------------------------------
# Time restrictions
# ---------------------------------------------------------------------------
#
# A scheduled block, distinct from a pause: it has a known end and the student
# sees it counting down. These test what goes on the wire; the enforcement it
# drives is covered in test_client.py.


class _RecordingConnection:
    """Stands in for EngineConnection, capturing commands instead of sending."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, list[str], dict]] = []
        # Selecting a client now declares a watch, so the stub has to model the
        # part of the interface that involves: whether it is connected, and the
        # declaration itself.
        self.connected = True
        self.watched: list[str] = []

    async def send_command(self, command_type, target_clients, parameters=None):
        self.sent.append((command_type, list(target_clients), parameters or {}))
        return True

    async def declare_watch(self, client_id):
        self.watched.append(client_id)
        return True


def _backend_with_connection(selected: str = "pc-01", rows=None) -> tuple:
    backend = Backend()
    connection = _RecordingConnection()
    backend._connection = connection
    if rows is not None:
        backend.clients.setRows(rows)
    backend.selectedClient = selected
    return backend, connection


async def _settle() -> None:
    """Let the task an ensure_future slot scheduled actually run."""
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_a_time_restriction_sends_a_start_and_an_end():
    backend, connection = _backend_with_connection()

    backend.setTimeRestriction(60, 0, False)
    await _settle()

    command_type, targets, parameters = connection.sent[0]
    start = datetime.fromisoformat(parameters["start"])
    end = datetime.fromisoformat(parameters["end"])

    assert command_type == MSG_SET_TIME_RESTRICTION
    assert targets == ["pc-01"]
    assert end - start == timedelta(minutes=60)


@pytest.mark.asyncio
async def test_a_delayed_block_starts_in_the_future():
    """Set up an exam lockout beforehand; the client's watchdog opens it."""
    backend, connection = _backend_with_connection()

    backend.setTimeRestriction(30, 15, False)
    await _settle()

    start = datetime.fromisoformat(connection.sent[0][2]["start"])

    assert start > datetime.now(timezone.utc) + timedelta(minutes=14)


@pytest.mark.asyncio
async def test_an_over_long_block_warns_that_the_client_will_shorten_it():
    """The cap is the client's, so this warns rather than silently clamping."""
    backend, connection = _backend_with_connection()

    backend.setTimeRestriction(MAX_BLOCK_HOURS * 60 + 30, 0, False)
    await _settle()

    assert connection.sent, "the command is still sent; the client applies the cap"
    assert "shorten" in backend.status


@pytest.mark.asyncio
async def test_blocking_the_room_targets_only_connected_clients():
    backend, connection = _backend_with_connection(
        rows=[
            {"client_id": "pc-01", "connected": True},
            {"client_id": "pc-02", "connected": False},
            {"client_id": "pc-03", "connected": True},
        ],
    )

    backend.setTimeRestriction(45, 0, True)
    await _settle()

    assert connection.sent[0][1] == ["pc-01", "pc-03"]


@pytest.mark.asyncio
async def test_blocking_the_room_with_nobody_connected_sends_nothing():
    backend, connection = _backend_with_connection(rows=[])

    backend.setTimeRestriction(45, 0, True)
    await _settle()

    assert connection.sent == []
    assert "No connected clients" in backend.status


@pytest.mark.asyncio
async def test_clearing_a_restriction_sends_the_clear_flag():
    backend, connection = _backend_with_connection()

    backend.clearTimeRestriction(False)
    await _settle()

    assert connection.sent[0][2] == {"clear": True}


@pytest.mark.asyncio
async def test_a_time_restriction_requires_a_selected_client():
    backend, connection = _backend_with_connection(selected="")

    backend.setTimeRestriction(60, 0, False)
    await _settle()

    assert connection.sent == []
    assert "Select a client" in backend.status


def test_the_cap_shown_in_the_gui_is_the_one_the_client_enforces():
    """Two copies of this number would drift; the GUI reads the shared one."""
    from client import lockout

    assert Backend().maxBlockHours == lockout.MAX_BLOCK_HOURS


# ---------------------------------------------------------------------------
# Application blacklist
# ---------------------------------------------------------------------------
#
# The standing list, distinct from terminateProcess which kills one process
# once. Both live in the policy panel and both are wanted.


@pytest.mark.asyncio
async def test_the_app_blacklist_is_sent_as_process_names():
    """The payload key has to match what client.policy.set_app_blacklist reads."""
    backend, connection = _backend_with_connection()

    backend.setAppBlacklist("steam.exe\ndiscord.exe")
    await _settle()

    command_type, targets, parameters = connection.sent[0]

    assert command_type == MSG_SET_APP_BLACKLIST
    assert targets == ["pc-01"]
    assert parameters == {"process_names": ["steam.exe", "discord.exe"]}


@pytest.mark.asyncio
async def test_the_app_blacklist_accepts_commas_and_blank_lines():
    backend, connection = _backend_with_connection()

    backend.setAppBlacklist("steam.exe, discord.exe\n\n  game.exe  \n")
    await _settle()

    assert connection.sent[0][2]["process_names"] == [
        "steam.exe", "discord.exe", "game.exe"
    ]


@pytest.mark.asyncio
async def test_an_empty_app_blacklist_clears_it():
    """Sending nothing is a real instruction, not a no-op to be swallowed."""
    backend, connection = _backend_with_connection()

    backend.setAppBlacklist("   \n  ")
    await _settle()

    assert connection.sent[0][2] == {"process_names": []}
    assert "cleared" in backend.status


@pytest.mark.asyncio
async def test_the_app_blacklist_requires_a_selected_client():
    backend, connection = _backend_with_connection(selected="")

    backend.setAppBlacklist("steam.exe")
    await _settle()

    assert connection.sent == []
    assert "Select a client" in backend.status
