"""Engine unit tests.

PHASE 1 PLACEHOLDER. The connection registry has real logic and is covered
below; everything else in the Engine is a stub, so its tests belong to Phase 2:

  - database.py store/get functions against a temp SQLite file
  - heartbeat-timeout reaping
  - command_log persistence and status updates
  - 24-hour and weekly aggregation
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from common.constants import ROLE_ADMIN, ROLE_CLIENT
from engine import connection_manager, database, main as engine_main


def _fake_writer() -> MagicMock:
    """A StreamWriter stand-in whose wait_closed can be awaited."""
    writer = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


@pytest.fixture(autouse=True)
def clear_registry():
    connection_manager.clear()
    yield
    connection_manager.clear()


def test_register_then_lookup():
    writer = MagicMock()
    connection_manager.register("pc-01", writer, ROLE_CLIENT, "127.0.0.1:1234")

    assert connection_manager.is_connected("pc-01")
    assert connection_manager.get_writer("pc-01") is writer
    assert connection_manager.connection_count() == 1


def test_unregister_is_idempotent():
    connection_manager.register("pc-01", MagicMock(), ROLE_CLIENT)
    connection_manager.unregister("pc-01")
    connection_manager.unregister("pc-01")

    assert not connection_manager.is_connected("pc-01")
    assert connection_manager.connection_count() == 0


def test_roles_are_kept_separate():
    connection_manager.register("pc-01", MagicMock(), ROLE_CLIENT)
    connection_manager.register("pc-02", MagicMock(), ROLE_CLIENT)
    connection_manager.register("admin-01", MagicMock(), ROLE_ADMIN)

    assert sorted(connection_manager.get_client_ids()) == ["pc-01", "pc-02"]
    assert connection_manager.get_admin_ids() == ["admin-01"]


def test_connected_clients_excludes_admins():
    connection_manager.register("pc-01", MagicMock(), ROLE_CLIENT)
    connection_manager.register("admin-01", MagicMock(), ROLE_ADMIN)

    listed = connection_manager.get_connected_clients()

    assert [entry["client_id"] for entry in listed] == ["pc-01"]


def test_reconnect_replaces_previous_writer():
    first, second = MagicMock(), MagicMock()
    connection_manager.register("pc-01", first, ROLE_CLIENT)
    connection_manager.register("pc-01", second, ROLE_CLIENT)

    assert connection_manager.get_writer("pc-01") is second
    assert connection_manager.connection_count() == 1


def test_find_stale_ignores_fresh_peers():
    connection_manager.register("pc-01", MagicMock(), ROLE_CLIENT)

    assert connection_manager.find_stale(timeout=60) == []


def test_find_stale_reports_silent_peers():
    connection_manager.register("pc-01", MagicMock(), ROLE_CLIENT)

    # Real elapsed time is needed rather than timeout=0: Windows' system clock
    # granularity is ~15.6ms, so registering and checking inside one tick gives
    # identical timestamps and nothing looks stale. 50ms clears that comfortably.
    time.sleep(0.05)

    assert connection_manager.find_stale(timeout=0.01) == ["pc-01"]


def test_touch_refreshes_last_seen():
    connection_manager.register("pc-01", MagicMock(), ROLE_CLIENT)
    time.sleep(0.05)
    connection_manager.touch("pc-01")

    assert connection_manager.find_stale(timeout=0.01) == []


# ---------------------------------------------------------------------------
# Stale-connection reaping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaper_drops_silent_peers(monkeypatch):
    """A peer that stops sending anything is dropped and its socket closed.

    The real intervals are 15s and 60s, so both are shortened here; they are
    module globals in engine.main because of `from engine.config import ...`.
    """
    monkeypatch.setattr(engine_main, "REAP_INTERVAL", 0.02)
    monkeypatch.setattr(engine_main, "CLIENT_HEARTBEAT_TIMEOUT", 0.01)
    writer = _fake_writer()
    connection_manager.register("pc-01", writer, ROLE_CLIENT)

    reaper = asyncio.create_task(engine_main.reap_stale_connections())
    await asyncio.sleep(0.15)
    engine_main.request_shutdown()
    await asyncio.wait_for(reaper, timeout=1.0)

    assert not connection_manager.is_connected("pc-01")
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_reaper_keeps_active_peers(monkeypatch):
    monkeypatch.setattr(engine_main, "REAP_INTERVAL", 0.02)
    monkeypatch.setattr(engine_main, "CLIENT_HEARTBEAT_TIMEOUT", 5.0)

    connection_manager.register("pc-01", _fake_writer(), ROLE_CLIENT)

    reaper = asyncio.create_task(engine_main.reap_stale_connections())
    await asyncio.sleep(0.1)
    engine_main.request_shutdown()
    await asyncio.wait_for(reaper, timeout=1.0)

    assert connection_manager.is_connected("pc-01")


@pytest.mark.asyncio
async def test_reaper_stops_promptly_on_shutdown(monkeypatch):
    """Shutdown must not wait out a full reap interval."""
    monkeypatch.setattr(engine_main, "REAP_INTERVAL", 30)

    reaper = asyncio.create_task(engine_main.reap_stale_connections())
    await asyncio.sleep(0.01)
    engine_main.request_shutdown()

    await asyncio.wait_for(reaper, timeout=1.0)


# ---------------------------------------------------------------------------
# Engine-side persistence wiring
# ---------------------------------------------------------------------------


def test_setup_db_creates_the_file(tmp_path):
    from engine import setup_db

    target = tmp_path / "fresh.db"

    assert setup_db.main([str(target)]) == 0
    assert target.exists()

    # Idempotent: re-running against an existing database must not fail.
    assert setup_db.main([str(target)]) == 0

    database.close_database()


def test_setup_db_reports_failure(tmp_path):
    """A path that cannot be opened returns non-zero rather than raising."""
    from engine import setup_db

    unwritable = tmp_path / "no_such_dir" / "x.db"

    assert setup_db.main([str(unwritable)]) == 1


@pytest.mark.asyncio
async def test_handlers_persist_monitoring_data():
    """command_handler routes each message type into the right table."""
    from engine import command_handler

    database.store_client("pc-01", "host", "127.0.0.1", "Windows")

    await command_handler.handle_app_data(
        "pc-01", {"applications": [{"process_name": "chrome.exe", "cpu_percent": 5.0}]}
    )
    await command_handler.handle_network_data(
        "pc-01", {"bytes_sent": 100, "bytes_received": 200}
    )
    await command_handler.handle_usb_event(
        "pc-01", {"event": "inserted", "device_name": "Kingston"}
    )

    assert database.get_client_apps("pc-01")[0]["process_name"] == "chrome.exe"
    assert database.get_network_summary("pc-01")["samples"] == 1
    assert database.get_usb_events("pc-01")[0]["device_name"] == "Kingston"
