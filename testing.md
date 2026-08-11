# Phase 5 — manual per-system verification

Prove each unit works **on its own** before anything is integrated. Every test
here needs at most one component running, so a failure points at one component
rather than at "the system".

Commands are given in short form. `commands.md` is the reference for every flag
and what it does; this file says what to *run* and what you should *see*.

Work top to bottom. Record results in the table at the end.

| Part | What it covers | Machines | Safe on your own laptop? |
|---|---|---|---|
| **0** | Setup: roles, networking, install, TLS | — | yes |
| **1** | **Engine alone** — config resolves, database is writable, it serves, TLS is genuinely enforced | one | yes |
| **2** | **Client alone** — collection works on this hardware, state paths resolve, one agent per id | one | yes |
| **3** | **Admin alone** — QML loads clean, config resolves, the window survives a failed connect | one | yes |
| **4** | Helper windows — dialog exit codes, overlay, Task Manager | VM | **no** — takes the screen |
| **5** | The link — registration, telemetry, reconnect, and enforcement from a service | host + VM | **no** — installs a service |

**Parts 1–3 are the heart of this phase**: each unit proven on its own, with
nothing else running, so any failure names one component instead of "the
system". All three have a diagnostic that needs no network at all, which is why
they come first and why they are safe to run anywhere.

---

## What this phase cannot tell you

Stated up front so a green run is not over-read.

- **Packaging is Phase 8**, so three code paths here run their *fallback*: the
  Admin's script validator and the Client's script executor both fall back to
  the running interpreter, and the overlay runs as a Python module instead of
  a frozen executable. Each logs a warning. Phase 8 re-verifies this ground.
- **Authentication is a stub** (`issues.md` C1). `verify_challenge_response`
  returns `True` unconditionally, so anyone who can reach port 5000 can register
  as any client — or as an **admin**, and issue commands.

  This bites harder than it looks in the chosen setup. The Engine binds
  `0.0.0.0`, and `networkingMode=mirrored` puts WSL on the host's *real*
  interfaces — so on campus Wi-Fi the Engine is exposed to the whole network with
  no authentication behind it. TLS does not help: encryption without
  authentication only means the attacker's session is private too.

  **Run offline.** Nothing here needs a network (§0.1c), so this exposure is
  avoidable entirely rather than merely managed. Bind explicitly with `--host`
  if you want to be certain what is listening where.
- **Running by hand is not running as a service.** Everything below runs in your
  own login session. A service runs in session 0, which may behave differently
  for anything that draws on screen — that is exactly what T5.4 exists to check.

---

## Part 0 — Setup

### 0.1 Machine roles — the chosen setup

One physical laptop, three environments. The Engine is Linux-only by design, so
WSL covers it without a second machine; the Client goes in a Hyper-V VM because
it is the only unit whose tests are destructive.

| | Runs on | Why there |
|---|---|---|
| **Engine** | WSL, on the laptop | Linux-only by design (asyncio/epoll). Standard library only, so WSL needs no venv. |
| **Administrator** | Windows, on the laptop | Needs Qt and a real display; nothing it does can damage the host. |
| **Client Agent** | Windows VM | The only unit that installs a boot-start service and blacks out a screen. Snapshots make that repeatable instead of one-shot. |

**This is the right assignment and the order does not need changing.** Each unit
is where its constraints put it, and the destructive one is the one that can be
rolled back. Two sanity checks on it:

- Putting the Admin in the VM and the Client on the host would be exactly
  backwards — it would move the only dangerous component onto your working
  machine.
- Running the Engine in its own Linux VM instead of WSL would work but buys
  nothing: it is the same Linux, and WSL is the documented setup.

**Networking is simpler than it looks here**, because the protocol is
client-initiated: the Client opens a persistent connection outward to the Engine
and the Engine never dials back. So the VM does not need to be reachable from
anywhere — it only needs to reach the host. A NAT'd Hyper-V **Default Switch**
is sufficient, and avoids the brief host network drop that creating an External
switch causes. Use External only if you also want the VM on the LAN for its own
sake.

What the VM still needs:

- **`networkingMode=mirrored`** in `%USERPROFILE%\.wslconfig` on the host, so
  the Engine inside WSL is reachable on the host's interfaces rather than only
  on WSL's NAT. Without it, use the port proxy in §0.2 instead.
- **An inbound firewall rule for TCP 5000** on the host.
- **The `certs/` directory copied in**, at the same relative path. Clients pin
  that exact certificate.
- Point the client at the host's Default Switch address:
  `python -m client --engine <host-vEthernet-ip>`.

