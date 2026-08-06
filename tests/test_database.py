"""Tests for engine.database — the only module that speaks SQL.

Every test runs against a fresh temp database, so ordering never matters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine import database


def _iso(when: datetime) -> str:
    """Format a datetime the way the database stores timestamps."""
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ago(**kwargs) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(**kwargs))


def _noon_days_ago(days: int, plus_minutes: int = 0) -> str:
    """Midday, `days` ago, as a stored timestamp.

    Day-bucketing tests must not use offsets like "2 hours ago": run near
    midnight UTC those straddle a date boundary and land in a different bucket
    than intended. Anchoring to midday keeps each sample unambiguously inside
    one day whatever time the suite runs. `days` must be >= 1 so the anchor is
    never in the future.
    """
    base = datetime.now(timezone.utc) - timedelta(days=days)
    anchored = base.replace(hour=12, minute=0, second=0, microsecond=0)
    return _iso(anchored + timedelta(minutes=plus_minutes))


@pytest.fixture(autouse=True)
def seed_client():
    """Give every test one registered client to hang data off.

    The temp database itself comes from the autouse fixture in conftest.py.
    """
    database.store_client("pc-01", "lab1-pc-01", "192.168.1.50", "Windows")


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def test_store_client_inserts():
    client = database.get_client("pc-01")

    assert client["hostname"] == "lab1-pc-01"
    assert client["ip_address"] == "192.168.1.50"
    assert client["os_type"] == "Windows"
    assert client["status"] == "active"


def test_store_client_upserts_rather_than_duplicating():
    database.store_client("pc-01", "renamed-host", "192.168.1.99", "Windows")

    assert len(database.get_all_clients()) == 1
    assert database.get_client("pc-01")["hostname"] == "renamed-host"


def test_get_client_returns_none_when_absent():
    assert database.get_client("nope") is None


def test_update_last_seen_advances_timestamp():
    before = database.get_client("pc-01")["last_seen"]
    database.update_client_last_seen("pc-01", status="idle")
    after = database.get_client("pc-01")

    assert after["last_seen"] >= before
    assert after["status"] == "idle"


def test_mark_client_offline():
    database.mark_client_offline("pc-01")

    assert database.get_client("pc-01")["status"] == "offline"


# ---------------------------------------------------------------------------
# Application data
# ---------------------------------------------------------------------------


def _app(name: str, cpu: float = 10.0, memory: float = 100.0, start: str | None = None):
    return {
        "process_name": name,
        "window_title": f"{name} window",
        "start_time": start or _iso(datetime.now(timezone.utc)),
        "cpu_percent": cpu,
        "memory_mb": memory,
    }


def test_store_app_data_writes_every_row():
    written = database.store_app_data("pc-01", [_app("chrome.exe"), _app("code.exe")])

    assert written == 2
    assert len(database.get_client_apps("pc-01")) == 2


def test_store_app_data_ignores_empty_batch():
    assert database.store_app_data("pc-01", []) == 0
    assert database.get_client_apps("pc-01") == []


def test_store_app_data_maps_cpu_percent_to_cpu_usage():
    """The wire field is cpu_percent; the column is cpu_usage."""
    database.store_app_data("pc-01", [_app("chrome.exe", cpu=42.5)])

    assert database.get_client_apps("pc-01")[0]["cpu_usage"] == 42.5


def test_get_client_apps_is_newest_first():
    database.store_app_data("pc-01", [_app("first.exe")])
    database.store_app_data("pc-01", [_app("second.exe")])

    assert database.get_client_apps("pc-01")[0]["process_name"] == "second.exe"


def test_get_client_apps_honours_limit():
    database.store_app_data("pc-01", [_app(f"p{i}.exe") for i in range(10)])

    assert len(database.get_client_apps("pc-01", limit=3)) == 3


def test_get_client_apps_is_scoped_to_one_client():
    database.store_client("pc-02", "lab1-pc-02", "192.168.1.51", "Windows")
    database.store_app_data("pc-02", [_app("other.exe")])

    assert database.get_client_apps("pc-01") == []


def test_app_usage_summary_aggregates_per_process():
    database.store_app_data(
        "pc-01",
        [_app("chrome.exe", cpu=10.0), _app("chrome.exe", cpu=30.0), _app("code.exe", cpu=5.0)],
    )

    summary = {row["process_name"]: row for row in database.get_app_usage_summary("pc-01")}

    assert summary["chrome.exe"]["samples"] == 2
    assert summary["chrome.exe"]["avg_cpu"] == 20.0
    assert summary["chrome.exe"]["peak_cpu"] == 30.0
    assert summary["code.exe"]["samples"] == 1


def test_app_usage_summary_excludes_rows_outside_the_window():
    database.store_app_data("pc-01", [_app("old.exe", start=_ago(days=3))])
    database.store_app_data("pc-01", [_app("recent.exe")])

    names = [row["process_name"] for row in database.get_app_usage_summary("pc-01", hours=24)]

    assert names == ["recent.exe"]


# ---------------------------------------------------------------------------
# Network aggregation
# ---------------------------------------------------------------------------


def _store_network_at(client_id: str, when: str, sent: int, received: int) -> None:
    """Insert a sample with an explicit timestamp.

    store_network_data always stamps 'now', so window and reset behaviour is
    exercised through a direct insert instead.
    """
    with database.get_connection() as connection:
        connection.execute(
            "INSERT INTO network_usage (client_id, timestamp, bytes_sent, bytes_received)"
            " VALUES (?, ?, ?, ?)",
            (client_id, when, sent, received),
        )


def test_network_summary_is_empty_without_samples():
    summary = database.get_network_summary("pc-01")

    assert summary["bytes_sent"] == 0
    assert summary["bytes_received"] == 0
    assert summary["samples"] == 0


def test_network_summary_differences_cumulative_counters():
    """Counters arrive cumulative since boot, so usage is the sum of deltas."""
    _store_network_at("pc-01", _ago(hours=3), 1_000, 5_000)
    _store_network_at("pc-01", _ago(hours=2), 3_000, 9_000)
    _store_network_at("pc-01", _ago(hours=1), 4_000, 11_000)

    summary = database.get_network_summary("pc-01", hours=24)

    assert summary["bytes_sent"] == 3_000
    assert summary["bytes_received"] == 6_000
    assert summary["samples"] == 3


def test_network_summary_skips_counter_resets():
    """A reboot resets the counters; that must not count as negative usage."""
    _store_network_at("pc-01", _ago(hours=4), 10_000, 20_000)
    _store_network_at("pc-01", _ago(hours=3), 12_000, 23_000)
    _store_network_at("pc-01", _ago(hours=2), 500, 800)      # rebooted
    _store_network_at("pc-01", _ago(hours=1), 1_500, 2_800)

    summary = database.get_network_summary("pc-01", hours=24)

    # 2,000 before the reset plus 1,000 after it; the reset itself contributes 0.
    assert summary["bytes_sent"] == 3_000
    assert summary["bytes_received"] == 5_000


def test_network_summary_respects_the_window():
    """Proves ISO-string timestamps compare correctly in a TIMESTAMP column."""
    _store_network_at("pc-01", _ago(days=5), 1_000, 1_000)
    _store_network_at("pc-01", _ago(days=4), 9_000, 9_000)
    _store_network_at("pc-01", _ago(hours=2), 100, 100)
    _store_network_at("pc-01", _ago(hours=1), 600, 600)

    summary = database.get_network_summary("pc-01", hours=24)

    assert summary["samples"] == 2
    assert summary["bytes_sent"] == 500


def test_network_summary_is_scoped_to_one_client():
    database.store_client("pc-02", "lab1-pc-02", "192.168.1.51", "Windows")
    _store_network_at("pc-02", _ago(hours=2), 1_000, 1_000)
    _store_network_at("pc-02", _ago(hours=1), 9_000, 9_000)

    assert database.get_network_summary("pc-01")["bytes_sent"] == 0


def test_weekly_summary_buckets_by_day():
    _store_network_at("pc-01", _noon_days_ago(3), 1_000, 1_000)
    _store_network_at("pc-01", _noon_days_ago(3, plus_minutes=30), 3_000, 3_000)
    _store_network_at("pc-01", _noon_days_ago(1), 100, 100)
    _store_network_at("pc-01", _noon_days_ago(1, plus_minutes=30), 900, 900)

    days = database.get_weekly_network_summary("pc-01")

    assert len(days) == 2
    assert days[0]["bytes_sent"] == 2_000
    assert days[1]["bytes_sent"] == 800


def test_weekly_summary_does_not_leak_across_day_boundaries():
    """Deltas are computed within each day, so a bucket never absorbs the
    previous day's cumulative total."""
    _store_network_at("pc-01", _noon_days_ago(2), 1_000, 1_000)
    _store_network_at("pc-01", _noon_days_ago(1), 50_000, 50_000)
    _store_network_at("pc-01", _noon_days_ago(1, plus_minutes=30), 50_500, 50_500)

    days = database.get_weekly_network_summary("pc-01")

    # The later day shows 500, not the 49,000 jump from the earlier day's
    # last reading.
    assert days[-1]["bytes_sent"] == 500


