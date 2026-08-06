# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**No code exists yet.** The repository contains only `README.md` — a complete design specification for a final-year project (system monitoring/management tool for a computer lab). The README includes full reference implementations of `engine/main.py`, `client/main.py`, and `engine/database.py` as fenced code blocks; treat those as the intended starting point when scaffolding, not as existing files.

When implementing, follow the directory layout in the README's "Project Structure" section (`engine/`, `client/`, `admin_gui/`, `common/`, `tests/`).

## Commands

These come from the README's Deployment section and describe the intended layout; nothing is runnable yet.

```bash
pip install -r requirements.txt
python engine/setup_db.py          # initialize SQLite schema
python engine/main.py              # Engine — Linux only
```

```powershell
python client\main.py                             # Client Agent, manual/testing run
python client\install_service.py --startup=auto   # install as Windows service
python admin_gui\main.py                          # Administrator GUI
```

Tests use `pytest` with `pytest-asyncio` (`@pytest.mark.asyncio` for async tests). Target >70% coverage.

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

**Access-control asymmetry is intentional.** Application management is *blacklist-only* (whitelisting can't reliably enumerate OS/helper processes, so unlisted apps are allowed by design). Website filtering supports *both* modes via a required `mode` field, with blacklist as the default and whitelist reserved for locked-down sessions like exams. Don't "fix" this into symmetry.

**Lockout enforcement fails closed.** The schedule under `%ProgramData%` is HMAC-protected; if validation fails, treat the block as still active. Blocks are capped at 2 hours as a safety timeout against the overlay's own hangs (not against network loss — enforcement is local and doesn't need the Engine). Two independent watchdogs exist because the overlay *and* the agent can each hang: the agent polls every 30s, and an installer-registered Windows Scheduled Task checks every ~5 min. On boot the agent re-reads the schedule before anything else and re-launches the overlay if a block is still active.

## Build order

Scaffold everything first (module structure, signatures, empty handlers wired into dispatch) so messages flow end-to-end before real logic exists. Then implement fully, one component at a time, testing each before starting the next: **Engine → Admin → Client**, with full integration testing last. The Engine is finished first specifically so the other two are built against real behavior rather than assumptions.

## Code style

- Python 3.10+, PEP 8, type hints everywhere, docstrings on all functions, 100-char lines.
- **Prefer functions over classes** — use classes only when genuinely necessary. Module-level dicts hold shared state (`connections`, `client_info`, `running_scripts`); prefer immutable data and pure functions elsewhere.
- Catch specific exception types, log with context, degrade gracefully, and never surface internal errors outward — return `{"status": "error", "message": ...}` shaped results.
