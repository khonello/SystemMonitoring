# Implementation Tracker

Ordering follows README → "Development Guidelines → Implementation Approach"
and "Component build order". Where this conflicts with the 4-week calendar in
"Implementation Timeline", this ordering wins.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 0 — Repo Bootstrap ✅

- [x] `git init` + `.gitignore` (venv, `__pycache__`, `*.db`, `logs/`, bundled
      runtimes, auth material). No commit made yet.
- [x] Create package tree per README "Project Structure":
      `engine/`, `client/monitors/`, `admin_gui/qml/`, `common/`, `tests/`, `docs/`
- [x] `__init__.py` in every Python package
- [x] `requirements.txt` — `psutil==7.2.2`, `PySide6==6.11.1`, `pytest==9.1.1`,
      `pytest-asyncio==1.4.0`; `requirements-client.txt` — `pywin32==312`
      (Windows-only, not needed until Phase 4)
- [x] `pyproject.toml` + `pip install -e .` — **pulled forward from Phase 1.**
      Without it `from common.protocol import ...` fails, because running
      `python engine/main.py` puts `engine/` on `sys.path`, not the repo root.
      Also carries the pytest config (`asyncio_mode = "strict"`).
- [x] Virtualenv (`.venv`, Python 3.10.0) + install, all imports resolve

**Environment note:** development happens on Windows, but the Engine is
Linux-only by design (asyncio/epoll). The Engine runs under **WSL**
(Python 3.12.3) while the Client Agent and Admin GUI run on Windows
(Python 3.10.0). WSL2 localhost forwarding means the Windows client reaches
the WSL Engine at `127.0.0.1:5000` with no extra configuration — verified in
Phase 1. The Engine imports only the standard library, so it needs no venv or
pip install inside WSL; run it with `python3 -m engine.main`.

## Phase 1 — Scaffold Pass (all components, stub behavior) ✅

Goal: a message can travel Admin → Engine → Client and back with every handler
present but empty. No real logic in this phase.

### common/
- [x] `constants.py` — message types, ports, intervals, roles, `STREAM_LIMIT`
- [x] `protocol.py` — `create_message`, newline-delimited JSON encode/decode,
      envelope validation
- [x] `utils.py` — timestamp, command-id and client-id helpers

### engine/
- [x] `config.py` — host, port, DB path, `MAX_CLIENTS`, `HEARTBEAT_TIMEOUT`,
      `LOG_LEVEL`, `DEV_BYPASS_AUTH` (**default False, env-only**)
- [x] `main.py` — `asyncio.start_server`, `handle_client`, registration
      handshake, stale-peer reaper, signal handling
- [x] **`REGISTER` flow carries nonce/response fields from the start**, with
      `verify_challenge_response` stubbed to accept, and `DEV_BYPASS_AUTH`
      skipping the handshake outright before any nonce is sent
- [x] Startup banner logging loudly when the bypass is active
- [x] `connection_manager.py` (real registry), `command_handler.py` (dispatch
      table + routing), `protocol.py` (stream framing)
- [x] `auth.py` — **not in the README's file tree.** Added so Phase 6 is a swap
      of two function bodies rather than edits threaded through `main.py`.
- [x] `database.py` — `get_connection`, `init_database` with the real 5-table
      schema and indexes; all store/get functions present but stubbed
- [x] `setup_db.py` — `python -m engine.setup_db [path]`

### client/
- [x] `config.py` — engine address, `CLIENT_ID`, intervals,
      `BUNDLED_PYTHON_PATH`, `STATE_DIR`, `SCRIPT_LOG_DIR`
- [x] `connection.py` — connect, register (both handshake shapes), send/receive,
      exponential reconnect backoff
- [x] `auth.py` — **not in the README's file tree**, mirrors `engine/auth.py`
- [x] `main.py` — four concurrent loops (command listener, monitoring, network,
      heartbeat) with reconnect; `asyncio.wait(FIRST_COMPLETED)` rather than
      `gather`, so one dead loop tears the session down instead of hanging
- [x] `monitors/` — three stub collectors, synchronous by design
- [x] `executor.py` — dispatch with every command type, all "not implemented";
      `execute_script` already shaped to *not* await completion
- [ ] Windows service wrapper — deferred to Phase 4 packaging, not scaffolded

### admin_gui/
- [x] `main.py`, `backend.py` (signals/slots, no transport), `models.py`
      (`ClientListModel`)
- [x] `qml/main.qml`, `ClientList.qml`, `MonitoringPanel.qml`, `CommandPanel.qml`
      — window opens and lays out, controls call slots that only log
- [ ] asyncio ↔ Qt event-loop integration — **deliberately not decided**, it is
      a Phase 3 call that shapes `backend.py`

