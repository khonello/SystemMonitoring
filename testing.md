# Phase 5 — manual per-system verification

Prove each unit works **on its own** before anything is integrated. Every test
here needs at most one component running, so a failure points at one component
rather than at "the system".

Commands are given in short form. `commands.md` is the reference for every flag
and what it does; this file says what to *run* and what you should *see*.

Work top to bottom. Part 0 is setup, Parts 1–3 are the three units in isolation,
Part 4 is the helper windows, Part 5 is the two-machine link. Record results in
the table at the end.

---

## What this phase cannot tell you

Stated up front so a green run is not over-read.

- **Packaging is Phase 8**, so three code paths here run their *fallback*: the
  Admin's script validator and the Client's script executor both fall back to
  the running interpreter, and the overlay runs as a Python module instead of
  a frozen executable. Each logs a warning. Phase 8 re-verifies this ground.
- **Authentication is a stub** (`issues.md` C1). `verify_challenge_response`
  returns `True` unconditionally, so anyone on the network can register as any
  client or as an admin. **Test on an isolated network — a phone hotspot or a
  direct cable between the two laptops — never on campus or shared Wi-Fi.**
- **Running by hand is not running as a service.** Everything below runs in your
  own login session. A service runs in session 0, which may behave differently
  for anything that draws on screen — that is exactly what T5.4 exists to check.

---

## Part 0 — Setup

### 0.1 Machine roles

Two laptops is enough. The Engine is Linux-only by design, so it runs under WSL
on the Windows laptop rather than needing a third machine.

| | Laptop A ("server") | Laptop B ("lab machine") |
|---|---|---|
| Engine | ✅ under WSL | — |
| Administrator | ✅ on Windows | — |
| Client Agent | — | ✅ on Windows |

### 0.1a One machine, if that is all you have

All three run on a single laptop: **two on Windows** (Administrator, Client
Agent) **and one in WSL** (Engine). Nothing in Parts 1–3 needs a second machine,
and the whole command path — registration, telemetry, policy, reports, the audit
trail — works end to end this way. WSL2's localhost forwarding means the client
reaches the Engine at `127.0.0.1:5000` with no setup at all, so §0.2 below can be
skipped entirely.

What a single machine **cannot** test:

- **Anything the student would see.** The overlay would cover *your* screen and
  disable *your* Task Manager while you are working. T4.2–T4.6 and T5.5–T5.8 all
  need a machine you are willing to lose for a few minutes.
- **The link itself.** A real network hop, the WSL NAT crossing, TLS against a
  non-loopback address, and the reconnect/backoff behaviour of T5.3 are all
  loopback no-ops on one box.
- **Session 0 (C11).** Installing the service on your dev machine to test this
  means a service that starts on every boot and can black out your screen.

So: use one machine for Parts 1–3 and T5.1–T5.3, and bring in Laptop B for
Part 4 and T5.4 onward. Running the client under `--id` on the same box as the
Engine and Admin is not a compromise for any of the former — it is the same
socket, protocol and database either way.

**Engine and Admin on one laptop is fine and is the intended dev setup.** They
are different processes, in different operating systems, talking over a socket;
WSL2 forwards `localhost`, so the Admin reaches the Engine at `127.0.0.1:5000`
with no configuration. Nothing about co-locating them is a compromise — you are
still exercising the real socket path, the real protocol and the real database.

Two things to be aware of, neither a blocker:

- **`ENGINE_HOST` means opposite things to the two units** — the bind address on
  the Engine, the connect target on the Admin. They live in different shells
  (WSL vs Windows) so they cannot collide, but don't export it globally.
- **The database sits on `/mnt/c`** if you run the Engine from the Windows
  filesystem. SQLite over that mount is slower than a native Linux path and its
  locking is emulated. Run `python -m scripts.bench_database` once and note the
  number; if it is unpleasant, copy the repo into the WSL filesystem
  (`~/SystemMonitoring`) for the Engine only.

### 0.2 The one real obstacle: reaching WSL from Laptop B

WSL2 sits behind a NAT inside Laptop A. `localhost` forwarding is what lets
Windows-on-A reach it — but that does **not** extend to another machine. Left
alone, Laptop B cannot see the Engine at all.

Two ways to fix it. Try mirrored networking first; it is one line and removes
the problem instead of working around it.

**Option 1 — mirrored networking** (Windows 11 22H2+). In `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
```

