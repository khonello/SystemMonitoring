# Phase 5 — manual per-system verification

Prove each unit works **on its own** before anything is integrated. Every test
here needs at most one component running, so a failure points at one component
rather than at "the system".

Commands are given in short form. `commands.md` is the reference for every flag
and what it does; this file says what to *run* and what you should *see*.

Work top to bottom. Record results in the table at the end.

| Part | What it covers | Machines | Runs unattended on your own laptop? |
|---|---|---|---|
| **0** | Setup: roles, networking, install, TLS | — | yes |
| **1** | **Engine alone** — config resolves, database is writable, it serves, TLS is genuinely enforced | one | yes |
| **2** | **Client alone** — collection works on this hardware, state paths resolve, one agent per id | one | yes |
| **3** | **Admin alone** — QML loads clean, config resolves, the window survives a failed connect | one | yes |
| **4** | Helper windows — dialog exit codes, overlay, Task Manager | VM | takes over the screen for the length of the test |
| **5** | The link — registration, telemetry, reconnect, and enforcement from a service | host + VM | installs a boot-start service (removable) |

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

  TLS does not help: encryption without authentication only means the
  attacker's session is private too.

  **The chosen setup answers this structurally.** An Internal switch has no
  route to any real network, so the Engine is unreachable from Wi-Fi by
  construction rather than by anyone remembering a rule (section 0.1). Under
  topology A it is a rule instead — bind the port proxy to the Default Switch
  address, never `0.0.0.0` (section 0.2) — which is one of the reasons topology
  A is the fallback rather than the plan.
- **Running by hand is not running as a service.** Everything below runs in your
  own login session. A service runs in session 0, which may behave differently
  for anything that draws on screen — that is exactly what T5.4 exists to check.

---

## Part 0 — Setup

### 0.0 The setup, and the fallback

**The plan is two VMs on an isolated switch** (section 0.1): the Engine in its
own Linux VM, the Client Agent in a Windows VM, both on a Hyper-V **Internal**
switch, and the Administrator on the host. Chosen because it is simpler to run,
not merely tidier — it has no port proxy, no NAT addresses that move when the
host reboots, and no way for the Engine to be reachable from a real network.

**Topology A** (section 0.1f) keeps the Engine in WSL and bridges into it with a
port proxy. It exists because it needs one less VM's worth of disk, which is the
binding constraint on a machine that does not have ~70 GB spare. Use it if that
is where you are; the results carry over unchanged.

Everything from Part 1 onward is identical under either. Only how the Client
reaches the Engine differs.

### 0.1 The setup — two VMs on an isolated switch

The Engine runs in its own Linux VM rather than under WSL, and both VMs sit on a
**Hyper-V Internal switch**:

```
  HOST: Admin  ──┐
                 │  vEthernet (LabMonitor)   192.168.100.1
                 ▼
        ┌────────────────────────────────┐
        │  Internal switch "LabMonitor"  │   no route to any real network
        └───┬────────────────────┬───────┘
            │ .2                 │ .3
      ┌─────────────┐    ┌─────────────┐
      │ Engine (Linux)│    │ Client (Win) │
      └─────────────┘    └─────────────┘
```

**Internal, not Private.** A Private switch connects the VMs to each other but
excludes the host — and the Admin runs on the host. Internal gives the host a
`vEthernet (LabMonitor)` adapter on the same subnet.

What this removes, which is the whole argument for it:

- **No port proxy.** Client and Engine share a subnet; the client connects
  straight to `192.168.100.2:5000`.
- **No moving addresses.** Static IPs on a switch with no DHCP, so nothing to
  re-read after a reboot — unlike both NAT ranges in topology A.
- **The C1 exposure becomes structural.** An Internal switch has no route to any
  real network, so an Engine that authenticates nobody is unreachable from Wi-Fi
  *by construction* rather than by remembering to bind the right address. That
  is the one that matters.
- **Snapshots for the Engine too**, so `monitoring.db` can be reverted to a known
  state between runs.

It is also closer to what would ship: a plain Linux VM is a deployment target,
where WSL2 is a development convenience nobody deploys to.

**Sizing, and why the Admin stays on the host.** On a 16 GB machine:

| | RAM |
|---|---|
| Host Windows + editor, browser, tooling | ~8 GB |
| Client VM (Windows 11) | 4 GB |
| Engine VM (Linux, **server install, no desktop**) | 1–2 GB |
| Admin, on the host | ~0.4 GB |
| | **~14 GB** |

