# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Two root-level docs track the work: **`todo.md`** is the phase-by-phase plan, and **`issues.md`** logs known bugs, deferred decisions and unverified claims. Read both before starting a phase — `issues.md` marks which items block which phase.

**`issues.md` section D is "accepted limitations"** — things deliberately not built, each with what would change the decision. Check it before "fixing" something that looks missing: storage staying relational, no per-client partitioning, no client→Engine→same-client flow, the Engine staying stateless per message, telemetry fanning out to every admin, hosts-file whitelist approximation, one-off rather than recurring lockout schedules, and one machine being unable to simulate many *enforcing* clients are all decisions, not gaps.

Phases 0–4 are complete: Engine, Administrator and Client Agent are all implemented and tested (263 tests). **Phase 5, manual per-system verification, is next.** Packaging was moved out of Phase 4 to Phase 8 (dead last) — packaging code that has never been proven on its target machine is the wrong order of work, and no design decisions remain in it. Three code paths fall back to the running interpreter meanwhile and log a warning; those fallbacks are for bringing a machine up, not for shipping, so Phase 5's results do not fully transfer to the packaged build.

`issues.md` section A lists decisions only the user can make (retention period, institutional approval, TLS scope). Don't try to resolve those in code.

`README.md` is the design specification, including reference implementations as fenced code blocks. Where the working code and the README disagree, the code is newer — the deviations and their reasons are recorded in `todo.md`.

## Commands

Run everything through the venv. The project is installed editable, which is what makes `from common.protocol import ...` resolve from every entry point.

Requirements are split per deployable unit — the Engine is standard-library only, so a Linux install pulls nothing. A dev box runs the whole suite and needs all three files:

```powershell
pip install -r requirements.txt -r requirements-admin.txt -r requirements-client.txt
```

```powershell
.\.venv\Scripts\python.exe -m pytest -q                    # 263 tests
.\.venv\Scripts\python.exe -m pytest -q --cov=engine --cov=common --cov=admin
.\.venv\Scripts\python.exe -m scripts.bench_database       # SQLite write cost
```

**Each unit has its own CLI: `python -m engine`, `python -m client`, `python -m admin`.** `labmonitor.py` dispatches to all three plus the helpers on a dev box. Every flag maps onto an existing env var — the flag exists because config is read at import time, so `<package>/cli.py` writes to `os.environ` *before* importing the component. That is also why the three `main.py` files were left untouched and still work env-only via `python -m <package>.main`. Don't move argparse into them.

Diagnostics that need nothing else running — reach for these before debugging an integration:

```powershell
.\.venv\Scripts\python.exe -m admin  --check-qml   # loads every QML file offscreen
.\.venv\Scripts\python.exe -m client --once        # one real collection cycle, printed
.\.venv\Scripts\python.exe -m client --check       # config, state, missing bundles
```

Both client helper windows are QML (`client/ui/`), matching the Administrator — don't reintroduce a second toolkit. `LABMONITOR_UI_HEADLESS=1` loads and validates their QML without showing anything, which is how to check a change without taking over the screen.

**The Engine runs under WSL**, not Windows — it is Linux-only by design (asyncio/epoll). It imports only the standard library, so WSL needs no venv, and `engine/cli.py` is stdlib-only to keep that true:

```bash
wsl -- bash -lc "cd /mnt/c/.../SystemMonitoring && python3 -m engine --check"
wsl -- bash -lc "cd /mnt/c/.../SystemMonitoring && python3 -m engine"
```

WSL2 localhost forwarding means the Windows client reaches it at `127.0.0.1:5000` unchanged. `ENGINE_LOG_LEVEL=DEBUG` surfaces heartbeats; `DEV_BYPASS_AUTH=1` skips the handshake.

Tests use `pytest-asyncio` in strict mode — async tests need an explicit `@pytest.mark.asyncio`.

## Architecture

Three deployable packages, each on a different machine:

- **Engine** (`engine/`) — Linux only, Python + `asyncio`. Central hub: accepts client TCP connections, routes commands between admin and clients, stores monitoring data. Deliberately Linux-only because asyncio there is backed by `epoll`. Listens on port 5000.
- **Client Agent** (`client/`) — Windows only, headless. Persistent connection to the Engine, collects metrics via `psutil`, executes admin commands. Spawns two bundled helper executables **on demand, not persistently**: a dialog exe (shutdown/grace warnings) and an overlay exe (time-based lockout).
- **Administrator Client** (`admin/`) — Windows, Qt 6 + QML over a Python backend.

Wire protocol is newline-delimited JSON over TCP, UTF-8. Every message has `type`, `client_id`, `timestamp`, `payload`, and an optional `trace_id`. On the Engine, message types are dispatched through the `_ROUTES` table in `engine/command_handler.py`; the Client uses an if/elif chain in `handle_command` — see the README's Communication Protocol and Script Execution Model sections for the full type list.

