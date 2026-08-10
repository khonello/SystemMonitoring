"""Client Agent tests.

Windows-specific collection (window titles, removable drives, idle time) is
exercised where it can be and skipped where it cannot, so the suite still runs
on the Linux side. The logic that matters most — tamper detection, the lockout
cap, hosts-file rendering, non-blocking script execution — is platform
independent and always runs.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from client import executor, lockout, policy, single_instance, state
from client.connection import reconnect_delay
from client.executor import handle_command, running_scripts, terminate_process
from client.monitors.network_monitor import collect_network_data
from client.monitors.process_monitor import collect_process_data
from client.monitors.usb_monitor import get_idle_time, poll_usb_events, reset_baseline
from common.constants import (
    DEFAULT_SCRIPT_TIMEOUT,
    MAX_SCRIPT_TIMEOUT,
    OVERLAY_MODE_PAUSE,
    OVERLAY_MODE_SCHEDULED,
    PAUSE_MAX_SECONDS,
    POLICY_MODE_BLACKLIST,
    POLICY_MODE_WHITELIST,
    RECONNECT_DELAY,
    RECONNECT_MAX_DELAY,
    STATUS_ERROR,
    STATUS_SUCCESS,
    STREAM_LIMIT,
    STREAM_OVERHEAD_ALLOWANCE,
)

IS_WINDOWS = sys.platform == "win32"
windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="Windows-only behaviour")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep every test out of the real %ProgramData%."""
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr("client.config.STATE_DIR", tmp_path / "state")
    yield


@pytest.fixture
def captured_messages(monkeypatch):
    """Collect what the executor would have sent."""
    sent: list[dict] = []

    async def fake_send(message):
        sent.append(message)
        return True

    monkeypatch.setattr("client.executor.connection.send", fake_send)
    return sent


# ---------------------------------------------------------------------------
# Reconnect backoff
# ---------------------------------------------------------------------------


def test_backoff_grows_exponentially():
    assert reconnect_delay(1) == RECONNECT_DELAY
    assert reconnect_delay(2) == RECONNECT_DELAY * 2
    assert reconnect_delay(3) == RECONNECT_DELAY * 4


def test_backoff_is_capped():
    assert reconnect_delay(50) == RECONNECT_MAX_DELAY


def test_backoff_handles_zeroth_attempt():
    assert reconnect_delay(0) == RECONNECT_DELAY


# ---------------------------------------------------------------------------
# Monitors
# ---------------------------------------------------------------------------


def test_process_collection_returns_expected_shape():
    processes = collect_process_data()

    assert isinstance(processes, list)
    assert processes, "expected at least this test's own interpreter"

    entry = processes[0]
    for key in ("process_name", "pid", "window_title", "cpu_percent",
                "memory_mb", "start_time"):
        assert key in entry


def test_process_collection_skips_noise():
    names = {entry["process_name"] for entry in collect_process_data()}

    assert "System Idle Process" not in names
    assert "svchost.exe" not in names


def test_network_collection_returns_counters():
    data = collect_network_data()

    assert set(data) >= {"bytes_sent", "bytes_received", "active_connections"}
    assert data["bytes_sent"] >= 0
    assert data["bytes_received"] >= 0


def test_idle_time_is_a_non_negative_float():
    idle = get_idle_time()

    assert isinstance(idle, float)
    assert idle >= 0


def test_usb_first_poll_establishes_a_baseline():
    """Drives already mounted when the agent starts are not insertions."""
    reset_baseline()

    assert poll_usb_events() == []


# ---------------------------------------------------------------------------
# Tamper-protected state
# ---------------------------------------------------------------------------


def test_state_round_trip():
    state.write_state("test.json", {"a": 1, "b": "two"})

    assert state.read_state("test.json") == {"a": 1, "b": "two"}


def test_reading_absent_state_returns_none():
    assert state.read_state("never-written.json") is None


def test_tampered_payload_is_detected():
    """Editing the file by hand must not go unnoticed."""
    state.write_state("test.json", {"end": "2026-01-01T00:00:00Z"})

    path = state.state_path("test.json")
    path.write_text(
        path.read_text(encoding="utf-8").replace("2026", "2020"), encoding="utf-8"
    )

    with pytest.raises(state.StateTampered):
        state.read_state("test.json")


def test_corrupt_state_file_is_detected():
    state.write_state("test.json", {"a": 1})
    state.state_path("test.json").write_text("not json at all", encoding="utf-8")

    with pytest.raises(state.StateTampered):
        state.read_state("test.json")