# ---------------------------------------------------------------------------
# USB events
# ---------------------------------------------------------------------------


def test_store_and_read_usb_events():
    database.store_usb_event("pc-01", {"event": "inserted", "device_name": "Kingston"})

    events = database.get_usb_events("pc-01")

    assert events[0]["device_name"] == "Kingston"
    assert events[0]["event_type"] == "inserted"


# ---------------------------------------------------------------------------
# Command audit trail
# ---------------------------------------------------------------------------


def test_log_command_records_the_dispatch():
    database.log_command("admin-01", "pc-01", "cmd_1", "TERMINATE_PROCESS",
                         {"process_name": "chrome.exe"})

    entry = database.get_command_history("pc-01")[0]

    assert entry["admin_id"] == "admin-01"
    assert entry["command_type"] == "TERMINATE_PROCESS"
    assert entry["status"] == "dispatched"
    assert "chrome.exe" in entry["command_data"]


def test_update_command_status():
    database.log_command("admin-01", "pc-01", "cmd_1", "SCREEN_CAPTURE", {})
    database.update_command_status("cmd_1", "success")

    assert database.get_command_history()[0]["status"] == "success"


def test_command_history_is_newest_first():
    database.log_command("admin-01", "pc-01", "cmd_1", "SCREEN_CAPTURE", {})
    database.log_command("admin-01", "pc-01", "cmd_2", "TERMINATE_PROCESS", {})

    assert database.get_command_history()[0]["command_id"] == "cmd_2"