Confirm with `Test-NetConnection <host-ip> -Port 5000` from inside the VM before
going further.

#### Three things a VM cannot tell you

Not blockers, but do not read a failure here as a code fault.

- **USB detection (T2.2) will not work in a Hyper-V VM.** `usb_monitor` counts a
  drive as removable only when `GetDriveTypeW` returns `DRIVE_REMOVABLE`. Hyper-V
  has no plain USB pass-through: an Enhanced Session redirected drive presents as
  remote, and an attached VHD or pass-through disk presents as fixed. Neither
  trips the check. **Run T2.1 and T2.2 on the host instead** — Part 2 is
  non-destructive, so that costs nothing.
- **Clock skew after a snapshot restore.** Lockout schedules are time-based and
  HMAC-protected, so a VM resumed with a stale clock can make a block window look
  expired or not yet started. Run `w32tm /resync` after every revert, before
  testing anything time-based.
- **`--once` will report far fewer processes** than the ~212 seen on the host,
  with fewer window titles. That is a quiet VM, not a broken collector.

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

So: use the host alone for Parts 1–3 and T5.1–T5.3, and bring in the VM for
Part 4 and T5.4 onward. Running the client under `--id` on the same box as the
Engine and Admin is not a compromise for any of the former — it is the same
socket, protocol and database either way.

### 0.1b What the second machine should be, and what it costs

The staged plan — one machine now, a second one later — is the right order:
everything cheap and safe comes first, and the second machine is only needed for
the tests that are neither.

Three ways to provide it.

| | Cost in money | Cost in time | Cost in risk |
|---|---|---|---|
| **Your own laptop, no second machine** | none | none | **high** — see below |
| **Windows VM on your laptop** | none | ~2h once | **very low** — snapshots |
| **Second physical laptop** | one laptop | ~1h once | low |

**Why "just use your own machine" is the expensive option.** The tests that
still need a second machine are exactly the destructive ones. `install_service`
registers a service that **starts on every boot** plus a Scheduled Task that
runs every 5 minutes as SYSTEM, and the thing they enforce blacks out the screen
and disables Task Manager. The design bounds the damage — blocks are capped at
2 hours, the overlay always restores the Task Manager policy on exit, and
`install_service.py --uninstall` removes both — but the whole point of C11 is
that this path has **never been run**, and it is being tested precisely because
it might not behave as designed. A fail-closed component failing in an
unexpected direction on your only working machine, days before a deadline, is
not a risk worth taking to save two hours.

**The VM is the best value, and you already have what it needs.**

- **Hypervisor: free.** You are on Windows 11 **Pro**, so Hyper-V is included —
  enable it under *Windows Features*. Prefer it over VirtualBox/VMware here for
  a specific reason: WSL2 already requires the Hyper-V platform, so a third-party
  hypervisor on the same host runs in a slower compatibility mode. Using Hyper-V
  avoids paying that twice.
- **Windows: free for this purpose.** Microsoft's Evaluation Center offers a
  time-limited Windows 11 Enterprise evaluation (90 days at the time of
  writing — check the current terms), which comfortably outlasts a project.
- **Disk: ~40–64 GB**, thin-provisioned so it only grows as used. Python plus
  PySide6 adds ~200 MB.
- **RAM: 4 GB** assigned while it runs. Comfortable if the host has 12 GB+.
- **CPU: 2 vCPU.**
- **Setup: ~2 hours**, most of it the ISO download and Windows install running
  unattended.

**The feature that actually matters is snapshots.** Take a checkpoint before
`install_service`, run the destructive tests, and revert in seconds — including
if the machine ends up genuinely locked. That turns C11 and T5.5–T5.8 from
"careful, one-shot" into something you can repeat as many times as it takes,
which is the difference between measuring a fail-open properly and guessing at
it.

**Networking.** Give the VM an **External** virtual switch so it gets a real LAN
address, and set `networkingMode=mirrored` in `.wslconfig` on the host so the
Engine inside WSL is reachable at the host's address. §0.2 then applies to the
VM exactly as written for Laptop B — including `Test-NetConnection` as the gate.

**When the physical laptop is still worth it.** A VM cannot tell you about real
Wi-Fi behaviour, roaming, a dock changing the adapter, or a genuinely separate
physical display. If you have a second laptop, use it for T5.1–T5.3 network
realism and the VM for the destructive T5.4 onward. If you have to pick one,
pick the VM — the destructive tests are the ones that cannot be done safely any
other way.

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

### 0.1c Do you need a network? No — and offline is better