def test_state_write_is_atomic(tmp_path):
    """A crashed write must not leave a half-file that fails its own check."""
    state.write_state("test.json", {"first": True})
    state.write_state("test.json", {"second": True})

    assert state.read_state("test.json") == {"second": True}
    leftovers = list((tmp_path / "state").glob("*.tmp"))
    assert leftovers == []


# ---------------------------------------------------------------------------
# Single-instance guard
# ---------------------------------------------------------------------------

# Locks the same byte the guard does, without importing the client — the point
# is to prove the *operating system* releases it, so the child must not share
# any cleanup path with the code under test.
_HOLDER_SOURCE = """
import os, sys, time
handle = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)
if sys.platform == "win32":
    import msvcrt
    msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
print("locked", flush=True)
time.sleep(30)
"""


@pytest.fixture(autouse=True)
def release_instance_lock():
    """The guard holds a module-level handle; don't leak it between tests."""
    yield
    single_instance.release()


def test_lock_lives_in_the_per_client_state_directory():
    assert single_instance.lock_path().parent == state.STATE_DIR


def test_acquire_succeeds_when_nothing_is_running():
    assert single_instance.acquire() is True
    assert single_instance.lock_path().exists()


def test_acquire_is_refused_while_another_handle_holds_the_lock():
    """A second agent under the same client id must not start."""
    state.ensure_state_dir()
    other = os.open(single_instance.lock_path(), os.O_CREAT | os.O_RDWR)
    single_instance._lock(other)
    try:
        assert single_instance.acquire() is False
    finally:
        single_instance._unlock(other)
        os.close(other)

    assert single_instance.acquire() is True, "released lock should be takeable"


def test_release_allows_a_later_acquire():
    assert single_instance.acquire() is True
    single_instance.release()
    assert single_instance.acquire() is True


def test_a_second_call_in_one_process_is_idempotent():
    assert single_instance.acquire() is True
    assert single_instance.acquire() is True


def test_lock_is_released_when_the_holder_is_killed():
    """The crash-restart case: a hard kill must not leave the agent locked out.

    This is the whole reason the guard is an OS lock rather than a heartbeat
    timestamp — an agent killed at T and restarted seconds later has to be able
    to start, or a crash keeps the machine unenforced.
    """
    state.ensure_state_dir()
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER_SOURCE, str(single_instance.lock_path())],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        assert single_instance.acquire() is False, "holder is alive"
    finally:
        holder.kill()
        holder.wait(timeout=10)
        holder.stdout.close()

    assert single_instance.acquire() is True, "OS should drop the dead holder's lock"


