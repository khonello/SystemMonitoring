# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**`remember.md` is the one-page list of things that are easy to forget and expensive to get wrong** — safety rules, the silent-failure modes, and what the doc and issue naming means. Read it first after any gap in the work.

Two root-level docs track the work: **`todo.md`** is the phase-by-phase plan, and **`issues.md`** logs known bugs, deferred decisions and unverified claims. Read both before starting a phase — `issues.md` marks which items block which phase. **`commands.md`** is the operational CLI reference — every program, its flags, and why the entry points are split the way they are; keep it current when a flag changes, since unlike the README it is meant to track the code. **`testing.md`** is the Phase 5 manual test plan: the two-VM topology, what to run on each unit, and what the result should look like. **`LAB-SETUP.md`** is the procedure that builds that lab from nothing on any Windows 11 Pro machine — ten steps, five scripts, a symptom-first pitfalls table, and a separate section for *updating* a lab that already exists. It carries the Debian install screen by screen, with the answers and the traps: tasksel's Space-not-Enter, the keyboard layout test (`@` vs `"` above the `2` key — the layout follows the keyboard, never the country), why there is no `sudo`, and the finished-dialog ghost that looks like a freeze. It is deliberately machine-agnostic (no drive letters anywhere) because the lab is built on the dev box and rebuilt on the presentation machine.

**Scope is a project defence demonstrated on VMs, not a deployment.** No institutional approval is in play (`issues.md` A2), and it changes what the open findings block: C11 — the agent's service and watchdog run as SYSTEM in session 0, so the overlay may render where nobody can see it while every log line reports success — gates a real *install*, not the demo, because a hand-run agent never enters session 0. Unverified; needs elevation to test. C1 (authentication accepts anyone) likewise gates deployment. Nothing blocks the defence.

**Overlay duplication is fixed, and the shape of the fix matters (B25).** The overlay holds a lock in `STATE_DIR` for its own lifetime, so `overlay_running()` answers "is a lockout on screen?" for every launcher rather than "did *I* start one?". The holder records its pid beside the lock so a launcher without a handle can still stop it — and `_stop_overlay_by_pid` refuses to signal its own pid, because the first version terminated the test suite. Cross-process *mode* transitions are deliberately not handled: a watchdog cannot know the agent's overlay mode, and leaving a screen blocked in the wrong mode beats flapping or doubling it.

**`LAB-UPDATE.md` is the change-code-and-get-it-into-the-lab loop on one page** — cut the disc (elevated, *no* `-AttachTo`, the script sweeps every VM holding it), `REFRESH=1` on the Engine, copy and clear the read-only bit on the client, `umount` before the next cut. It is the condensed form of `LAB-SETUP.md` § *Updating a lab that is already running*; that section carries the reasoning, this one the sequence. Keep both in step.

**`LAB-NETWORK.md` is the switch, and the one demonstration it blocks.** The `LabMonitor` switch is Internal with no gateway, which is what structurally contains C1 — an Engine nothing can route to is one nothing can register with. The exception is website filtering: with no internet, "blocked" and "no network" look identical on screen, so it proves nothing. That page turns on host-side NAT (`New-NetNat` on 192.168.100.0/24; the host already holds 192.168.100.1) and back off again, without renumbering anything. Read the two gotchas before blaming the network: **the browser's DNS-over-HTTPS bypasses the hosts file entirely**, and **the agent must be elevated to write it**.

**`issues.md` section D is "accepted limitations"** — things deliberately not built, each with what would change the decision. Check it before "fixing" something that looks missing (D5, the telemetry fan-out, was resolved on 2026-08-13 and is kept there for its reasoning): storage staying relational, no per-client partitioning, no client→Engine→same-client flow, the Engine staying stateless per message, hosts-file whitelist approximation, one-off rather than recurring lockout schedules, and one machine being unable to simulate many *enforcing* clients are all decisions, not gaps.

Phases 0–4 are complete: Engine, Administrator and Client Agent are all implemented and tested (**307 tests**). **Phase 5, manual per-system verification, is in progress**: the lab is built, the gate has passed, and the three components have run together across three machines over TLS — but only five of `testing.md`'s ~25 result rows are filled. Follow **`LAB-SETUP.md`** to build the lab; its pitfalls table is symptom-first, and it now carries a separate section for *updating* a lab that already exists.

**Two features were built early, during Phase 5, and the README's protocol section therefore lags the code** (deviation recorded in `todo.md`):