Then `wsl --shutdown` and restart. WSL now shares the Windows network interface,
so the Engine is reachable at Laptop A's LAN address directly.

**Option 2 — port proxy.** From an **elevated** PowerShell on Laptop A:

```powershell
$wsl = (wsl -- hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=5000 listenaddress=0.0.0.0 connectport=5000 connectaddress=$wsl
netsh advfirewall firewall add rule name="LabMonitor Engine" dir=in action=allow protocol=TCP localport=5000
```

The WSL IP changes on reboot, so this needs redoing. To undo:

```powershell
netsh interface portproxy delete v4tov4 listenport=5000 listenaddress=0.0.0.0
netsh advfirewall firewall delete rule name="LabMonitor Engine"
```

Either way, confirm from Laptop B before going further:

```powershell
Test-NetConnection <laptop-A-ip> -Port 5000
```

`TcpTestSucceeded : True` is the gate. If it is False, nothing in Part 5 will
work and the fault is here, not in the code.

### 0.3 Install

Laptop A (both units) and Laptop B (client only):

```powershell
pip install -r requirements.txt -r requirements-admin.txt -r requirements-client.txt   # A
pip install -r requirements.txt -r requirements-client.txt                             # B
```

The Engine needs nothing installed in WSL — it is standard library only.

### 0.4 TLS

TLS is presence-based: once `certs/engine-cert.pem` exists, all three units use
it with no flag. Generate **once**, on Laptop A:

```powershell
python -m scripts.generate_cert
```

Then copy the whole `certs/` directory to Laptop B at the same relative path.
Clients pin that exact certificate and verify against the fixed identity
`labmonitor-engine`, not the IP — so Laptop A's address can change without
breaking anything, but a *regenerated* certificate breaks every client until
it is re-copied.

To take TLS out of the picture while diagnosing something else, `--no-tls` on
all three. Put it back before you call Phase 5 done.

- [ ] **T0.1** `Test-NetConnection` from B to A on 5000 succeeds
- [ ] **T0.2** `certs/` present on both machines, same files

---

## Part 1 — Engine, alone (Laptop A, WSL)

Nothing else running for any of this.

### T1.1 — Configuration and database

```bash
wsl -- bash -lc "cd /mnt/c/.../SystemMonitoring && python3 -m engine --check"
```

Expect: listen address `0.0.0.0:5000`, the resolved database path, max clients
and admins, heartbeat timeout `60`, retention `30 days`, transport line, an
authentication line, then `Database ready.` and exit 0.

Check specifically:
- Transport says **TLS** with a certificate path — if it says PLAINTEXT, the
  certificate is not where the Engine is looking.
- Authentication says the handshake runs. If it says **BYPASSED**, you have
  `DEV_BYPASS_AUTH` set in that shell; unset it.
- It does **not** bind the port. Run it twice in a row to confirm.

- [ ] **T1.1** passes

### T1.2 — Serving

```bash
wsl -- bash -lc "cd /mnt/c/.../SystemMonitoring && ENGINE_LOG_LEVEL=DEBUG python3 -m engine"
```

Expect a listening log line and then silence — no peers yet. Leave it running
for the rest of Part 1.

- [ ] **T1.2** starts and stays up

### T1.3 — Refusing a plaintext peer

With TLS on, from Laptop A's Windows side:

```powershell
python -m client --once            # no network; just proves the client works
python -m client --no-tls --id tls-probe
```

The second should fail to establish a session, and the Engine should log the
refusal. This is the check that TLS is genuinely enforced rather than optional.
Stop the probe after you have seen it.

- [ ] **T1.3** plaintext client is refused, and the Engine says so

### T1.4 — Database is being written

```powershell
python -m engine.setup_db --help    # confirms the helper exists
```

Then after Part 5 has produced traffic, confirm `monitoring.db` has grown and
that `scripts/bench_database.py` reports a sane write cost:

```powershell
python -m scripts.bench_database
```

- [ ] **T1.4** write cost recorded: ______ ms/write

---

## Part 2 — Client Agent, alone (Laptop B)

No Engine needed for T2.1–T2.4. This is the most valuable part of Phase 5 —
every failure here would otherwise look like a networking problem later.

### T2.1 — Collection actually works on this hardware

```powershell
python -m client --once --top 20
```

Expect: a process count in the hundreds, **non-zero CPU percentages** (zeroes
everywhere means the priming pause did not work), memory figures, some window
titles, cumulative network counters, a USB line, an idle time in seconds, and a
screen-lock boolean.

