# Implementation Tracker

Ordering follows README → "Development Guidelines → Implementation Approach"
and "Component build order". Where this conflicts with the 4-week calendar in
"Implementation Timeline", this ordering wins.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

| Phase | Status |
|-------|--------|
| 0 — Repo bootstrap | ✅ done |
| 1 — Scaffold pass (all components) | ✅ done |
| 2 — Engine | ✅ done |
| 3 — Admin GUI | ✅ done |
| 4 — Client Agent | ✅ done (packaging moved to Phase 8) |
| 5 — Manual per-system verification | **next** |
| 6 — Full integration | not started |
| 7 — Authentication | not started |
| 8 — Packaging | not started |

**289 tests passing.** Open problems and decisions live in
[issues.md](issues.md); section A there needs your input.

**Packaging moved from Phase 4 to Phase 8** — packaging code that has never been
proven on its target machine is the wrong order of work. It is pure build work
with no design risk left in it (the runtime question was settled in
[issues.md](issues.md) B11), so it gains least from being early and blocks
nothing. The cost of deferring it is stated in Phase 5 below.

---

## Phase 0 — Repo Bootstrap ✅

- [x] `git init` + `.gitignore` (venv, `__pycache__`, `*.db`, `logs/`, bundled
      runtimes, auth material). No commit made yet.
- [x] Create package tree per README "Project Structure":
      `engine/`, `client/monitors/`, `admin/qml/`, `common/`, `tests/`, `docs/`
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

### admin/
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
- [x] Script pre-send validation — syntax (`py_compile` in a subprocess, under
      the interpreter version the client will use), **plus a stdlib-only import
      policy read with `ast`** and a Windows-availability check resolved inside
      the bundled runtime. Surfaced on a Check button as well as on send, and
      lists accepted imports, not just rejected ones.
- [x] Local prefs in QSettings — remembers the address that actually connected,
      not the one prefilled at startup
- [x] Tests: **126 passing**, 30 of them new for the Admin GUI
- [x] Verified end-to-end against a live Engine under WSL with a real client:
      roster, live telemetry relay, validation rejection, command round trip,
      all five reports, and policy dispatch reaching the audit trail
- [x] Time-schedule editor — deferred to Phase 4, where the lockout overlay
      that enforces it is built. Phase 4 built the enforcement and did not come
      back for the editor; **now done** (issues.md B16). One-off windows with a
      start delay, matching what the client can actually store, with the 2-hour
      cap warned about rather than duplicated.
- [x] **Gate: Admin tested against the completed Engine before Client work begins**

**Engine changes this phase required:**

- `APP_DATA` / `NETWORK_DATA` / `USB_EVENT` are now relayed to admins for the
  live dashboard (scale caveat in issues.md C5)
- New `REPORT_REQUEST` / `REPORT` message pair, with five report kinds
- `CLIENT_LIST` merges the live registry with the database, so a client that
  disconnects does not vanish from the operator's list

---

## Phase 4 — Client Agent (full implementation) ✅ except packaging

### Monitoring
- [x] Process monitor — `psutil.process_iter` **via `asyncio.to_thread`**,
      plus window titles from `EnumWindows` through ctypes, since psutil has no
      notion of windows. CPU counters are primed at startup so the first batch
      is not all zeroes.
- [x] Network monitor — cumulative counters sent as-is, differenced by the
      Engine; connection count degrades to 0 rather than failing when it needs
      elevation
- [x] USB monitor — polls removable drives rather than subscribing to
      `WM_DEVICECHANGE`. A message-only window would be more immediate but
      needs a second event loop running alongside asyncio, for events that
      happen a few times a day. First poll establishes a baseline so drives
      already mounted at startup are not reported as insertions.
- [x] Idle time — `GetLastInputInfo`, with the tick-count wrap handled
- [x] Screen-lock detection via `OpenInputDesktop`

### Commands
- [x] `execute_script` — detached launch, per-`command_id` log, immediate
      `COMMAND_ACCEPTED`, never awaits completion
- [x] `tail_log_and_report` — reads only when the file has grown, plus a final
      drain so output between the last poll and exit is not lost
- [x] `terminate_script` keyed by `command_id`; `terminate_process` by name
- [x] On-arrival re-validation with the bundled interpreter
- [x] Screen capture — JPEG, base64, via `to_thread` (verified live at
      1920x1080, 119 KB)

### Access control
- [x] **Indeterminate pause** — hold one machine or the whole room with no
      stated end. No countdown on the client, because there is no deadline to
      show. Internally capped at 1 hour as a fail-safe against the *admin*
      disappearing, with the Admin GUI warning at 5 minutes so extending is
      deliberate. Pause beats a scheduled block; dropping it reverts to the
      countdown rather than releasing a still-blocked machine.
- [x] Script execution capped at 5 minutes (15 max), reported as
      `status: "timeout"` so it reads differently from a crash
- [x] Website filtering, both modes, hosts-file based inside delimited markers
      so an administrator's own entries survive. Blocks bare **and** `www.`
      forms — blocking one alone does not bite.