- **Selection is a subscription.** An admin declares what it is watching (`MSG_WATCH`); the Engine relays that client's telemetry only to the consoles watching it, and asks that client to sample every 3s instead of 30/60 (`MSG_SET_SAMPLE_RATE`, `engine/watch.py`, `client/sampling.py`). Fast sampling expires by itself, is renewed while the watch is live, and is **not** durable. This closed `issues.md` D5 and the live half of C19. **Recording is untouched by any of it** — the persist step runs before any relay and never consults the registry.
- **Screen captures land somewhere.** They had been arriving as base64 in a `COMMAND_RESPONSE` and being discarded; they are now saved (`ADMIN_CAPTURE_DIR`, default `~/LabMonitor/captures`) and previewed.
- **Idle time reaches the console (2026-08-15).** It was collected and sent on every heartbeat and then dropped at the Engine — logged, never stored, never relayed. `handle_heartbeat` now relays `MSG_CLIENT_STATE` (`idle_time`, `screen_locked`, `status`) to the consoles *watching* that client, and only for peers whose role is client. Live only, deliberately not stored: `issues.md` D10 has the reasoning and what would change it.

**The Admin has a design system now** (`admin/qml/Theme.qml` plus `Section`, `SegmentedControl`, `StatTile`, `StatePill`, `ListEditor`, registered via `admin/qml/qmldir`). One palette, a 4px spacing scale, one 30px control height, one 4px radius, `Material.roundedScale: SmallScale`. Don't add a colour or a spacing value inline — put it in `Theme.qml` or use what is there. Primary navigation lives in the header; a choice *within* a page is a `SegmentedControl`, never a second `TabBar`.

**State is said in words, not in a colour change (2026-08-15).** Anything reporting a state — paused, sent, blocked, malformed — carries a `StatePill`: a dot, a word, and its own tint. It exists because a control whose two states differed only by one surface step was unreadable on a near-black canvas, and because Material's *own* button chrome cannot be relied on for it. `SegmentedControl` segments may declare a `tint`, which is how whitelist mode comes up amber against blacklist's blue: the mode that breaks pages if you get it wrong should not look like the one that doesn't.

**Policy is two pages, split on a line the protocol already draws.** *Policy* holds the `DURABLE_COMMANDS` — website filtering and the application blacklist — which declare state a machine converges to and which the Engine queues and replays for a machine that was offline. *Restrictions* holds what acts now on a connected machine or is recorded undeliverable: pause, terminate, scheduled block, and the one marked "every connected machine" section (fleet pause moved here out of the roster footer, which is a way of choosing what to look at, not a way of acting on it). Both list editors are `ListEditor`, which counts entries, validates each line, names the malformed ones, and says whether what is on screen has been **sent** — never "in force", because nothing in the protocol reports a client's current policy back.

**Two Qt traps this cost hours to find, both silent.** A `Property` whose `notify=` names a signal defined on a *base* class produces a metaobject the QML engine walks off the end of: the process dies with an access violation before any QML error is printed, and `--check-qml` reports nothing. Use a `@Slot` and the `count >= 0 ? model.thing() : 0` idiom instead. Separately, `background: null` on a Material `TextArea` takes the placeholder with it, and `placeholderText` is a *floating* label — a pre-filled field draws its content on top of its own ghost. `ListEditor` uses `background: Item {}` and draws its own hint.

**Everything below describes a lab that gets rebuilt on a different machine.** Nothing here is specific to the box it was first built on: no drive letter is a constant (the scripts pick one), the keyboard layout is decided by a test rather than copied, and every path that matters is either derived or overridable. When updating these notes, write them for the machine that does not exist yet.

**Where the build-out actually stands** (drive letters below are from the first build only — the scripts find their own):