The first USB poll establishes a baseline, so already-mounted drives are *not*
reported. Plug a drive in and re-run to see an insertion.

- [ ] **T2.1** processes: ______  |  window titles seen: Y/N  |  CPU non-zero: Y/N
- [ ] **T2.2** USB insertion detected on a second run: Y/N

### T2.3 — Configuration and state

```powershell
python -m client --check
```

Expect the resolved client id, the Engine target, transport, and three
**MISSING** bundle lines (pinned Python, dialog exe, overlay exe) — missing is
correct until Phase 8. Then the state directory, `writable True`,
`lockout active False`, `paused False`, and `agent running False`.

Note the state path. It should end in a sanitised id plus a hash suffix, e.g.
`...\SystemMonitoring\lab-b-Windows-1f4c9a02`.

- [ ] **T2.3** state dir: ________________  writable: Y/N

### T2.4 — One agent per id

```powershell
python -m client --id probe          # leave running
python -m client --id probe          # second window
python -m client --id probe-2        # third window
python -m client --id probe --check
```

Expect: the second exits 1 with `Another Client Agent is already running as
probe`, the third runs normally (different id), and `--check` reports
`agent running    True`.

Then kill the first with Task Manager (**End task**, not Ctrl-C) and start it
again — it should acquire normally. That is the crash-restart case.

- [ ] **T2.4** duplicate refused, different id allowed, restart-after-kill works

### T2.5 — Lockout survives a reboot

Set a block through the Admin later (Part 5), then reboot Laptop B while the
block is still open. The agent must re-read the schedule on boot and put the
overlay back **before** anything else. This is the single most important
behaviour in the client.

- [ ] **T2.5** block still enforced after reboot

---

## Part 3 — Administrator, alone (Laptop A, Windows)

### T3.1 — QML loads clean

```powershell
python -m admin --check-qml
```

Expect `OK - 7 QML files loaded with no errors or warnings` and exit 0. Any
warning is a real fault — this is the check to run after touching a `.qml` file.

- [ ] **T3.1** files loaded: ______  warnings: ______

### T3.2 — Configuration

```powershell
python -m admin --check
```

Expect admin id `admin-<hostname>`, the Engine target, the QML directory, the
live-sample cap, transport, and a script-validator line reading **MISSING** —
correct until Phase 8.

- [ ] **T3.2** passes

### T3.3 — The window itself

```powershell
python -m admin
```

With no Engine running: the window should open, show the connect field
prefilled, and fail to connect **without crashing or freezing**. The GUI is
single-threaded over qasync, so a hang here means something blocked the loop.

- [ ] **T3.3** window opens, failed connect is handled cleanly, UI stays responsive

---

## Part 4 — Helper windows (Laptop B)

Both are QML and both take over the screen to some degree. Run them when
convenient, not mid-demo.

### T4.1 — Dialog

```powershell
python -m client.dialog_app --message "Test warning" --timeout 15 --allow-cancel
echo $LASTEXITCODE
```

The answer *is* the exit code: `0` acknowledged, `1` cancelled, `2` timed out,
`3` bad arguments. Test all three of the first three.

- [ ] **T4.1** acknowledged→0, cancelled→1, timeout→2

### T4.2 — Overlay

⚠️ Covers the whole screen and disables Task Manager. Pick an end time a couple
of minutes out.

```powershell
python -m client.overlay_app --until 2026-08-11T14:05:00Z
```

Expect: full coverage of the primary display, a countdown, self-close at the
`--until` time, exit 0.

Then the same with `--mode pause` — it must show **no countdown**. A pause is
the admin holding the screen with no stated end; showing its internal expiry
would turn an admin safety net into a promise to the student.

- [ ] **T4.3** scheduled mode shows a countdown, closes on time
- [ ] **T4.4** pause mode shows **no** countdown

### T4.5 — Task Manager hardening (`issues.md` C10)

Never actually verified — on the dev machine group policy owns the key, so the
write fails and the overlay degrades to a plain fullscreen window, which is the
intended degradation but means the real path has never run.

While an overlay is up, try Ctrl+Shift+Esc. Then after it exits, try again.

- [ ] **T4.5** blocked during: Y/N  |  restored after: Y/N  |  or degraded with a logged line: Y/N
- [ ] **T4.6** does a determined Alt-Tab beat the 500ms topmost re-assert? Y/N

