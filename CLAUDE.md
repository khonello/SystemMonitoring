# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Two root-level docs track the work: **`todo.md`** is the phase-by-phase plan, and **`issues.md`** logs known bugs, deferred decisions and unverified claims. Read both before starting a phase — `issues.md` marks which items block which phase.

Phases 0–3 are complete: the Engine and the Admin GUI are fully implemented and tested. The Client Agent's monitors and executor are still deliberate stubs (Phase 4) — commands reach it, get audited, and come back "not implemented", which is the expected state.

`issues.md` section A lists decisions only the user can make (retention period, institutional approval, TLS scope). Don't try to resolve those in code.

`README.md` is the design specification, including reference implementations as fenced code blocks. Where the working code and the README disagree, the code is newer — the deviations and their reasons are recorded in `todo.md`.

## Commands

Run everything through the venv. The project is installed editable, which is what makes `from common.protocol import ...` resolve from every entry point.

```powershell
.\.venv\Scripts\python.exe -m pytest -q                    # 126 tests
.\.venv\Scripts\python.exe -m pytest -q --cov=engine --cov=common --cov=admin_gui
.\.venv\Scripts\python.exe -m scripts.bench_database       # SQLite write cost
.\.venv\Scripts\python.exe -m client.main                  # Client Agent
.\.venv\Scripts\python.exe -m admin_gui.main               # Administrator GUI
```

**The Engine runs under WSL**, not Windows — it is Linux-only by design (asyncio/epoll). It imports only the standard library, so WSL needs no venv:

```bash
wsl -- bash -lc "cd /mnt/c/.../SystemMonitoring && python3 -m engine.main"
```

WSL2 localhost forwarding means the Windows client reaches it at `127.0.0.1:5000` unchanged. `ENGINE_LOG_LEVEL=DEBUG` surfaces heartbeats; `DEV_BYPASS_AUTH=1` skips the handshake.

Tests use `pytest-asyncio` in strict mode — async tests need an explicit `@pytest.mark.asyncio`.

## Architecture

Three deployable packages, each on a different machine:

- **Engine** (`engine/`) — Linux only, Python + `asyncio`. Central hub: accepts client TCP connections, routes commands between admin and clients, stores monitoring data. Deliberately Linux-only because asyncio there is backed by `epoll`. Listens on port 5000.
- **Client Agent** (`client/`) — Windows only, headless. Persistent connection to the Engine, collects metrics via `psutil`, executes admin commands. Spawns two bundled helper executables **on demand, not persistently**: a dialog exe (shutdown/grace warnings) and an overlay exe (time-based lockout).
- **Administrator Client** (`admin_gui/`) — Windows, Qt 6 + QML over a Python backend.

Wire protocol is newline-delimited JSON over TCP, UTF-8. Every message has `type`, `client_id`, `timestamp`, `payload`. Message types are dispatched through a `handlers` dict in `process_message` (Engine) and an if/elif chain in `handle_command` (Client) — see the README's Communication Protocol and Script Execution Model sections for the full type list.

