"""Client Agent unit tests.

PHASE 1 PLACEHOLDER. Only the reconnect backoff has real logic today. The
monitors and the executor are stubs, so their tests belong to Phase 4:

  - collect_process_data shape, with psutil mocked
  - execute_script launching without awaiting completion
  - tail_log_and_report reading only when the log file has grown
  - terminate_script targeting by command_id rather than process name
  - the %ProgramData% state store failing closed on a bad HMAC
"""

from __future__ import annotations

import pytest

from client.connection import reconnect_delay
from client.executor import handle_command
from client.monitors.network_monitor import collect_network_data
from client.monitors.process_monitor import collect_process_data
from client.monitors.usb_monitor import get_idle_time, poll_usb_events
from common.constants import RECONNECT_DELAY, RECONNECT_MAX_DELAY


def test_backoff_grows_exponentially():
    assert reconnect_delay(1) == RECONNECT_DELAY
    assert reconnect_delay(2) == RECONNECT_DELAY * 2
    assert reconnect_delay(3) == RECONNECT_DELAY * 4


def test_backoff_is_capped():
    assert reconnect_delay(50) == RECONNECT_MAX_DELAY


def test_backoff_handles_zeroth_attempt():
    assert reconnect_delay(0) == RECONNECT_DELAY


# --- Stub contracts ---------------------------------------------------------
# These assert the *shape* the Phase 4 implementations must keep, so a change
# that breaks the caller's expectations fails here rather than at runtime.


def test_process_collector_returns_a_list():
    assert collect_process_data() == []


def test_network_collector_returns_expected_keys():
    data = collect_network_data()

    assert set(data) >= {"bytes_sent", "bytes_received", "active_connections"}


def test_usb_collector_returns_a_list():
    assert poll_usb_events() == []


def test_idle_time_is_a_float():
    assert isinstance(get_idle_time(), float)


@pytest.mark.asyncio
async def test_unknown_command_does_not_raise(monkeypatch):
    """An unrecognised command must be reported, not crash the listener."""
    sent = []

    async def fake_send(message):
        sent.append(message)
        return True

    monkeypatch.setattr("client.executor.connection.send", fake_send)

    await handle_command({"type": "NO_SUCH_COMMAND", "command_id": "cmd_1", "payload": {}})

    assert sent[0]["payload"]["status"] == "error"
    assert "Unknown command" in sent[0]["payload"]["message"]