**The Engine owns all persistence.** SQLite by default, bundled into the Engine package. Neither Client nor Admin has a database — they keep small config/state files instead (the Client's under `%ProgramData%` with restrictive ACLs, since it holds the derived auth key and the tamper-protected lockout schedule). All SQL lives in `engine/database.py` behind functions like `store_app_data`/`get_network_summary`, so the documented Postgres migration path stays a change to that one module.

## Rules that are easy to violate

**asyncio vs. threads.** Anything that can signal readiness (socket I/O, subprocess spawn/wait) goes on the event loop — never a thread. Threads or `asyncio.to_thread` are reserved for synchronous calls that can't signal readiness and would stall the loop. The concrete case: `psutil.process_iter()` must be called as `await asyncio.to_thread(collect_process_data)`, never inline in an async function, or heartbeats get delayed.

**Every inbound message declares its flow; nothing is routed by hand.** `engine/routing.py` is the mechanism (role check → persist → handler → relay, all narrated under one `trace_id`), and `_ROUTES` in `engine/command_handler.py` is the declaration. Add a message type by adding a row, not by writing a handler that stores and fans out on its own — the point is that the table answers "where does this go?" without reading any handler body, and that one code path logs every hop. A type absent from the table is refused with a logged reason. Roles live in the table too (`senders`), so a client cannot reach an admin-only flow and an admin cannot fabricate telemetry. Deliberately not a pipeline framework: three fixed steps, no middleware, no composition.

**Relays are checked, not fired and forgotten.** `routing.relay` counts failures and logs them against the trace id. An admin whose socket died used to stop receiving telemetry with nothing anywhere saying so. Never go back to ignoring a send's return value.

**Commands for an offline client are queued only if replaying them is still correct.** `DURABLE_COMMANDS` (the `SET_*` policy commands) declare state to converge to, so they queue in `command_log` with status `queued` and flush on the client's next registration; a newer one of the same type supersedes the older. Everything else — captures, dialogs, kills, scripts, pauses — is a point-in-time action and stays `undeliverable`. There is no separate outbox table, so the queue and the audit trail cannot disagree. `SET_PAUSE` is excluded on purpose: the client already persists pause state across reboots, so replaying it would re-freeze a machine whose pause had legitimately lapsed.

**Script execution never blocks on completion.** Admin-defined scripts (Python or PowerShell only) may run indefinitely. The client writes stdout/stderr to `logs/{command_id}.log`, sends `COMMAND_ACCEPTED` immediately, then a background task polls the log on a fixed interval and only reads when the file *size has grown*. On exit it sends one `COMMAND_COMPLETE` and deletes the log and temp script file — that log is scratch space, not a durable record. Termination is keyed by `command_id` (`TERMINATE_SCRIPT`), not process name; `TERMINATE_PROCESS` by name is a separate, unrelated command for app control.

**Never invoke a system Python.** Both the Admin GUI and the Client Agent bundle their own pinned embeddable Python (`BUNDLED_PYTHON_PATH`). The Admin validates scripts with `py_compile` before sending; the Client re-validates on arrival before executing. Both bundles must be the same pinned version or "validated" scripts can still fail at runtime.

**TLS is presence-based and pinned.** Once `certs/engine-cert.pem` exists, the Engine and both clients enable TLS automatically — there is no flag to forget, and `ENGINE_TLS=0` is the deliberate escape hatch. Clients pin the Engine's self-signed certificate and pass `server_hostname=TLS_IDENTITY` (a fixed name) rather than the IP, so hostname verification stays on even when the Engine's address changes. Never disable `check_hostname` or `verify_mode` to "make it work" — that silently reduces TLS to obfuscation. Tests run against real handshakes and assert the refusals; `tests/conftest.py` forces plaintext for the protocol tests, since they stand up their own plaintext servers.

**Authentication is built last but is not optional.** Per-client keys are derived as `HMAC(master_secret, client_id)`; the handshake is nonce/challenge based. The build order defers real crypto until after all three components are integrated — but the *message shape* is scaffolded from the start, so `REGISTER` carries nonce/response fields with a stubbed always-accept check. Do not change the protocol later to add auth; fill in the existing stub.

`DEV_BYPASS_AUTH` must skip the handshake **entirely** with an early return before any nonce is sent — deliberately not a validation step that quietly passes, so a forgotten flag is visible in a packet capture. Defaults to off, logs loudly when on.

**Two module globals need resetting between tests, and `tests/conftest.py` does it autouse.** `engine.database` holds its path and connection globally — without isolation, any test touching the Engine writes to the real `monitoring.db` in the repo root. `engine.main._shutdown` is an `asyncio.Event` created lazily per loop; `Event.wait()` binds to the first loop that awaits it and raises `RuntimeError` from any other, and a leaked `set()` makes every later connection handler exit instantly. Both failure modes are silent and cascade, so don't remove those fixtures.

**The Admin GUI is single-threaded via qasync.** asyncio runs on top of Qt's event loop, so the GUI, the Engine socket and every background task share one thread — no cross-thread marshalling anywhere. QML calls synchronous slots; anything needing I/O schedules a task with `asyncio.ensure_future` and returns immediately. Don't introduce a socket thread: it would contradict the README's rule that threads are only for work that cannot signal readiness.

**Admins heartbeat like clients.** Nothing else makes an Admin GUI send traffic, and the Engine reaps any peer silent past `HEARTBEAT_TIMEOUT` regardless of role. Removing that heartbeat task disconnects idle operators after 60 seconds.

**Database conventions.** Timestamps are ISO-8601 UTC strings (fixed width, so `WHERE timestamp >= ?` compares chronologically). Network counters arrive cumulative since client boot, so summaries sum positive deltas and skip negatives — a negative delta is a reboot, not negative usage. Every dispatch gets its own `command_id` even in a broadcast. Writes are synchronous on the event loop by measurement, not by oversight; re-run `scripts/bench_database.py` before changing that.

**Access-control asymmetry is intentional.** Application management is *blacklist-only* (whitelisting can't reliably enumerate OS/helper processes, so unlisted apps are allowed by design). Website filtering supports *both* modes via a required `mode` field, with blacklist as the default and whitelist reserved for locked-down sessions like exams. Don't "fix" this into symmetry.

**Don't launch the overlay or dialog casually.** `client/overlay_app.py` takes over the full screen, disables Task Manager, and re-asserts topmost every 500ms. It always restores the Task Manager policy on exit — including on a crash — and closes itself at its `--until` time, but running it uninvited on someone's working machine is disruptive. Ask first.

**Two different ways a screen gets held, and they are not interchangeable.** A *scheduled restriction* has a known end and shows the student a countdown; a *pause* is the admin holding the screen live, with no stated end and deliberately no countdown. Both are capped, but for different reasons — the schedule's 2-hour cap guards against the overlay hanging, the pause's 1-hour cap guards against the *admin* vanishing. Never show the pause's internal expiry on the client: that turns an admin safety net into a promise to the user. A pause takes precedence over a schedule, and dropping it reverts to the countdown rather than releasing a still-blocked machine.

**Scripts are stdlib-only, and imports are read with `ast` — never a regex.** A pattern match can't tell `import os` from the same words in a docstring, mishandles `import os, sys` and multi-line `from` imports, and misses imports deferred inside functions. Two separate Windows checks matter: a denylist of POSIX-only stdlib modules (`fcntl`, `pwd`, …) exists to give a *useful* message, while `find_spec` inside the bundled interpreter is authoritative. `find_spec` resolves without importing — never validate by importing, that executes module-level code.

**Scripts are capped at 5 minutes (15 max).** They're an extension mechanism for small routine tasks, not a job runner. This does *not* remove the need for the non-blocking execution model — a 5-minute script stalls the agent just as surely as an infinite one. On Windows a killed script gets no cleanup, so scripts must be safely interruptible.

**Client state is per-client, and out-of-process readers must be told which client.** `STATE_DIR` is `STATE_ROOT / state_component(CLIENT_ID)`, not a bare `%ProgramData%\SystemMonitoring` — otherwise several agents on one box share one lockout schedule and overwrite each other. `CLIENT_ID` arrives from the environment, so it is sanitised to one path component *and* suffixed with a hash of the original: sanitising alone is lossy, and `lab1/pc-01` colliding with `lab1_pc-01` would silently reunite two machines' state. The consequence that bites: a Windows service and a Scheduled Task inherit nothing from the installer's environment, so `install_service.py` bakes `--id` into **both** command lines and `client/watchdog.py` applies it before importing `client.config`. Leave that out and the watchdog resolves a different directory, finds no schedule, and releases a blocked machine — a fail-open in the component whose job is to fail closed.

**Lockout enforcement fails closed.** The schedule under `%ProgramData%` is HMAC-protected; if validation fails, treat the block as still active. Blocks are capped at 2 hours as a safety timeout against the overlay's own hangs (not against network loss — enforcement is local and doesn't need the Engine). Two independent watchdogs exist because the overlay *and* the agent can each hang: the agent polls every 30s, and an installer-registered Windows Scheduled Task checks every ~5 min. On boot the agent re-reads the schedule before anything else and re-launches the overlay if a block is still active.

## Build order

Scaffold everything first (module structure, signatures, empty handlers wired into dispatch) so messages flow end-to-end before real logic exists. Then implement fully, one component at a time, testing each before starting the next: **Engine → Admin → Client**, with full integration testing last. The Engine is finished first specifically so the other two are built against real behavior rather than assumptions.

## Code style

- Python 3.10+, PEP 8, type hints everywhere, docstrings on all functions, 100-char lines.
- **Prefer functions over classes** — use classes only when genuinely necessary. Module-level dicts hold shared state (`connections`, `client_info`, `running_scripts`); prefer immutable data and pure functions elsewhere.
- Catch specific exception types, log with context, degrade gracefully, and never surface internal errors outward — return `{"status": "error", "message": ...}` shaped results.