### tests/
- [x] `test_protocol.py` — 24 tests, real coverage of the one module with logic
- [x] `test_engine.py` — connection-registry tests (had real logic); the rest
      listed as Phase 2 work
- [x] `test_client.py` — backoff plus stub-contract tests; rest listed as Phase 4
- [x] `test_integration.py` — **deviation from plan (was to be empty).** The
      exit criteria *are* an end-to-end round trip, so they are encoded as
      tests rather than checked once by hand and lost.
- [x] ~~`pytest.ini` / `pyproject.toml` with asyncio mode configured~~ — Phase 0

### Exit criteria — all met
- [x] **47 tests passing** (`python -m pytest`)
- [x] Engine starts under WSL, creates the SQLite schema, logs its auth posture
- [x] Windows client connects to the WSL Engine, completes the nonce handshake,
      and registers
- [x] Heartbeats arrive every 15s and are logged (at DEBUG); APP_DATA and
      NETWORK_DATA arrive on their own intervals
- [x] Admin → Engine → Client → Engine → Admin round trip returns
      `"Not implemented (Phase 1 scaffold)"`
- [x] Role enforcement holds: a Client Agent sending `ADMIN_COMMAND` is refused

---

## Phase 2 — Engine (full implementation) ✅

- [x] Connection registry + heartbeat-timeout reaping of dead clients
- [x] `database.py` real implementations: `store_client`,
      `update_client_last_seen`, `mark_client_offline`, `store_app_data`,
      `store_network_data`, `store_usb_event`, `get_client_apps`,
      `get_network_summary`, `get_usb_events`, `get_all_clients`
- [x] All SQL confined to `database.py` (keeps the documented Postgres path open)
- [x] Command routing admin → specific client, and `broadcast_command`
- [x] `command_log` persistence + status updates, including an `undeliverable`
      row when the target client is not connected
- [x] Script lifecycle relay: `COMMAND_ACCEPTED` / `COMMAND_OUTPUT` /
      `COMMAND_COMPLETE` forwarded to admins
- [x] Data aggregation: `get_network_summary` (24h), `get_weekly_network_summary`
      (per-day), `get_app_usage_summary`
- [x] **Measured** the `run_in_executor` question — see below
- [x] Unit + integration tests: **96 passing, 87% coverage** on engine+common
      (target was >70%)

**Decisions made during Phase 2, worth remembering:**

- **Writes stay synchronous on the event loop.** `scripts/bench_database.py`
  measures 5–8ms per write, ~35ms blocked per second across 50 clients — a
  3.5% duty cycle. Re-run that benchmark before revisiting; the fix if it ever
  changes is `asyncio.to_thread` at the call sites in `command_handler.py`,
  not a change to `database.py`.
- **One long-lived connection, not one per call.** Opening and closing per call
  cost ~11–15ms; reusing it roughly halved that. `PRAGMA synchronous = NORMAL`
  trades an fsync per commit for possibly losing the newest samples on power
  loss — right for telemetry, and it cannot corrupt the database.
- **Network counters are differenced at query time.** Clients send cumulative
  since-boot counters, so summaries sum positive deltas and skip negatives,
  which are reboots rather than negative usage.
- **Each dispatch gets its own `command_id`**, even in a broadcast. A shared id
  would duplicate audit rows, make one status update hit all of them, and leave
  `TERMINATE_SCRIPT` unable to name a single execution.
- **Timestamps are ISO-8601 UTC strings.** Fixed width, so lexicographic
  comparison is chronological and `WHERE timestamp >= ?` works directly.

**Follow-up items, all since resolved — see [issues.md](issues.md) section B:**

- [x] Retention scheduled, batched and off the event loop (B3)
- [x] `get_app_usage_summary` — index measured, reverted, retention is the fix (B4)
- [x] Idle admin connections no longer dropped (B1)
- [x] Client and admin capacity capped separately (B2)

- [x] **Gate: Engine fully tested standalone before Admin work begins**

---

## Phase 3 — Admin GUI (full implementation) ✅

- [x] PySide6 + QML app shell
- [x] **asyncio ↔ Qt integration: qasync** (issues.md B5). Chosen because the
      README's concurrency rule says threads are only for work that cannot
      signal readiness — sockets can, so a socket thread would have
      contradicted the model used everywhere else. GUI, socket and background
      tasks all share one thread.
- [x] **Idle-admin disconnection fixed** (issues.md B1) — the Admin GUI
      heartbeats on the same 15s interval a Client Agent uses
- [x] `connection.py` — admin session as a class, not module state, so tests
      can stand up more than one at a time
- [x] Live client list, including clients that are known but currently offline
- [x] Monitoring dashboard: applications, network samples, USB events, buffered
      **per client** so switching selection loses nothing