**Nothing in this plan needs internet, Wi-Fi or a hotspot once the machines
exist.** Every link is internal to the laptop:

| Link | Carried by | Needs internet? |
|---|---|---|
| Admin → Engine | WSL2 loopback forwarding | no |
| VM → Engine | Hyper-V Default Switch (host-side NAT + DHCP) | no |
| VM clock | Hyper-V Integration Services, synced from the host | no |

The Default Switch runs its own DHCP and NAT on the host, so the VM gets an
address and can reach the host with the laptop in airplane mode. Disconnecting
the *virtual* adapter in the VM's settings is also how you test T5.3's reconnect
backoff — no real network to unplug.

**Run it offline by preference, not just when convenient.** Authentication is a
stub, so the only thing standing between the Engine and anyone on the same
network is the network itself. Offline turns `issues.md` C1 from a live exposure
into a theoretical one for the whole of Phase 5. Use the hotspot only for
one-time provisioning — the Windows ISO, Python, `pip install` inside the VM —
then take it off the network and leave it there.

One consequence: **do not use `networkingMode=mirrored` in this setup.** Mirrored
mode hands WSL the host's real interfaces, which is both the exposure above and
fragile with no interfaces to share. Use the port proxy in §0.2 instead — it
forwards from the host's own addresses, including the Default Switch one the VM
talks to, and works with the laptop entirely offline.

### 0.2 Reaching WSL from the VM (or from a second laptop)

*Skip this if `networkingMode=mirrored` in §0.1 already worked — check with
`Test-NetConnection` first.*

WSL2 sits behind a NAT inside the host. `localhost` forwarding is what lets
Windows-on-A reach it — but that does **not** extend to another machine. Left
alone, the VM cannot see the Engine at all.

Two ways to fix it. Try mirrored networking first; it is one line and removes
the problem instead of working around it.

**Option 1 — mirrored networking** (Windows 11 22H2+). In `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
```

Then `wsl --shutdown` and restart. WSL now shares the Windows network interface,
so the Engine is reachable at the host's address directly.

**Option 2 — port proxy.** From an **elevated** PowerShell on the host:

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

Either way, confirm from the VM before going further:

```powershell
Test-NetConnection <host-ip> -Port 5000
```

`TcpTestSucceeded : True` is the gate. If it is False, nothing in Part 5 will
work and the fault is here, not in the code.

### 0.3 Install

Host (Engine + Admin) and VM (client only):

```powershell
pip install -r requirements.txt -r requirements-admin.txt -r requirements-client.txt   # A
pip install -r requirements.txt -r requirements-client.txt                             # B
```

The Engine needs nothing installed in WSL — it is standard library only.

### 0.4 TLS

TLS is presence-based: once `certs/engine-cert.pem` exists, all three units use
it with no flag. Generate **once**, on the host:

```powershell
python -m scripts.generate_cert
```

Then copy the whole `certs/` directory into the VM at the same relative path.
Clients pin that exact certificate and verify against the fixed identity
`labmonitor-engine`, not the IP — so the host's address can change without
breaking anything, but a *regenerated* certificate breaks every client until
it is re-copied.

To take TLS out of the picture while diagnosing something else, `--no-tls` on
all three. Put it back before you call Phase 5 done.

- [ ] **T0.1** `Test-NetConnection` from B to A on 5000 succeeds
- [ ] **T0.2** `certs/` present on both machines, same files

---

## Part 1 — Engine, alone (host, WSL)

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

With TLS on, from the host's Windows side:

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

## Part 2 — Client Agent, alone (VM; T2.1–T2.2 on the host)

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

**Deferred — this is the one Part 2 test that is not standalone or safe.** It
needs a block set through the Admin (Part 5) and a reboot of the machine being
blocked, so run it on the second machine when you reach Part 5, not now.

Set a block through the Admin, then reboot the client machine while the
block is still open. The agent must re-read the schedule on boot and put the
overlay back **before** anything else. This is the single most important
behaviour in the client.

- [ ] **T2.5** block still enforced after reboot

---

## Part 3 — Administrator, alone (host, Windows)

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

## Part 4 — Helper windows (VM)

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

Engine running in WSL with `ENGINE_LOG_LEVEL=DEBUG`. In the VM:

```powershell
python -m client --engine <host-ip> -v
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

Disconnect the VM's network adapter (or stop the Engine) with the agent running.
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
# elevated prompt in the VM - take a snapshot first
python -m client.install_service
sc start LabMonitorAgent
```

Then set a block from the Admin and watch the VM's screen.

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