- [x] App blacklist enforced on the monitoring cycle. Blocking a launch means
      terminating shortly after start; there is no pre-launch hook without a
      kernel driver.
- [x] Dialog window — frameless, translucent, draggable by its own surface,
      answer returned as an exit code. **QML, not tkinter**: the project is
      already committed to Qt 6 + QML, and a second toolkit for two windows is
      not justified — nor does tkinter do frameless/fluid well.
- [x] Overlay window — scrim over the primary display with a centred panel
      rather than an opaque takeover, topmost re-assert every 500ms, Task
      Manager policy toggled and **always restored**, even on a crash
- [x] `client/ui/` — Theme.qml and ActionButton.qml shared by both, so one
      easing curve and one palette govern the pair
- [x] `%ProgramData%` state store, HMAC-protected, atomic writes,
      **fails closed** on tampering
- [x] 2-hour continuous-block cap
- [x] Watchdogs: agent polls every 30s **and** `client/watchdog.py` runs from a
      Scheduled Task every 5 minutes, covering the agent itself having hung
- [x] Reboot handling: `check_on_startup` re-applies an active block before
      anything else, with no Engine needed
- [x] Watchdog runs outside the connection loop — a machine does not become
      unrestricted because the network went down

### Packaging — **moved to Phase 8**

- [x] `install_service.py` — service registration, `%ProgramData%` ACLs, and
      the watchdog Scheduled Task in one step. Stays here: it is installation,
      not packaging, and needs nothing built first.
- [x] Tests — 161 passing at the close of this phase

**Verified live:** the dialog rendered, counted down and returned exit code 2
(timed out); the overlay covered the primary display for its full window,
self-closed and exited 0. Neither produced a QML error.

**Still unverified:** the Task Manager policy. This machine denies the registry
write (group policy owns the key), so the overlay degrades to a plain
fullscreen window — intended behaviour, but it means enable-and-restore has
never actually run. Confirm on a real lab machine where the agent runs as
SYSTEM. See issues.md C10.

---

## Phase 4.5 — Transport encryption ✅ (pulled forward from Future Enhancements)

- [x] TLS on the Engine listener and both client types, self-signed and pinned
- [x] Certificate identity is a fixed name (`labmonitor-engine`), so hostname
      verification stays on even on a DHCP address
- [x] `scripts/generate_cert.py` — openssl-backed, no new Python dependency
- [x] Presence-based enabling: no flag to forget, loud startup log either way
- [x] Fails closed — bad certificate stops the Engine; a client that cannot
      build a context refuses rather than downgrading to plaintext
- [x] 15 TLS tests against real handshakes, asserting refusals as well as
      successes, plus 2 end-to-end through the agent's own connect path
- [x] `certs/` and `*.pem` gitignored — the key is secret, the certificate is
      deployment-specific

## Phase 5 — Manual per-system verification ⬅ in progress

Prove each unit works **on its own, on its own machine**, before anything is
integrated or packaged. Each system has a diagnostic that needs nothing else
running, so a failure points at one component instead of at "the system".

- [x] `python -m engine`, `python -m client`, `python -m admin` — argparse on
      each unit, in a `cli.py` per package. Config is read from the environment
      into `Final` constants at import time, so flags are applied to the
      environment *before* the component is imported; the three `main.py` files
      were not touched and still work environment-only.
- [x] `labmonitor.py` — dev launcher dispatching to all three plus the helpers,
      importing each lazily so the Engine never pulls in PySide6
- [x] `engine --check` — resolved config, TLS posture, prepares the database,
      does not bind the port
- [x] `client --once` — one real collection cycle, printed, with no Engine
- [x] `client --check` — config, local state, and which bundled pieces are absent
- [x] `admin --check-qml` — loads every QML file offscreen, reports warnings

Verified on a dev box: `--check-qml` loads every QML file clean; `--once`
returned 212 processes with real CPU numbers, window titles, network counters
and idle time.

**The lab is built and the first tests have passed (2026-08-13).** Both VMs
exist, are checkpointed, and the three components have talked to each other
across three machines over TLS. Recorded in `testing.md`'s results table:
**T0.1** (the gate — client VM reaches the Engine on 5000), **T1.1**, **T1.2**
(Engine serves, TLS on, `EpollSelector`), **T5.1** (registration, 15s
heartbeats, telemetry) and **T5.2** (Admin receives relayed telemetry).
`LAB-SETUP.md` is the procedure that rebuilds that lab from nothing on any
Windows 11 Pro machine — it is deliberately machine-agnostic, since the lab is
built again on the presentation machine.

To run by hand:

- [x] Engine — `--check`, then serve, and confirm the listen address, transport
      mode and auth posture in the log. **Done on the Debian VM**, not WSL: the
      lab supersedes the WSL arrangement, though WSL remains the fallback
      topology for a machine short on disk
- [x] Client on a Windows machine — `--once`, then a live session; confirm
      registration, heartbeats every 15s, and telemetry on its own intervals
- [x] Administrator — `--check-qml`, then connected; roster and live dashboard
      confirmed. **A command round trip and all five reports are still to do**