- [x] Command panel: script send, screen capture, terminate process/script,
      with script output streamed in as it arrives
- [x] Reports viewer — 24h network, per-day weekly, app usage, USB events,
      command history. Admins never touch the database; every query goes
      through the Engine via `REPORT_REQUEST`.
- [x] Policy editor: website blacklist/whitelist **with `mode` always explicit**
      and the whitelist tradeoff spelled out in the UI; app blacklist
      (blacklist-only by design)
- [x] Script pre-send validation (`py_compile` in a subprocess, so the check
      runs under the interpreter version the client will use)
- [x] Local prefs in QSettings — remembers the address that actually connected,
      not the one prefilled at startup
- [x] Tests: **126 passing**, 30 of them new for the Admin GUI
- [x] Verified end-to-end against a live Engine under WSL with a real client:
      roster, live telemetry relay, validation rejection, command round trip,
      all five reports, and policy dispatch reaching the audit trail
- [ ] Time-schedule editor — deferred to Phase 4, where the lockout overlay
      that enforces it is built. Editing schedules with nothing to enforce them
      would be UI without behaviour.
- [x] **Gate: Admin tested against the completed Engine before Client work begins**

**Engine changes this phase required:**

- `APP_DATA` / `NETWORK_DATA` / `USB_EVENT` are now relayed to admins for the
  live dashboard (scale caveat in issues.md C5)
- New `REPORT_REQUEST` / `REPORT` message pair, with five report kinds
- `CLIENT_LIST` merges the live registry with the database, so a client that
  disconnects does not vanish from the operator's list

---

## Phase 4 — Client Agent (full implementation)

### Monitoring
- [ ] Process monitor — `psutil.process_iter` **via `asyncio.to_thread`**, never inline
- [ ] Network monitor — `net_io_counters` deltas
- [ ] USB monitor — event-driven, log-only, no blocking
- [ ] Idle time — Windows `GetLastInputInfo` via ctypes

### Commands
- [ ] `execute_script` — detached launch, per-`command_id` log file, immediate
      `COMMAND_ACCEPTED`, no waiting on completion
- [ ] `tail_log_and_report` — poll on interval, read only when file size grew,
      one `COMMAND_COMPLETE` on exit, then delete log + temp script
- [ ] `terminate_script` keyed by `command_id`; `terminate_process` by name
- [ ] On-arrival script re-validation with the bundled interpreter
- [ ] Screen capture with compression

### Access control
- [ ] Website filtering, both modes, hosts-file or proxy based
- [ ] App blacklist enforcement via existing `TERMINATE_PROCESS`
- [ ] Dialog exe (shutdown / grace warnings) — spawned on demand, choice
      reported back via exit code or stdout
- [ ] Overlay exe — fullscreen single-monitor lockout, topmost re-assert ~500ms,
      Task Manager policy toggle
- [ ] `%ProgramData%` state store, ACL-restricted, HMAC-protected, **fails closed**
- [ ] 2-hour continuous-block cap
- [ ] Watchdogs: agent polls every 30s **and** an installer-registered Windows
      Scheduled Task checks every ~5min (covers the agent itself hanging)
- [ ] Reboot handling: re-read schedule on startup before anything else,
      relaunch overlay if a block is still active

### Packaging
- [ ] Bundle pinned embeddable Python — **same pinned version as the Admin bundle**
- [ ] `install_service.py` (pywin32 or NSSM), auto-start, registers the
      watchdog Scheduled Task in the same installer step
- [ ] Tests

---

## Phase 5 — Full Integration

- [ ] All three components running together
- [ ] Multi-client scenarios (target 10+, design ceiling 50)
- [ ] Network failure / reconnect behavior
- [ ] Performance + load testing
- [ ] **Re-measure client RAM footprint** — README flags the <50MB figure as
      predating the bundled runtime and helper exes, and explicitly unverified

---

## Phase 6 — Authentication (last, but a hard prerequisite for real deployment)

- [ ] Master secret generation + admin-side storage
- [ ] Per-client derived keys: `HMAC(master_secret, client_id)`
- [ ] Provisioning: bake the derived key into each client install package
- [ ] Replace the Phase 1 stub with real nonce/challenge verification
- [ ] `DEV_BYPASS_AUTH` confirmed defaulting off, requiring deliberate per-run activation
- [ ] **Budget real time here**: dev-mode skipped the handshake entirely, so this
      is the first test of its *mechanics* (ordering, round-trips, blocking), not
      just its crypto — README "Dev-Mode Auth Bypass", known tradeoff
- [ ] Rate limiting, admin action audit logging

---

## Deferred / Out of scope

TLS (transport is plaintext JSON even after auth — sniffable on the LAN),
Postgres migration, and everything under README "Removed Features".