def test_command_history_filters_by_client():
    database.store_client("pc-02", "lab1-pc-02", "192.168.1.51", "Windows")
    database.log_command("admin-01", "pc-02", "cmd_1", "SCREEN_CAPTURE", {})

    assert database.get_command_history("pc-01") == []


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def test_prune_removes_old_rows_and_keeps_recent_ones():
    database.store_app_data("pc-01", [_app("old.exe", start=_ago(days=40))])
    database.store_app_data("pc-01", [_app("recent.exe")])
    _store_network_at("pc-01", _ago(days=40), 1, 1)
    _store_network_at("pc-01", _ago(hours=1), 2, 2)

    removed = database.prune_older_than(days=30)

    assert removed["app_logs"] == 1
    assert removed["network_usage"] == 1
    assert [row["process_name"] for row in database.get_client_apps("pc-01")] == ["recent.exe"]


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------


def test_connection_is_reused_across_calls():
    """One long-lived connection, not one per call - the change that halved
    write latency in scripts/bench_database.py."""
    with database.get_connection() as first:
        pass
    with database.get_connection() as second:
        pass

    assert first is second


def test_retargeting_the_path_starts_a_fresh_database(tmp_path):
    database.store_app_data("pc-01", [_app("chrome.exe")])

    database.set_database_path(tmp_path / "other.db")
    database.init_database()

    assert database.get_client_apps("pc-01") == []


def test_failed_write_rolls_back():
    with pytest.raises(Exception):
        with database.get_connection() as connection:
            connection.execute(
                "INSERT INTO usb_events (client_id, device_name, event_type, timestamp)"
                " VALUES ('pc-01', 'x', 'inserted', 'now')"
            )
            connection.execute("INSERT INTO no_such_table VALUES (1)")

    assert database.get_usb_events("pc-01") == []