- [ ] Dialog window — `labmonitor.py dialog --message "Test" --timeout 15`
- [ ] Overlay window — `labmonitor.py overlay --until <near-future ISO>`.
      **Takes over the screen and disables Task Manager**; run it when
      convenient, and check both directions of the Task Manager policy
      ([issues.md](issues.md) C10)
- [ ] **Does enforcement reach the screen from a service context?** The agent
      and the watchdog both run as SYSTEM in session 0, which is isolated from
      the interactive desktop — so the overlay may be invisible while every log
      line reports success ([issues.md](issues.md) C11). Needs elevation, so it
      could not be settled from a dev session. Gates a real *install*, not the
      defence demo, which runs the agent by hand.
- [ ] Duplicate overlays from a watchdog pass ([issues.md](issues.md) C12,
      verified) — observe the count, then fix once C11 is measured

**Not started: Parts 2, 3 and 4 in full** — the helper windows, the client's own
diagnostics on the VM, reconnect behaviour, and the service-context questions.
`testing.md`'s results table is the checklist, and most of its rows are still
empty. "It worked when we demonstrated it" and "Phase 5 passes" are different
claims, and only the first is currently true.

[testing.md](testing.md) is the step-by-step plan for this phase,
[LAB-SETUP.md](LAB-SETUP.md) is how the lab gets built (and rebuilt elsewhere),
and [remember.md](remember.md) is the one-page list of what not to forget.

**What this phase cannot tell you.** With packaging last, all of the above
exercises the *fallback* paths: the running interpreter for script validation
and execution, and the overlay run as a module rather than as an executable. A
green Phase 5 does not transfer to the packaged build, so Phase 8 carries a
short re-verification of the same ground.

### Built ahead of schedule, during Phase 5

Two things arrived here rather than in their planned phase, both because the
lab made the gap obvious the moment real data was on screen. **The protocol
gained two message types**, so `README.md`'s Communication Protocol section now
lags the code — the deviation is recorded here per the usual rule:

- **`WATCH` (admin→Engine) and `SET_SAMPLE_RATE` (Engine→client).** Selecting a
  client subscribes the console to that machine's telemetry *and* asks the
  machine to sample every 3s while watched. This closes `issues.md` D5's
  fan-out and the live half of C19. `SET_SAMPLE_RATE` is deliberately **not** in
  `DURABLE_COMMANDS`.
- **Screen captures are saved and previewed.** The image had been arriving in a
  `COMMAND_RESPONSE` and being discarded, so the operator was told "Captured
  1920x1080" and given nothing. Now written under the operator's own directory
  (`ADMIN_CAPTURE_DIR`) and shown.

### Admin presentation work, also done here

`issues.md` C17's first half: the window opens maximized, one Material dark
theme replaces the platform default, and the console has a design system —
`Theme.qml` plus `Section`, `SegmentedControl` and `StatTile`. Policy was
rebuilt around blast radius. The ordering rule ("no UI work until Phase 5
passes") was relaxed deliberately once T5.1 and T5.2 had proven the system end
to end, which was the rule's actual purpose.

---

## Phase 6 — Full Integration

- [ ] All three components running together
- [ ] Multi-client scenarios (target 10+, design ceiling 50). **One box can
      simulate many clients for telemetry, policy and reporting, but not for
      enforcement** — separate state does not buy a separate screen, so
      overlays would fight over one display ([issues.md](issues.md) D8). Use
      VMs or real machines for the enforcement half.
- [ ] Network failure / reconnect behavior
- [ ] Performance + load testing
- [ ] **Re-measure client RAM footprint** — README flags the <50MB figure as
      predating the bundled runtime and helper exes, and explicitly unverified

---

## Phase 7 — Authentication (a hard prerequisite for real deployment)

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

## Phase 8 — Packaging (last)

Moved out of Phase 4. No design decisions remain — the runtime question was
settled in [issues.md](issues.md) B11 — so this is build work, and it is worth
least before the code it wraps has been proven on a real machine.

- [ ] **Bundle the pinned embeddable Python for script execution.** Scripts are
      stdlib + `subprocess` only, so the embeddable distribution is sufficient
      and the import policy enforces it. Until this exists the agent and the
      Admin validator both fall back to the running interpreter and log a
      warning.
- [ ] Freeze the helper windows into **one** executable with a mode flag, so the
      Qt payload is paid for once rather than twice. An embeddable distribution
      has no pip and so could never carry PySide6 — these two concerns stay
      independent.
- [ ] Both bundles must be the **same pinned version**, or a script that
      validates on the Admin console can still fail on a lab machine
- [ ] Windows service wrapper (the deferred Phase 1 item)
- [ ] **Re-verify the Phase 5 ground against the packaged build** — script
      validation, script execution and the overlay all run through different
      paths once the bundles exist

---

## Deferred / Out of scope

Postgres migration, and everything under README "Removed Features".

*(TLS was here, and is no longer deferred — it was pulled forward and built in
Phase 4.5 above.)*