That fits. Making the Admin a *third* VM does not — a Windows VM running Qt
wants another 4 GB and leaves the host nothing. Two VMs with the Admin on the
host is also the right split on its own terms: the Admin is the one component
that never needs reverting.

Two things that turn "fits" into "comfortable":

- **Install the Engine VM as a server, no desktop.** Ubuntu Server or a Debian
  netinst: ~1 GB RAM, ~5 GB disk. The Engine is headless and standard-library
  only, so a desktop would be pure overhead. `apt install python3` is the whole
  dependency list.
- **Dynamic Memory on the Windows client VM** (startup 4 GB, min 1 GB, max
  4 GB), so Hyper-V reclaims what it is not using. Install with a static 4 GB
  and switch afterwards — Windows Setup is happier that way.

**32 GB** removes the arithmetic entirely and leaves room for a second client VM
for multi-client testing (issues.md B21, D8). 16 GB is workable for the plan as
written.

**Setup order:**

1. Hyper-V Manager → *Virtual Switch Manager* → **New → Internal** → name it
   `LabMonitor`.
2. Give each VM a **second** adapter on *Default Switch* for provisioning
   internet, and remove it once each machine has its packages. That is what
   keeps the lab network clean without fighting an offline install.
3. Static addresses: host `192.168.100.1` on `vEthernet (LabMonitor)`, Engine
   `.2`, Client `.3`, `/24`, no gateway.
4. Engine: `python3 -m engine --check`, then serve. It binds `0.0.0.0`, which on
   this VM means only the isolated switch.
5. Client: `python -m client --engine 192.168.100.2`.
6. Admin: `python -m admin --engine 192.168.100.2`.
7. `certs/` copied to all three; the pinned identity `labmonitor-engine` means
   the addresses above never appear in the certificate.

Section 0.2 does not apply here — there is no NAT to bridge.

### 0.1f Topology A — the fallback, for a machine short on disk

One physical laptop, three environments. The Engine is Linux-only by design, so
WSL covers it without a second machine; the Client goes in a Hyper-V VM because
its tests are the ones you will want to repeat.

| | Runs on | Why there |
|---|---|---|
| **Engine** | WSL, on the laptop | Linux-only by design (asyncio/epoll). Standard library only, so WSL needs no venv. |
| **Administrator** | Windows, on the laptop | Needs Qt and a real display, and never needs reverting. |
| **Client Agent** | Windows VM | Its tests take over a screen and install a service, so snapshots let you repeat them freely rather than once per sitting. |

**This is the right assignment and the order does not need changing.** Each unit
is where its constraints put it, and the one you will rerun most is the one that
can be rolled back. Two sanity checks on it:

- Putting the Admin in the VM and the Client on the host would be backwards —
  the Admin is the one that never needs reverting.
- Running the Engine in its own Linux VM buys nothing *on this laptop*, where
  disk is the constraint — it is the same Linux either way. It buys plenty once
  disk is not: see topology B in section 0.1.

**Networking is simpler than it looks here**, because the protocol is
client-initiated: the Client opens a persistent connection outward to the Engine
and the Engine never dials back. So the VM does not need to be reachable from
anywhere — it only needs to reach the host. A NAT'd Hyper-V **Default Switch**
is sufficient, and avoids the brief host network drop that creating an External
switch causes. Use External only if you also want the VM on the LAN for its own
sake.

What the VM still needs:

- **A route from the VM into WSL.** WSL2 sits behind its own NAT inside the
  host, so the Engine is not reachable from the VM by default. Use the **port
  proxy** in section 0.2 — it forwards from the host's own addresses, including the
  Default Switch one the VM talks to. (`networkingMode=mirrored` also solves it,
  but do not use it here: it puts WSL on the host's *real* interfaces, which
  exposes an unauthenticated Engine to whatever network you are on, and is
  fragile offline. See section 0.1c.)
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
  trips the check. **Run T2.1 and T2.2 on the host instead** — they touch
  nothing, so that costs nothing.
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
reaches the Engine at `127.0.0.1:5000` with no setup at all, so section 0.2 below can be
skipped entirely.

What a single machine **cannot** test:

- **Anything the student would see.** The overlay would cover *your* screen and
  disable *your* Task Manager for the length of the block. T4.2–T4.6 and
  T5.5–T5.8 all want a machine you can hand over for a few minutes.
- **The link itself.** A real network hop, the WSL NAT crossing, TLS against a
  non-loopback address, and the reconnect/backoff behaviour of T5.3 are all
  loopback no-ops on one box.