- **`LabClient` is DONE.** Stock Win11 24H2 Pro, local account `lab`/`lab`, Python 3.12 from python.org installed **for all users** at `C:\Python312`, repo copied (not cloned) to `C:\SystemMonitoring`, **venv named `environ`, not `.venv`** (so every command on that VM is `C:\SystemMonitoring\environ\Scripts\python.exe`, and `lab_client_setup.ps1` — which hardcodes `.venv` at line 171 — would build a *second* venv if re-run there; pass it the existing path or accept the duplicate), packages installed, `client --check` clean — id `labclient-1-windows`, three MISSING bundles, `agent running False` — static `192.168.100.3/24` with no gateway, Dynamic Memory 2/1/3 GB, automatic checkpoints off, and the **`baseline` checkpoint taken**.
- **`LabEngine` is DONE** (2026-08-13). Debian **13.6.0** trixie, minimal — ~1.2 GB and 313 packages, no desktop — user `lab`/`lab`, **no `sudo`** (Debian omits it when a root password is set; use `su -`), keymap `gb`. Repo copied to `/opt/SystemMonitoring`, `engine --check` clean: **TLS with `certs/engine-cert.pem`**, authentication **not** BYPASSED, `Database ready.` Static `192.168.100.2/24` with no gateway, 512 MB static, 1 vCPU, on `LabMonitor`, and the **`baseline` checkpoint taken**. `LabRepo.iso` is still in its DVD drive.
- **The gate is PASSED and the system has run end to end (2026-08-13).** `TcpTestSucceeded : True` between the VMs, then registration, 15s heartbeats, telemetry, and an Admin on the host receiving relayed data over TLS. Five rows of `testing.md`'s results table are filled: **T0.1, T1.1, T1.2, T5.1, T5.2**. Everything else in that table is still empty — Parts 2, 3 and 4 have not been run, so **"it worked when we demonstrated it" is true and "Phase 5 passes" is not**.
- **Resume here: `testing.md` Part 2 onward**, plus a command round trip and the five reports from Part 3. Start both VMs, run the Engine as `lab` (not root — root leaves journal files `lab` cannot write), start the agent on the client, and work down the results table.
- **Updating a running lab is its own procedure**, separate from building one: `LAB-SETUP.md` → *Updating a lab that is already running*. Build and attach the disc with `scripts/build_repo_iso.ps1 -AttachTo LabEngine,LabClient`, then move promptly — the medium can drop out of a guest minutes later, and the same page has the symptom-first recovery. Once the lab is networked, `scp` to the Engine beats re-cutting a disc.
- **512 MB is what the Engine runs in, not what it installs in** — Debian 13 drops into low-memory mode below roughly a gigabyte and stops to ask which udebs to load, so `setup_lab_vms.ps1` creates the VM at 2 GB and `lab_host_finalize.ps1` cuts it back. Both VMs follow that shape: install-time size at creation, runtime size at finalize. Then `lab_host_finalize.ps1 -VMName LabEngine` on the host, then the T0.1/T0.2 gate, then Part 1.
- **`scripts/vm_console_shot.ps1 -VMName <vm>` reads a running guest's screen from the host** (Hyper-V's WMI thumbnail API — no agent, no network, nothing typed into the guest), so "what is on screen right now?" is answerable at a boot menu or mid-installer, when nothing else can see anything. It is a diagnostic aid, not part of the procedure, and it is what caught the Debian low-memory banner.
- **Opening a VM's console before starting it is not optional** — VMConnect renders only once attached, so starting first means the five-second boot prompt expires unseen and the keyboard looks dead. This will catch the Engine VM exactly as it caught the client one.
- `LabRepo.iso` is the repo-on-a-disc built with `oscdimg` (LAB-SETUP.md step 4, reasoning in `testing.md` 0.1c). It is how code reaches both guests without ssh, shares or a network — an isolated switch rules out every other transport — and the same image serves the Engine VM. **It is a snapshot and goes stale silently**, so `scripts/build_repo_iso.ps1` is the only way it should be cut — it stages, images, ejects the old disc, copies, re-attaches (`-AttachTo LabEngine`), and then *verifies*: `DvdMediaType` rather than the reported path, and the on-disc `lab_engine_setup.sh` hashed against the working copy. Both checks exist because both failures happened — a disc missing three of four scripts on 2026-08-12, and a "fixed" script tested on 2026-08-13 against a disc that never received the fix. The one part it cannot do is `umount /mnt` inside a running guest; Linux holds the medium, so that stays a manual step and the script names it when the copy is blocked.

**The lab is built twice** — here, and again on the presentation machine, which has a different disk layout. That is why no script hardcodes a drive letter and why the pitfalls are written down rather than remembered.

