"""Engine unit tests.

PHASE 1 PLACEHOLDER. The connection registry has real logic and is covered
below; everything else in the Engine is a stub, so its tests belong to Phase 2:

  - database.py store/get functions against a temp SQLite file
  - heartbeat-timeout reaping
  - command_log persistence and status updates
  - 24-hour and weekly aggregation
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from common.constants import ROLE_ADMIN, ROLE_CLIENT
from engine import connection_manager


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