- **Session 0 (C11).** Testing it means installing a boot-start service on your
  dev machine. Removable with `--uninstall`, but not something to leave behind.

So: use the host alone for Parts 1–3 and T5.1–T5.3, and bring in the VM for
Part 4 and T5.4 onward. Running the client under `--id` on the same box as the
Engine and Admin is not a compromise for any of the former — it is the same
socket, protocol and database either way.

### 0.1b What the second machine should be, and what it costs

The staged plan — one machine now, a second one later — is the right order:
everything that needs no second machine comes first.

| | Money | Time | What it gets you |
|---|---|---|---|
| **Your own laptop, nothing else** | none | none | works; ties up your desktop, one careful run at a time |
| **Windows VM on your laptop** | none | ~2h once | revert in seconds, repeat freely, desktop stays yours |
| **Second physical laptop** | a laptop | ~1h once | real network and a real second screen |

**Which tests this is about — everything else is ordinary.** Only **T4.2**
(running the overlay) and **T5.4–T5.8** (installing the service and setting a
block) take over a screen. Part 0 provisioning, Parts 1–3 and T5.1–T5.3 do
nothing of the sort; they start processes, print things and exit.

Nothing blocks a machine by itself. A block window exists only if an admin sends
a schedule command, or you launch `overlay_app` by hand. `store_schedule` has
exactly one caller — the handler for that admin command — and a client with no
schedule file reports `lockout active False`, because `load_schedule` returns
None rather than inventing anything. (The fail-closed synthetic block applies to
a schedule that *exists* and fails its integrity check, so it cannot appear on a
machine that was never given one.)

**And when those tests do run**, the overlay covers the primary display and
disables Task Manager for the length of the block. Blocks are capped at 2 hours,
the overlay closes itself at its end time, and the Task Manager policy is
restored on exit including on a crash. `install_service.py --uninstall` removes
the service and the Scheduled Task. So the ceiling is a screen you cannot use
for a couple of hours, not a machine to repair.

Which is why testing on one machine is a legitimate choice. It is just tedious:
each attempt costs you your desktop for the length of the block, so you end up
running those few tests once carefully rather than as many times as it takes to
understand what you are seeing. C11 is worth poking at repeatedly.

**The VM is the best value, and you already have what it needs.**

- **Hypervisor: free.** You are on Windows 11 **Pro**, so Hyper-V is included —
  enable it under *Windows Features*. Prefer it over VMware/VirtualBox here for
  a specific reason: WSL2 already requires the Hyper-V platform, so a
  third-party hypervisor on the same host runs through a compatibility layer
  and gives up some speed. Hyper-V avoids paying that twice.
- **Windows: free for this purpose.** A retail Windows 11 ISO installs and runs
  unactivated indefinitely — see section 0.1d.
- **Disk: 64 GB**, thin-provisioned so it only grows as used. That is Windows
  11's own minimum, not a comfort figure — Setup refuses less. Python plus
  PySide6 adds ~400 MB.
- **RAM: 4 GB** assigned while it runs. Comfortable if the host has 12 GB+.
- **CPU: 2 vCPU.**
- **Setup: ~2 hours**, most of it the Windows install running unattended.

**Snapshots are the actual reason.** Take a checkpoint before
`install_service`, run the tests, revert in seconds. That turns C11 and
T5.5–T5.8 from one careful attempt into something you can repeat until you
understand it, which is the difference between measuring the session-0 question
and guessing at it.

**Networking.** Default Switch and the section 0.2 port proxy, set out in section 0.1d and
section 0.2 — including `Test-NetConnection` as the gate. An External switch is only
worth it if you also want the VM on the LAN for its own sake.

**When the physical laptop is still worth it.** A VM cannot tell you about real
Wi-Fi behaviour, roaming, a dock changing the adapter, or a genuinely separate
physical display. If you have a second laptop, use it for T5.1–T5.3 network
realism and the VM for T5.4 onward. If you have to pick one, pick the VM: it is
free, and it is the one that lets you repeat things.

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
| Admin → Engine | the Internal switch (WSL loopback under topology A) | no |
| Client → Engine | the same Internal switch (Default Switch + proxy under A) | no |
| VM clocks | Hyper-V Integration Services, synced from the host | no |

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

Under the chosen setup none of this needs managing: the Internal switch carries
no route anywhere, so the Engine is off every real network whether the laptop is
online or not.