**The Admin GUI needs real visual work before the defence (`issues.md` C17).** Dimensions read as distorted and it looks like a prototype rather than an operator tool — which matters more than usual, since the Admin is the only component an audience looks at for any length of time. It is a *presentation* defect, not a correctness one: the Admin registers, heartbeats, dispatches and receives telemetry, and its QML loads clean. Replacing Qt with DearPyGui was floated; C17 records what that would cost (qasync and the single-threaded design, a second toolkit alongside the client's QML helpers, a second stack in Phase 8 packaging) and recommends fixing the QML layout instead. Don't start a toolkit migration without reading it. C17 also holds a **fleet-view proposal** — a tile or rail per connected client, selecting one to scope the dashboard to it — with the recommendation to use a persistent left rail rather than a separate page, so selection can never become a hidden mode, and to keep *view* scope separate from *command* scope.

**Order of work, decided and not negotiable by convenience: prove the system end to end first.** No UI work starts until Phase 5 passes — restyling a system that has not been shown to work means debugging both at once. C17 then comes *before* authentication (C1) deliberately: C1 gates a deployment and the Internal switch already contains it structurally, while the Admin is the only component an audience looks at for any length of time.

Two things from that build-out that cost hours and will cost them again: **open a VM's console *before* starting it** (VMConnect renders only once attached, so the five-second boot prompt expires unseen and the keyboard looks dead — `testing.md` 0.1d), and **the trimmed client image was abandoned** (`issues.md` D9) — it installs and then loops OOBE forever, so the client VM runs **stock** Win11 and `build_client_image.ps1` is kept as record only. Packaging was moved out of Phase 4 to Phase 8 (dead last) — packaging code that has never been proven on its target machine is the wrong order of work, and no design decisions remain in it. Three code paths fall back to the running interpreter meanwhile and log a warning; those fallbacks are for bringing a machine up, not for shipping, so Phase 5's results do not fully transfer to the packaged build.

`issues.md` section A lists decisions only the user can make (retention period, institutional approval, TLS scope). Don't try to resolve those in code.

`README.md` is the design specification, including reference implementations as fenced code blocks. Where the working code and the README disagree, the code is newer — the deviations and their reasons are recorded in `todo.md`.

## Commands

Run everything through the venv. The project is installed editable, which is what makes `from common.protocol import ...` resolve from every entry point.

Requirements are split per deployable unit — the Engine is standard-library only, so a Linux install pulls nothing. A dev box runs the whole suite and needs all three files:

```powershell
pip install -r requirements.txt -r requirements-admin.txt -r requirements-client.txt
```

```powershell
.\.venv\Scripts\python.exe -m pytest -q                    # 289 tests
.\.venv\Scripts\python.exe -m pytest -q --cov=engine --cov=common --cov=admin
.\.venv\Scripts\python.exe -m scripts.bench_database       # SQLite write cost
```

**Each unit has its own CLI: `python -m engine`, `python -m client`, `python -m admin`.** `labmonitor.py` dispatches to all three plus the helpers on a dev box. Every flag maps onto an existing env var — the flag exists because config is read at import time, so `<package>/cli.py` writes to `os.environ` *before* importing the component. That is also why the three `main.py` files were left untouched and still work env-only via `python -m <package>.main`. Don't move argparse into them. Full flag-by-flag reference, including the helper programs: **`commands.md`**.

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

**One agent per client id, guarded by an OS lock — not a heartbeat file.** `client/single_instance.py` holds an exclusive byte lock on `agent.lock` in `STATE_DIR` for the process's life, acquired in `main()` *before* `lockout.check_on_startup()` — a duplicate that discovered itself later would already have launched a competing overlay. The Engine cannot catch this itself: a second connection for a known peer is indistinguishable from a reconnect, so it replaces the writer and the first agent talks to a dead socket. Two rules not to undo: it is keyed on the **client id**, never the machine, or the multi-client simulation B21 exists for dies; and it returns "proceed" on anything that is not a positive detection of another holder, because refusing to start on an unwritable state directory leaves the machine with nothing enforcing. Don't replace it with a refreshed timestamp and a staleness window — that fails open on crash-restart, when service recovery restarts an agent whose file is still fresh.

**Lockout enforcement fails closed.** The schedule under `%ProgramData%` is HMAC-protected; if validation fails, treat the block as still active. Blocks are capped at 2 hours as a safety timeout against the overlay's own hangs (not against network loss — enforcement is local and doesn't need the Engine). Two independent watchdogs exist because the overlay *and* the agent can each hang: the agent polls every 30s, and an installer-registered Windows Scheduled Task checks every ~5 min. On boot the agent re-reads the schedule before anything else and re-launches the overlay if a block is still active.

## Build order

Scaffold everything first (module structure, signatures, empty handlers wired into dispatch) so messages flow end-to-end before real logic exists. Then implement fully, one component at a time, testing each before starting the next: **Engine → Admin → Client**, with full integration testing last. The Engine is finished first specifically so the other two are built against real behavior rather than assumptions.

## Code style

- Python 3.10+, PEP 8, type hints everywhere, docstrings on all functions, 100-char lines.
- **Prefer functions over classes** — use classes only when genuinely necessary. Module-level dicts hold shared state (`connections`, `client_info`, `running_scripts`); prefer immutable data and pure functions elsewhere.
- Catch specific exception types, log with context, degrade gracefully, and never surface internal errors outward — return `{"status": "error", "message": ...}` shaped results.