def test_an_unopenable_lock_still_lets_the_agent_start(monkeypatch):
    """Fail open on environment problems, closed only on a real duplicate.

    Refusing to start because the lock file could not be opened would leave the
    machine with no agent enforcing anything — worse than the duplicate this
    guards against.
    """
    real_open = os.open

    def refuse_the_lock(path, *args, **kwargs):
        if str(path).endswith(single_instance.LOCK_FILE):
            raise PermissionError("state directory is not writable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(single_instance.os, "open", refuse_the_lock)

    assert single_instance.acquire() is True


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------


def _window(start_offset_h: float, end_offset_h: float):
    now = datetime.now(timezone.utc)
    return now + timedelta(hours=start_offset_h), now + timedelta(hours=end_offset_h)


def test_block_window_is_capped_at_two_hours():
    """A safety timeout against the overlay's own failure modes, not a network
    response — enforcement is entirely local."""
    start, end = _window(0, 8)

    stored = lockout.store_schedule(start, end)

    duration = lockout._parse(stored["end"]) - start
    assert duration == timedelta(hours=lockout.MAX_BLOCK_HOURS)


def test_short_block_window_is_left_alone():
    start, end = _window(0, 1)

    stored = lockout.store_schedule(start, end)

    assert lockout._parse(stored["end"]) == end


def test_active_window_reports_blocked():
    lockout.store_schedule(*_window(-0.5, 0.5))

    assert lockout.is_blocked_now() is True


def test_past_window_reports_unblocked():
    lockout.store_schedule(*_window(-3, -2))

    assert lockout.is_blocked_now() is False


def test_future_window_reports_unblocked():
    lockout.store_schedule(*_window(1, 2))

    assert lockout.is_blocked_now() is False


def test_no_schedule_reports_unblocked():
    assert lockout.is_blocked_now() is False


def test_tampered_schedule_fails_closed():
    """Editing the schedule to end a block early must not release the machine."""
    lockout.store_schedule(*_window(-0.5, 0.5))

    path = state.state_path(state.SCHEDULE_FILE)
    path.write_text(path.read_text(encoding="utf-8").replace("2026", "2020"),
                    encoding="utf-8")

    schedule = lockout.load_schedule()

    assert schedule["tampered"] is True
    assert lockout.is_blocked_now(schedule) is True


def test_unparseable_times_fail_closed():
    state.write_state(state.SCHEDULE_FILE, {"start": "nonsense", "end": "also nonsense"})

    assert lockout.is_blocked_now() is True


def test_apply_command_rejects_backwards_window():
    start, end = _window(2, 1)

    result = lockout.apply_command({"start": start.isoformat(), "end": end.isoformat()})

    assert result["status"] == "error"


def test_apply_command_rejects_missing_end():
    assert lockout.apply_command({})["status"] == "error"


def test_apply_command_can_clear(monkeypatch):
    monkeypatch.setattr(lockout, "stop_overlay", lambda: None)
    lockout.store_schedule(*_window(-0.5, 0.5))

    result = lockout.apply_command({"clear": True})

    assert result["status"] == "success"
    assert lockout.is_blocked_now() is False


# ---------------------------------------------------------------------------
# Indeterminate pause
# ---------------------------------------------------------------------------


@pytest.fixture
def quiet_overlay(monkeypatch):
    """Record overlay calls without launching a window."""
    calls = []
    monkeypatch.setattr(
        lockout, "start_overlay",
        lambda end, mode=OVERLAY_MODE_SCHEDULED: calls.append(("start", mode)) or True,
    )
    monkeypatch.setattr(lockout, "stop_overlay", lambda: calls.append(("stop", None)))
    monkeypatch.setattr(lockout, "overlay_running", lambda: False)
    return calls


def test_pause_is_capped_at_one_hour():
    """The cap is a fail-safe against an absent admin, not a user-facing
    policy — an unattended pause must lapse."""
    stored = lockout.store_pause(datetime.now(timezone.utc) + timedelta(hours=8))

    remaining = lockout._parse(stored["until"]) - datetime.now(timezone.utc)
    assert remaining <= timedelta(seconds=PAUSE_MAX_SECONDS + 1)


def test_pause_reports_active():
    lockout.store_pause(datetime.now(timezone.utc) + timedelta(minutes=10))

    assert lockout.is_paused() is True


def test_lapsed_pause_reports_inactive():
    lockout.store_pause(datetime.now(timezone.utc) - timedelta(minutes=1))

    assert lockout.is_paused() is False


def test_no_pause_reports_inactive():
    assert lockout.is_paused() is False


def test_tampered_pause_fails_closed():
    lockout.store_pause(datetime.now(timezone.utc) + timedelta(minutes=10))

    path = state.state_path(state.PAUSE_FILE)
    path.write_text(path.read_text(encoding="utf-8").replace("2026", "2020"),
                    encoding="utf-8")

    pause = lockout.load_pause()

    assert pause["tampered"] is True
    assert lockout.is_paused(pause) is True


def test_pause_command_sets_and_reports_expiry(quiet_overlay):
    result = lockout.apply_pause_command({"action": "pause"})

    assert result["status"] == "success"
    assert lockout.is_paused() is True
    assert lockout._parse(result["pause_until"]) is not None


def test_pause_command_clamps_a_long_request(quiet_overlay):
    result = lockout.apply_pause_command({"action": "pause", "seconds": 99_999})

    remaining = lockout._parse(result["pause_until"]) - datetime.now(timezone.utc)
    assert remaining <= timedelta(seconds=PAUSE_MAX_SECONDS + 1)


def test_resume_clears_the_pause(quiet_overlay):
    lockout.apply_pause_command({"action": "pause"})

    result = lockout.apply_pause_command({"action": "resume"})

    assert result["status"] == "success"
    assert lockout.is_paused() is False


def test_unknown_pause_action_is_rejected(quiet_overlay):
    assert lockout.apply_pause_command({"action": "freeze"})["status"] == "error"


def test_pause_takes_precedence_over_a_schedule(quiet_overlay):
    """Both can be active. The pause is the live admin action and shows no
    countdown, so it wins."""
    lockout.store_schedule(*_window(-0.5, 0.5))
    lockout.store_pause(datetime.now(timezone.utc) + timedelta(minutes=10))

    lockout.enforce_once()

    assert ("start", OVERLAY_MODE_PAUSE) in quiet_overlay


def test_dropping_a_pause_falls_back_to_an_active_schedule(quiet_overlay):
    """Resuming must not release a machine that is still inside a scheduled
    block — it should revert to the countdown."""
    lockout.store_schedule(*_window(-0.5, 0.5))
    lockout.store_pause(datetime.now(timezone.utc) + timedelta(minutes=10))
    lockout.enforce_once()

    lockout.clear_pause()
    quiet_overlay.clear()
    lockout.enforce_once()

    assert ("start", OVERLAY_MODE_SCHEDULED) in quiet_overlay


def test_dropping_a_pause_with_no_schedule_releases_the_machine(monkeypatch):
    calls = []
    monkeypatch.setattr(lockout, "start_overlay", lambda *a, **k: True)
    monkeypatch.setattr(lockout, "stop_overlay", lambda: calls.append("stop"))
    monkeypatch.setattr(lockout, "overlay_running", lambda: True)

    lockout.clear_pause()
    lockout.enforce_once()

    assert calls == ["stop"]


def test_pause_expiry_is_exposed_for_the_admin_warning():
    lockout.store_pause(datetime.now(timezone.utc) + timedelta(minutes=10))

    assert lockout.pause_expires_at() is not None


def test_pause_expiry_is_none_when_not_paused():
    assert lockout.pause_expires_at() is None


@pytest.mark.asyncio
async def test_pause_command_dispatches(captured_messages, quiet_overlay):
    await handle_command({
        "type": "SET_PAUSE",
        "command_id": "cmd_pause",
        "payload": {"action": "pause"},
    })

    assert captured_messages[0]["payload"]["status"] == "success"
    assert lockout.is_paused() is True


# ---------------------------------------------------------------------------
# Website policy
# ---------------------------------------------------------------------------


def test_hosts_block_covers_bare_and_www():
    """A browser reaches www.example.com without the bare domain resolving, so
    blocking one form alone does not bite."""
    rendered = policy.render_managed_block(POLICY_MODE_BLACKLIST, ["facebook.com"])

    assert "127.0.0.1 facebook.com" in rendered
    assert "127.0.0.1 www.facebook.com" in rendered


def test_hosts_block_normalises_urls():
    rendered = policy.render_managed_block(
        POLICY_MODE_BLACKLIST, ["https://YouTube.com/watch?v=x", "  http://bbc.co.uk  "]
    )

    assert "127.0.0.1 youtube.com" in rendered
    assert "127.0.0.1 bbc.co.uk" in rendered


def test_hosts_block_records_the_mode():
    """Mode is never inferred - it is written into the file itself."""
    rendered = policy.render_managed_block(POLICY_MODE_WHITELIST, ["example.com"])

    assert "# mode=whitelist" in rendered


def test_managed_block_is_delimited():
    rendered = policy.render_managed_block(POLICY_MODE_BLACKLIST, ["x.com"])

    assert rendered.startswith(policy.BEGIN_MARKER)
    assert rendered.rstrip().endswith(policy.END_MARKER)


def test_stripping_leaves_unmanaged_entries_untouched():
    """An administrator's own hosts entries must survive a policy change."""
    original = (
        "127.0.0.1 localhost\n"
        "10.0.0.1 internal.printer\n"
        + policy.render_managed_block(POLICY_MODE_BLACKLIST, ["blocked.com"])
        + "192.168.1.1 router\n"
    )

    stripped = policy.strip_managed_block(original)

    assert "internal.printer" in stripped
    assert "router" in stripped
    assert "blocked.com" not in stripped
    assert policy.BEGIN_MARKER not in stripped


def test_stripping_is_idempotent():
    plain = "127.0.0.1 localhost\n"

    assert policy.strip_managed_block(plain) == plain


def test_unknown_policy_mode_is_rejected():
    result = policy.apply_website_policy("allowlist", ["x.com"])

    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Application blacklist
# ---------------------------------------------------------------------------


def test_blacklist_is_normalised():
    result = policy.set_app_blacklist(["  Steam.exe ", "DISCORD.EXE", ""])

    assert result["blocked"] == ["discord.exe", "steam.exe"]


def test_blacklist_persists_to_state():
    policy.set_app_blacklist(["steam.exe"])

    assert policy.load_cached_policy()["app_blacklist"] == ["steam.exe"]


def test_empty_blacklist_terminates_nothing():
    policy.set_app_blacklist([])

    assert policy.enforce_app_blacklist() == []


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_command_is_reported_not_raised(captured_messages):
    await handle_command({"type": "NO_SUCH_COMMAND", "command_id": "cmd_1", "payload": {}})

    assert captured_messages[0]["payload"]["status"] == "error"
    assert "Unknown command" in captured_messages[0]["payload"]["message"]


@pytest.mark.asyncio
async def test_terminating_an_absent_process_reports_cleanly():
    result = await terminate_process("definitely-not-running-xyz.exe")

    assert result["status"] == "error"
    assert "No process named" in result["message"]


@pytest.mark.asyncio
async def test_terminate_process_requires_a_name():
    assert (await terminate_process(""))["status"] == "error"


@pytest.mark.asyncio
async def test_invalid_script_is_rejected_before_launch(captured_messages, tmp_path, monkeypatch):
    """Re-validated on arrival even though the Admin already checked it."""
    monkeypatch.setattr("client.executor.SCRIPT_LOG_DIR", tmp_path)

    await handle_command({
        "type": "EXECUTE_SCRIPT",
        "command_id": "cmd_bad",
        "payload": {"script": "print('unterminated\n", "script_type": "python"},
    })

    complete = [m for m in captured_messages if m["type"] == "COMMAND_COMPLETE"]
    assert complete, "expected a COMMAND_COMPLETE rejection"
    assert complete[0]["payload"]["status"] == "error"
    assert "validation" in complete[0]["payload"]["message"].lower()
    assert list(tmp_path.glob("*.py")) == [], "rejected script should be cleaned up"


@pytest.mark.asyncio
async def test_unsupported_script_type_is_rejected(captured_messages, tmp_path, monkeypatch):
    monkeypatch.setattr("client.executor.SCRIPT_LOG_DIR", tmp_path)

    await handle_command({
        "type": "EXECUTE_SCRIPT",
        "command_id": "cmd_sh",
        "payload": {"script": "echo hi", "script_type": "bash"},
    })

    assert "Unsupported script_type" in captured_messages[0]["payload"]["message"]


@pytest.mark.asyncio
async def test_script_runs_and_streams_output(captured_messages, tmp_path, monkeypatch):
    """The whole lifecycle: accepted immediately, output streamed, one
    COMMAND_COMPLETE, scratch files removed."""
    monkeypatch.setattr("client.executor.SCRIPT_LOG_DIR", tmp_path)
    monkeypatch.setattr("client.executor.TAIL_POLL_INTERVAL", 0.05)

    await handle_command({
        "type": "EXECUTE_SCRIPT",
        "command_id": "cmd_ok",
        "payload": {"script": "print('hello from the script')\n", "script_type": "python"},
    })

    types = [m["type"] for m in captured_messages]
    assert types[0] == "COMMAND_ACCEPTED", "launch must be acknowledged before completion"

    for _ in range(100):
        if any(m["type"] == "COMMAND_COMPLETE" for m in captured_messages):
            break
        await asyncio.sleep(0.05)

    output = "".join(
        m["payload"]["chunk"] for m in captured_messages if m["type"] == "COMMAND_OUTPUT"
    )
    complete = [m for m in captured_messages if m["type"] == "COMMAND_COMPLETE"]

    assert "hello from the script" in output
    assert len(complete) == 1, "exactly one COMMAND_COMPLETE"
    assert complete[0]["payload"]["returncode"] == 0
    assert list(tmp_path.glob("cmd_ok.*")) == [], "scratch files should be cleared"


@pytest.mark.asyncio
async def test_long_running_script_does_not_block_the_acknowledgement(
    captured_messages, tmp_path, monkeypatch
):
    """The point of the whole design: a script that never exits must still be
    acknowledged straight away."""
    monkeypatch.setattr("client.executor.SCRIPT_LOG_DIR", tmp_path)
    monkeypatch.setattr("client.executor.TAIL_POLL_INTERVAL", 0.05)

    script = "import time\nprint('started', flush=True)\ntime.sleep(30)\n"

    await asyncio.wait_for(
        handle_command({
            "type": "EXECUTE_SCRIPT",
            "command_id": "cmd_long",
            "payload": {"script": script, "script_type": "python"},
        }),
        timeout=20,
    )

    assert captured_messages[0]["type"] == "COMMAND_ACCEPTED"
    assert "cmd_long" in running_scripts

    result = await terminate_script_and_wait("cmd_long")
    assert result["status"] == "success"


async def terminate_script_and_wait(command_id: str) -> dict:
    from client.executor import terminate_script

    result = await terminate_script(command_id, force=True)
    for _ in range(60):
        if command_id not in running_scripts:
            break
        await asyncio.sleep(0.05)
    return result


@pytest.mark.asyncio
async def test_terminating_an_unknown_script_reports_cleanly():
    from client.executor import terminate_script

    result = await terminate_script("cmd_never_existed")

    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Execution time cap
# ---------------------------------------------------------------------------


def test_timeout_defaults_when_unspecified():
    from client.executor import clamp_timeout

    assert clamp_timeout(None) == DEFAULT_SCRIPT_TIMEOUT
    assert clamp_timeout("") == DEFAULT_SCRIPT_TIMEOUT
    assert clamp_timeout("nonsense") == DEFAULT_SCRIPT_TIMEOUT
    assert clamp_timeout(0) == DEFAULT_SCRIPT_TIMEOUT
    assert clamp_timeout(-5) == DEFAULT_SCRIPT_TIMEOUT


def test_timeout_is_clamped_to_the_ceiling():
    """An admin must not be able to opt out of the cap."""
    from client.executor import clamp_timeout

    assert clamp_timeout(MAX_SCRIPT_TIMEOUT * 10) == MAX_SCRIPT_TIMEOUT


def test_reasonable_timeout_is_honoured():
    from client.executor import clamp_timeout

    assert clamp_timeout(60) == 60
    assert clamp_timeout("120") == 120


@pytest.mark.asyncio
async def test_overrunning_script_is_stopped_and_reported_as_timeout(
    captured_messages, tmp_path, monkeypatch
):
    """A script that outlives its limit is killed, and reported distinctly from
    a crash so the operator can tell the two apart."""
    monkeypatch.setattr("client.executor.SCRIPT_LOG_DIR", tmp_path)
    monkeypatch.setattr("client.executor.TAIL_POLL_INTERVAL", 0.05)
    monkeypatch.setattr("client.executor.SCRIPT_KILL_GRACE", 2.0)

    script = "import time\nprint('working', flush=True)\ntime.sleep(60)\n"

    await handle_command({
        "type": "EXECUTE_SCRIPT",
        "command_id": "cmd_slow",
        "payload": {"script": script, "script_type": "python", "timeout_seconds": 1},
    })

    accepted = [m for m in captured_messages if m["type"] == "COMMAND_ACCEPTED"]
    assert accepted, "launch must still be acknowledged immediately"
    assert accepted[0]["payload"]["timeout_seconds"] == 1

    for _ in range(200):
        if any(m["type"] == "COMMAND_COMPLETE" for m in captured_messages):
            break
        await asyncio.sleep(0.05)

    complete = [m for m in captured_messages if m["type"] == "COMMAND_COMPLETE"]
    assert len(complete) == 1
    assert complete[0]["payload"]["status"] == "timeout"
    assert "execution limit" in complete[0]["payload"]["message"]
    assert "cmd_slow" not in running_scripts
    assert list(tmp_path.glob("cmd_slow.*")) == [], "scratch files still cleared"


@pytest.mark.asyncio
async def test_quick_script_is_unaffected_by_the_cap(
    captured_messages, tmp_path, monkeypatch
):
    """The cap must not interfere with the normal case."""
    monkeypatch.setattr("client.executor.SCRIPT_LOG_DIR", tmp_path)
    monkeypatch.setattr("client.executor.TAIL_POLL_INTERVAL", 0.05)

    await handle_command({
        "type": "EXECUTE_SCRIPT",
        "command_id": "cmd_quick",
        "payload": {"script": "print('fast')\n", "script_type": "python",
                    "timeout_seconds": 60},
    })

    for _ in range(200):
        if any(m["type"] == "COMMAND_COMPLETE" for m in captured_messages):
            break
        await asyncio.sleep(0.05)

    complete = [m for m in captured_messages if m["type"] == "COMMAND_COMPLETE"]
    assert complete[0]["payload"]["status"] == "success"


# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------


@windows_only
@pytest.mark.asyncio
async def test_screen_capture_produces_an_image():
    from client.executor import capture_screen

    result = await capture_screen(quality=40)

    # A headless session legitimately cannot capture; both outcomes are valid,
    # but a success must carry a real payload.
    if result["status"] == "success":
        assert result["format"] == "jpeg"
        assert result["width"] > 0
        assert len(result["image_base64"]) > 1000
    else:
        assert "message" in result


@pytest.mark.asyncio
async def test_capture_refuses_a_payload_over_the_message_budget(monkeypatch):
    """Refused with a reason, rather than handed to the framing to explode on.

    A line over STREAM_LIMIT makes asyncio's reader raise mid-stream, costing
    the agent its connection and reporting nothing about the actual cause
    (issues.md B18).
    """
    oversized = "A" * (STREAM_LIMIT - STREAM_OVERHEAD_ALLOWANCE + 1)
    monkeypatch.setattr(
        executor, "_grab_screen", lambda quality: (oversized, 7680, 4320, len(oversized))
    )

    result = await executor.capture_screen(quality=95)

    assert result["status"] == STATUS_ERROR
    assert "quality" in result["message"]
    assert "image_base64" not in result


@pytest.mark.asyncio
async def test_a_capture_within_the_budget_is_returned(monkeypatch):
    monkeypatch.setattr(
        executor, "_grab_screen", lambda quality: ("QUJD", 1920, 1080, 3)
    )

    result = await executor.capture_screen()

    assert result["status"] == STATUS_SUCCESS
    assert result["image_base64"] == "QUJD"


# ---------------------------------------------------------------------------
# Per-client state directory (issues.md B21)
# ---------------------------------------------------------------------------


def test_state_component_cannot_escape_the_state_root():
    """CLIENT_ID comes from the environment, so it reaches the path unvalidated."""
    from client.config import STATE_ROOT, state_component

    for hostile in ("../../Windows/System32", "..", "/etc/passwd", r"C:\Windows", "."):
        component = state_component(hostile)

        assert "/" not in component and "\\" not in component
        assert component not in {".", ".."}
        # The decisive check: joining it stays inside the root.
        assert STATE_ROOT.resolve() in (STATE_ROOT / component).resolve().parents


def test_state_component_distinguishes_ids_that_sanitise_alike():
    """Sanitising is lossy, and two machines sharing state is the bug being fixed."""
    from client.config import state_component

    assert state_component("lab1/pc-01") != state_component("lab1_pc-01")


def test_state_component_is_stable_for_the_same_id():
    from client.config import state_component

    assert state_component("lab1-pc-07") == state_component("lab1-pc-07")


def test_state_component_survives_an_id_with_nothing_usable_in_it():
    from client.config import STATE_ROOT, state_component

    component = state_component("///")

    assert component
    assert STATE_ROOT.resolve() in (STATE_ROOT / component).resolve().parents


def test_two_clients_on_one_machine_get_separate_directories():
    """The whole point of B21: shared state meant they overwrote each other."""
    from client.config import STATE_ROOT, state_component

    first = STATE_ROOT / state_component("lab1-pc-01")
    second = STATE_ROOT / state_component("lab1-pc-02")

    assert first != second
    assert first.parent == second.parent == STATE_ROOT


@windows_only
def test_installer_pins_the_client_id_into_both_commands():
    """A service and a Scheduled Task inherit neither the installer's
    environment nor each other's, so an id left to be re-derived could resolve
    differently and point the watchdog at the wrong state."""
    from client.config import CLIENT_ID
    from client.install_service import agent_command, watchdog_command

    assert f"--id {CLIENT_ID}" in agent_command()
    assert f"--id {CLIENT_ID}" in watchdog_command()


def test_the_watchdog_applies_its_id_to_the_environment(monkeypatch):
    """A Scheduled Task under SYSTEM inherits nothing from the agent, so without
    --id it would read a different state directory, find no schedule, and
    release a machine that should still be blocked."""
    import os

    from client import watchdog

    monkeypatch.delenv("CLIENT_ID", raising=False)

    # No schedule is stored, so enforce_once finds nothing to do and the pass is
    # a no-op against the isolated state directory this suite uses.
    assert watchdog.main(["--id", "probe-id"]) == 0
    assert os.environ["CLIENT_ID"] == "probe-id"


def test_the_watchdog_runs_without_an_id():
    """It still has to work when the id comes from the environment instead."""
    from client import watchdog

    assert watchdog.main([]) == 0