---

## Part 5 — The two-machine link

Only now does anything talk to anything.

### T5.1 — Registration and heartbeat

Engine running on A with `ENGINE_LOG_LEVEL=DEBUG`. On B:

```powershell
python -m client --engine <laptop-A-ip> -v
```

Expect on the Engine: a registration line naming the client id, then a heartbeat
every **15s**. Expect telemetry on its own intervals — app data every **30s**,
network every **60s**. The Engine reaps any peer silent past **60s**.

- [ ] **T5.1** registers, heartbeats at 15s, app data at 30s, network at 60s

### T5.2 — Admin sees it

```powershell
python -m admin --engine 127.0.0.1
```

Expect the client in the roster, live data on the dashboard, and all five
reports returning something: `network_24h`, `network_weekly`, `app_usage`,
`usb_events`, `command_history`.

Leave the Admin idle for **two minutes**. It must stay connected — admins
heartbeat like clients, and without that the Engine reaps them after 60s.

- [ ] **T5.2** roster, dashboard, all five reports, survives 2 min idle

### T5.3 — Reconnect

Pull Laptop B off the network (or stop the Engine) with the agent running.
Expect reconnect attempts backing off from **5s** toward a **60s** ceiling, and
a clean re-registration when the Engine returns.

While disconnected, confirm a *scheduled block still enforces*. Enforcement is
local and must not depend on the Engine.

- [ ] **T5.3** backoff observed, reconnects cleanly, block held while offline

### T5.4 — Does enforcement work from a service context? *(new, unverified)*

**The one to take seriously.** Everything above runs in your login session. In
production the agent runs as a Windows service and the lockout watchdog runs as
a Scheduled Task — both as SYSTEM, in session 0, which is isolated from the
interactive desktop. If a GUI launched from there cannot reach your screen, the
overlay would be invisible while every log line still reports success.

```powershell
# elevated prompt on Laptop B
python -m client.install_service
sc start LabMonitorAgent
```

Then set a block from the Admin and watch Laptop B's screen.

- [ ] **T5.5** overlay visible when launched by the **service**: Y/N
- [ ] **T5.6** overlay visible when launched by the **Scheduled Task** watchdog
      (stop the service first, so the task is the only thing enforcing): Y/N
- [ ] **T5.7** `DisableTaskMgr` written to the **logged-in user's** hive, not
      SYSTEM's: Y/N

If T5.5 or T5.6 is No, that is a fail-open in enforcement and Phase 6 should not
start until it is fixed. See `issues.md` C11.

### T5.8 — Duplicate overlays from the watchdog *(new, `issues.md` C12)*

With the agent running and a block active, wait for a watchdog pass (~5 min) or
run one by hand:

```powershell
python -m client.watchdog --id <the agent's id>
```

`overlay_running()` only sees overlays this *process* started, so the watchdog
cannot tell the agent already has one up. Check Task Manager for a second
`overlay_app` / `labmonitor-overlay` process.

- [ ] **T5.8** number of overlay processes after a watchdog pass: ______

---

## Gate: ready for Phase 6?

Integration should not start until:

- [ ] Every Part 1–4 box is ticked, or its failure is logged in `issues.md`
- [ ] T5.1, T5.2 and T5.3 pass
- [ ] T5.5 and T5.6 are answered — **not** left blank
- [ ] The isolated-network constraint is still true (auth is still a stub)

---

## Results

| Test | Result | Notes |
|---|---|---|
| T0.1 port reachable | | |
| T1.1 engine --check | | |
| T1.2 engine serves | | |
| T1.3 plaintext refused | | |
| T1.4 write cost | | |
| T2.1 collection | | |
| T2.2 USB | | |
| T2.3 config/state | | |
| T2.4 single instance | | |
| T2.5 block survives reboot | | |
| T3.1 QML | | |
| T3.2 admin --check | | |
| T3.3 window | | |
| T4.1 dialog exit codes | | |
| T4.3 overlay scheduled | | |
| T4.4 overlay pause | | |
| T4.5 Task Manager | | |
| T4.6 Alt-Tab | | |
| T5.1 registration | | |
| T5.2 admin end to end | | |
| T5.3 reconnect | | |
| T5.5 service overlay | | |
| T5.6 watchdog overlay | | |
| T5.7 policy hive | | |
| T5.8 duplicate overlays | | |