Under topology A it does need managing. **Do not use `networkingMode=mirrored`
there** — it hands WSL the host's real interfaces, which is both the exposure
above and fragile with no interfaces to share. Use the port proxy in section 0.2,
bound to the Default Switch address.

### 0.1d Building the VM

A retail **Win11 24H2 x64** ISO (~5.7 GB, multi-edition) is the right media.
Choose **Pro** at the edition prompt: Home would run the agent fine, but Pro
matches a managed lab machine and carries `gpedit.msc`, which is what T4.5 needs
to reproduce the group-policy conflict C10 describes.

**Activation is not needed for any of this.** Left unactivated, Windows 11 runs
indefinitely with cosmetic limits — a desktop watermark and locked
personalization settings. Services, Scheduled Tasks, session behaviour and
registry policy all work normally, and those are the entire subject of Phase 5.
Use a key if you have one through your institution; do not buy one for this.

**Hyper-V settings that Setup will refuse without:**

| Setting | Value | Why |
|---|---|---|
| Generation | **2** | Windows 11 requires UEFI. Cannot be changed after creation — a Gen 1 VM has no **Security** page at all and must be recreated |
| Security → Trusted Platform Module | **enabled** | Win11 requires TPM 2.0. A Gen 2 VM has a virtual one, but the creation wizard never offers it and it is **off by default**, so Setup stops with a generic "This PC can't run Windows 11" naming no requirement. Tick it at *VM → Settings → Security*, with the VM shut down — after the wizard, before first boot |
| Secure Boot | on, template *Microsoft Windows* | Win11 requirement |
| Memory | 4096 MB startup | Win11 minimum |
| Virtual processors | 2 | Win11 minimum |
| Disk | 64 GB dynamic VHDX | Win11 minimum |
| Network | **Default Switch** | NAT; internet during provisioning, nothing afterwards |

The networking step also offers *Not Connected* and a **WSL** switch. Not
Connected is the state you switch to at step 8, not the one to install with.
Leave the WSL switch alone despite the Engine living there — it is created and
reconfigured by WSL rather than by you, and Hyper-V Firewall rules apply to it;
Default Switch reaches the host just as well and stays put. The adapter can be
changed any time in *VM Settings → Network Adapter*.

Note the Default Switch's address range **changes when the host reboots**, so
re-read the host's `vEthernet (Default Switch)` address when you get to section 0.2
rather than recording it once.

**Leave the network connected until provisioning is finished.** Windows 11 24H2
pushes a Microsoft account and an internet connection through OOBE, and the
offline workarounds are a moving target — `oobe\BypassNRO.cmd` was removed in
recent builds, leaving `Shift+F10` → `start ms-cxh:localonly` as the current
local-account route. Fighting that buys nothing here. Install with the network
up, then take it down for good once the machine is provisioned.

**Provisioning, in order:**

1. Install Windows, complete OOBE.
2. Install **Python 3.10+** (the project pins `requires-python = ">=3.10"`).
   Tick *Add python.exe to PATH*.
3. Copy the repository in — Enhanced Session drive redirection is easiest.
4. `pip install -r requirements.txt -r requirements-client.txt`
   (the VM runs only the Client, so the Admin file is not needed).
5. `pip install -e .` — without it `from common.protocol import ...` will not
   resolve.
6. Copy `certs/` in at the same relative path.
7. `python -m client --check` — should resolve an id, report three MISSING
   bundles, and say `agent running False`.
8. **Leave the VM on Default Switch.** Do not disconnect the adapter: that link
   is how the client reaches the Engine, and Part 5 needs it. "Offline" means
   the *Engine* is not reachable from any real network, which section 0.2
   achieves by binding the proxy to the Default Switch address rather than by
   unplugging anything. (Disconnecting the adapter is still how T5.3 simulates
   network loss — temporarily, on purpose.)
9. **Checkpoint: "baseline"**, before anything is installed as a service.

Take a second checkpoint named **"pre-service"** immediately before T5.4's
`install_service`, and revert to it after each attempt. That is the whole reason
the VM is worth its two hours.

### 0.2 Reaching WSL from the VM — topology A only

Three environments, two NATs, and one link that needs building. What talks to
what:

```
             HOST LAPTOP
  ┌──────────────────────────────────────────┐
  │  Admin (Windows)                         │
  │      │                                   │
  │      │ 127.0.0.1:5000                    │
  │      │ WSL2 localhost forwarding         │
  │      ▼                                   │
  │  Engine (WSL)  ◄── port proxy ───┐       │
  │                                  │       │
  │        vEthernet (Default Switch)│       │
  └──────────────────┬───────────────┴───────┘
                     │  172.x.x.1:5000
                     │  Hyper-V Default Switch (NAT)
                     ▼
              ┌─────────────┐
              │ Client (VM) │
              └─────────────┘
```