**The Engine owns all persistence.** SQLite by default, bundled into the Engine package. Neither Client nor Admin has a database — they keep small config/state files instead (the Client's under `%ProgramData%` with restrictive ACLs, since it holds the derived auth key and the tamper-protected lockout schedule). All SQL lives in `engine/database.py` behind functions like `store_app_data`/`get_network_summary`, so the documented Postgres migration path stays a change to that one module.

## Rules that are easy to violate

**asyncio vs. threads.** Anything that can signal readiness (socket I/O, subprocess spawn/wait) goes on the event loop — never a thread. Threads or `asyncio.to_thread` are reserved for synchronous calls that can't signal readiness and would stall the loop. The concrete case: `psutil.process_iter()` must be called as `await asyncio.to_thread(collect_process_data)`, never inline in an async function, or heartbeats get delayed.

**Script execution never blocks on completion.** Admin-defined scripts (Python or PowerShell only) may run indefinitely. The client writes stdout/stderr to `logs/{command_id}.log`, sends `COMMAND_ACCEPTED` immediately, then a background task polls the log on a fixed interval and only reads when the file *size has grown*. On exit it sends one `COMMAND_COMPLETE` and deletes the log and temp script file — that log is scratch space, not a durable record. Termination is keyed by `command_id` (`TERMINATE_SCRIPT`), not process name; `TERMINATE_PROCESS` by name is a separate, unrelated command for app control.

**Never invoke a system Python.** Both the Admin GUI and the Client Agent bundle their own pinned embeddable Python (`BUNDLED_PYTHON_PATH`). The Admin validates scripts with `py_compile` before sending; the Client re-validates on arrival before executing. Both bundles must be the same pinned version or "validated" scripts can still fail at runtime.

**Authentication is built last but is not optional.** Per-client keys are derived as `HMAC(master_secret, client_id)`; the handshake is nonce/challenge based. The build order defers real crypto until after all three components are integrated — but the *message shape* is scaffolded from the start, so `REGISTER` carries nonce/response fields with a stubbed always-accept check. Do not change the protocol later to add auth; fill in the existing stub.

`DEV_BYPASS_AUTH` must skip the handshake **entirely** with an early return before any nonce is sent — deliberately not a validation step that quietly passes, so a forgotten flag is visible in a packet capture. Defaults to off, logs loudly when on.

**Two module globals need resetting between tests, and `tests/conftest.py` does it autouse.** `engine.database` holds its path and connection globally — without isolation, any test touching the Engine writes to the real `monitoring.db` in the repo root. `engine.main._shutdown` is an `asyncio.Event` created lazily per loop; `Event.wait()` binds to the first loop that awaits it and raises `RuntimeError` from any other, and a leaked `set()` makes every later connection handler exit instantly. Both failure modes are silent and cascade, so don't remove those fixtures.

**The Admin GUI is single-threaded via qasync.** asyncio runs on top of Qt's event loop, so the GUI, the Engine socket and every background task share one thread — no cross-thread marshalling anywhere. QML calls synchronous slots; anything needing I/O schedules a task with `asyncio.ensure_future` and returns immediately. Don't introduce a socket thread: it would contradict the README's rule that threads are only for work that cannot signal readiness.

**Admins heartbeat like clients.** Nothing else makes an Admin GUI send traffic, and the Engine reaps any peer silent past `HEARTBEAT_TIMEOUT` regardless of role. Removing that heartbeat task disconnects idle operators after 60 seconds.

**Database conventions.** Timestamps are ISO-8601 UTC strings (fixed width, so `WHERE timestamp >= ?` compares chronologically). Network counters arrive cumulative since client boot, so summaries sum positive deltas and skip negatives — a negative delta is a reboot, not negative usage. Every dispatch gets its own `command_id` even in a broadcast. Writes are synchronous on the event loop by measurement, not by oversight; re-run `scripts/bench_database.py` before changing that.

**Access-control asymmetry is intentional.** Application management is *blacklist-only* (whitelisting can't reliably enumerate OS/helper processes, so unlisted apps are allowed by design). Website filtering supports *both* modes via a required `mode` field, with blacklist as the default and whitelist reserved for locked-down sessions like exams. Don't "fix" this into symmetry.

**Lockout enforcement fails closed.** The schedule under `%ProgramData%` is HMAC-protected; if validation fails, treat the block as still active. Blocks are capped at 2 hours as a safety timeout against the overlay's own hangs (not against network loss — enforcement is local and doesn't need the Engine). Two independent watchdogs exist because the overlay *and* the agent can each hang: the agent polls every 30s, and an installer-registered Windows Scheduled Task checks every ~5 min. On boot the agent re-reads the schedule before anything else and re-launches the overlay if a block is still active.

## Build order

Scaffold everything first (module structure, signatures, empty handlers wired into dispatch) so messages flow end-to-end before real logic exists. Then implement fully, one component at a time, testing each before starting the next: **Engine → Admin → Client**, with full integration testing last. The Engine is finished first specifically so the other two are built against real behavior rather than assumptions.

## Code style

- Python 3.10+, PEP 8, type hints everywhere, docstrings on all functions, 100-char lines.
- **Prefer functions over classes** — use classes only when genuinely necessary. Module-level dicts hold shared state (`connections`, `client_info`, `running_scripts`); prefer immutable data and pure functions elsewhere.
- Catch specific exception types, log with context, degrade gracefully, and never surface internal errors outward — return `{"status": "error", "message": ...}` shaped results.