- **Admin → Engine** needs no setup. Both are on the host, and WSL2 forwards
  `localhost`, so the Admin connects to `127.0.0.1:5000`. The Default Switch is
  not involved at all.
- **Client → Engine** is the link that needs building. The VM reaches the host
  on the Default Switch address, but the Engine is not on the Windows host — it
  is inside WSL, behind a second NAT. The port proxy below bridges the two.
- **Client → Admin never happens.** They never speak directly; every command and
  every telemetry message goes through the Engine. So there is nothing to
  configure between the VM and the Admin.
- The Default Switch also NATs the VM out to the internet through the host. Same
  adapter, different destination — useful during provisioning, irrelevant after.

WSL2 sits behind its own NAT inside the host. `localhost` forwarding is what
lets Windows-on-the-host reach it — and that does **not** extend to the VM. Left
alone, the VM cannot see the Engine at all.

**Use a port proxy, bound to the Default Switch address — not to `0.0.0.0`.**
From an **elevated** PowerShell on the host:

```powershell
$wsl  = (wsl -- hostname -I).Trim().Split()[0]
$host_ip = (Get-NetIPAddress -InterfaceAlias "vEthernet (Default Switch)" -AddressFamily IPv4).IPAddress

netsh interface portproxy add v4tov4 listenport=5000 listenaddress=$host_ip connectport=5000 connectaddress=$wsl
netsh advfirewall firewall add rule name="LabMonitor Engine" dir=in action=allow protocol=TCP localport=5000
```

`listenaddress` is what makes this safe rather than merely working. Bound to
`0.0.0.0` the proxy answers on *every* host interface, so an Engine that
authenticates nobody would be reachable from whatever Wi-Fi the laptop is on.
Bound to the Default Switch address it answers only on the virtual network
between the host and the VM — which is the only place it is needed, and is true
whether or not the laptop is online.

That is also why **`networkingMode=mirrored` is the wrong fix here** despite
being one line: it gives WSL the host's real interfaces, which is exactly the
exposure this avoids.

**Both NAT addresses change when the host reboots** — the WSL one and the
Default Switch one — so this needs redoing after a restart. To undo:

```powershell
netsh interface portproxy delete v4tov4 listenport=5000 listenaddress=$host_ip
netsh advfirewall firewall delete rule name="LabMonitor Engine"
```

Confirm from inside the VM before going further, using that same host address:

```powershell
Test-NetConnection <default-switch-ip> -Port 5000
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

## Part 1 — Engine, alone (its VM; or WSL under topology A)

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
`3` bad arguments — and `0` for `--help`, fixed in `issues.md` B26. Test the
first three.

- [ ] **T4.1** acknowledged→0, cancelled→1, timeout→2

### T4.2 — Overlay

This covers the whole screen and disables Task Manager until its end time, so
pick one a couple of minutes out.

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

## Part 5 — The link

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

**The one genuinely unknown result in this phase** — and the one that gates a real install rather than the defence, since a hand-run agent never enters session 0. Everything above runs in your login session. In
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

If T5.5 or T5.6 is No, enforcement does not reach the screen under a real
install. That does not stop a demo — run the agent by hand and the overlay
behaves normally — but it is worth knowing, and worth being able to answer if a
panel asks. See `issues.md` C11.

### T5.8 — Duplicate overlays from the watchdog *(new, `issues.md` C12)*

With the agent running and a block active, wait for a watchdog pass (~5 min) or
run one by hand:

```powershell
python -m client.watchdog --id <the agent's id>
```

This used to launch a second overlay: `overlay_running()` only saw overlays the
calling *process* had started. The overlay now holds a lock in `STATE_DIR`, so
every launcher sees it (`issues.md` B25). Check Task Manager — there should be
exactly **one** `overlay_app` / `labmonitor-overlay` process.

- [ ] **T5.8** number of overlay processes after a watchdog pass: ______ (expect 1)

---

## Gate: ready for Phase 6?

Integration should not start until:

- [ ] Every Part 1–4 box is ticked, or its failure is logged in `issues.md`
- [ ] T5.1, T5.2 and T5.3 pass
- [ ] T5.5 and T5.6 are answered — **not** left blank. They gate a real
      install rather than the demonstration, so a No here is a finding to state,
      not a reason to stop
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
