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

  **The setup answers this structurally.** An Internal switch has no route to
  any real network, so the Engine is unreachable from Wi-Fi by construction
  rather than by anyone remembering a rule (section 0.1). That costs nothing to
  arrange — it is simply where the machines already are.
- **Running by hand is not running as a service.** Everything below runs in your
  own login session. A service runs in session 0, which may behave differently
  for anything that draws on screen — that is exactly what T5.4 exists to check.

---

## Part 0 — Setup

### 0.0 The setup

**Two VMs on an isolated switch**: the Engine in its own Linux VM, the Client
Agent in a Windows VM, both on a Hyper-V **Internal** switch, and the
Administrator on the host. Chosen because it is simpler to run, not merely
tidier — no port proxy, no NAT addresses that move when the host reboots, and no
way for the Engine to be reachable from a real network.

**There is one path through this document.** An earlier draft carried a second
topology that kept the Engine in WSL and bridged into it with a port proxy, as a
fallback for a machine short on disk. It was removed rather than kept, for two
reasons: two paths through a setup document is itself a source of mistakes, and
the port proxy is the one piece of that arrangement that can silently stop
working between sittings, because WSL2's address changes across host reboots.
The reasoning is in git history if it is ever wanted again.

**If you only want the steps, go to section 0.5** — Part 0 as a flat checklist,
with what is already done marked off. Everything between here and there is the
reasoning behind those steps.

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
  re-read after a reboot.
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
| Client VM (Windows 11, **tiny11** — section 0.1e) | 4 GB assigned, ~1.5 GB in use |
| Engine VM (Linux, **server install, no desktop**) | 1–2 GB |
| Admin, on the host | ~0.4 GB |
| | **~14 GB assigned, ~11 GB in use** |

That fits. Making the Admin a *third* VM does not — a Windows VM running Qt
wants another 4 GB and leaves the host nothing. Two VMs with the Admin on the
host is also the right split on its own terms: the Admin is the one component
that never needs reverting.

**On 8 GB it still fits**, and the row that decides it is the Engine VM, not the
Windows one. The Engine imports only the standard library, so a 512 MB
Debian-minimal guest runs it exactly as well as a 2 GB Ubuntu Server does:

| | RAM |
|---|---|
| Host Windows + Admin, editor and browser closed | ~3.5 GB |
| Client VM (Dynamic 1–3 GB, startup 2 — see below) | ~1.5–1.8 GB in use |
| Engine VM (Debian netinst, static) | 512 MB assigned, ~0.3 GB in use |
| | **~6 GB of 8** |

Two conditions turn that arithmetic into something that holds on the day:

- **Close the editor and browser before presenting.** That is 2–3 GB, and it is
  the entire margin.
- **`wsl --shutdown` first.** A WSL instance left running costs 0.5–1 GB doing
  nothing, and nothing in this setup uses it — the Engine has its own VM.

**What 8 GB does not fit is a second Windows client VM** — so run one agent per
VM. If the Admin's client list needs more than one row, start a second agent
*inside the same VM* under a different `--id`: separate `STATE_DIR` and separate
registration (issues.md B21), and only ever send a lockout to one of them. D8's
table is the boundary — telemetry, policy, reports and the audit trail all
simulate fine that way; enforcement does not.

Three things that turn "fits" into "comfortable":

- **Install the Engine VM as a server, no desktop** — and on 8 GB, a *minimal*
  one. **Debian netinst**, no tasksel selections: ~150–250 MB idle, ~4 GB on
  disk, and `apt install python3` is the whole dependency list. Ubuntu Server
  (~1 GB, ~5 GB) is the comfortable choice at 16 GB and pure overhead at 8.

  **Alpine was the first choice here and is the wrong trade on this laptop.** It
  is smaller again (~50–80 MB idle, ~2 GB disk), but `K:` has hundreds of GB
  free, so those 2 GB buy nothing — while a stripped Python build risks not
  carrying `sqlite3`, which the Engine needs for all persistence. Building the
  VM twice costs more than the disk it saves. Section 0.1f checks for it
  regardless.
- **Dynamic Memory on the Windows client VM.** Three fields: *Startup* is what
  Hyper-V commits at boot, *Minimum* the floor it can reclaim down to while the
  VM runs, *Maximum* the ceiling it can grow to under pressure. Use **startup
  2 GB, min 1 GB, max 3 GB** on an 8 GB host; 4 / 1 / 4 on 16 GB. Install with a
  **static 4 GB** and switch afterwards either way — Windows Setup is happier
  that way, and nothing else wants the RAM while it runs. On 8 GB also drop
  *Memory buffer* from its 20% default to 5–10%; that is headroom Hyper-V
  reserves above what the guest is actually using.
- **Build the client VM from a trimmed image** (section 0.1e). Worth doing, but
  note *why*: Dynamic Memory already reclaims most of what a debloat would save,
  so the real win is **disk**, which is the tighter of the two constraints on
  this laptop.

**32 GB** removes the arithmetic entirely and leaves room for a second client VM
for multi-client testing (issues.md B21, D8). 16 GB is workable for the plan as
written; 8 GB is workable with the two conditions above.

**Setup order:**

1. Hyper-V Manager → *Hyper-V Settings* → point **both** the virtual hard disk
   and the virtual machine path at `K:`. This is first because it is not
   optional: `C:` has under 5 GB free and cannot hold a guest at all.
2. Hyper-V Manager → *Virtual Switch Manager* → **New → Internal** → name it
   `LabMonitor`.
3. Give each VM a **second** adapter on *Default Switch* for provisioning
   internet, and remove it once each machine has its packages. That is what
   keeps the lab network clean without fighting an offline install.
4. Static addresses: host `192.168.100.1` on `vEthernet (LabMonitor)`, Engine
   `.2`, Client `.3`, `/24`, no gateway.
5. Engine: `python3 -m engine --check`, then serve. It binds `0.0.0.0`, which on
   this VM means only the isolated switch.
6. Client: `python -m client --engine 192.168.100.2`.
7. Admin: `python -m admin --engine 192.168.100.2`.
8. `certs/` is gitignored, so it reaches each VM only if you **copy** the
   working directory rather than `git clone` it (section 0.4). The pinned
   identity `labmonitor-engine` means the addresses above never appear in the
   certificate — which is why they can be changed without touching TLS.

**Why `192.168.100.x`, and why no gateway.** The `.100` is chosen to miss what
else is on the machine. `192.168.0.x` and `192.168.1.x` are what nearly every
home and ISP router hands out, `.2.x` and `.10.x` are common seconds, and both
the Hyper-V Default Switch and WSL2 sit somewhere in `172.16–31.x`. During
provisioning the host holds three adapters at once — Wi-Fi, Default Switch and
`vEthernet (LabMonitor)` — and two of them carrying the same prefix would give
the host two routes to one destination, resolved by interface metrics. That is
a bad thing to be debugging in the middle of Part 5, and `.100` makes it
practically impossible.

**No gateway is the part that does the work**, not the address. Without a
default route the guests can reach the host and each other and nothing else,
which is what makes `issues.md` C1 contained by construction rather than by
anyone remembering a rule.

Changing the range is a multi-place edit: `-HostIp` is a parameter of
`scripts/setup_lab_vms.ps1`, but `.2` and `.3` are typed into the guests by hand
and appear in the commands above. The certificate is the one thing that does not
care — see step 8.

### 0.1b Three things a VM cannot tell you

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

### 0.1c No network needed

**Nothing here needs internet, Wi-Fi or a hotspot once the machines exist.**
Every link is internal to the laptop:

| Link | Carried by | Needs internet? |
|---|---|---|
| Admin → Engine | the Internal switch | no |
| Client → Engine | the same Internal switch | no |
| VM clocks | Hyper-V Integration Services, synced from the host | no |

Use a hotspot only for one-time provisioning — the Windows ISO, Python, `pip
install` inside the VM — then move each VM onto `LabMonitor` and leave it there.
The Internal switch carries no route anywhere, so the Engine is off every real
network whether the laptop is online or not. That is also what keeps the stubbed
authentication (`issues.md` C1) from being a live exposure for the whole of
Phase 5 — it costs nothing extra, it is just where the machines already are.

Disconnecting the *virtual* adapter in the VM's settings is how T5.3's reconnect
backoff gets tested — no real network to unplug.

**The same isolation is why the code arrives on a disc.** A guest with no route
out cannot clone, cannot mount a share and has nothing listening for `scp`, and
Hyper-V offers no USB pass-through; copy-paste needs Enhanced Session, which
needs RDP running inside a guest that either has no desktop (Debian) or has not
finished OOBE yet (Windows). A DVD image is the one channel both guests read
natively before any network or account exists, and it is read-only, so a guest
cannot modify the source tree it was built from. `LAB-SETUP.md` step 4 is the
procedure; the reasoning is below.

**`LabRepo.iso` — what it is and what it costs to get wrong.** The repository is
staged to a temporary directory (dropping `.venv`, `__pycache__` and
`.pytest_cache`, all of which are host-specific and would be actively wrong on a
guest) and imaged with `oscdimg` from the Windows ADK. Two flags carry meaning:
`-u2` writes UDF, without which ISO 9660 truncates and upper-cases every name
long enough to matter; `-lLABREPO` sets the volume label the disc is identified
by inside the guest. Hidden files are skipped unless `-h` is passed, so **`.git`
never reaches the disc** — which enforces the copy-don't-clone rule (§0.4)
structurally rather than by discipline: what lands on each guest is a working
copy with `certs/` in it, not a repository that could be pulled or re-cloned.

The failure mode to respect is that **the disc is a snapshot and goes stale in
silence**. On 2026-08-12 the image on disk predated three of the four lab
scripts and contained none of them; the documented Engine command
(`sh /mnt/scripts/lab_engine_setup.sh`) would have failed with "no such file"
for a script sitting in the editor on the host. Re-cut the image after any
change to the code or the scripts, and mount it on the host to confirm before
attaching it — the stale-disc symptom points at the guest, which is the wrong
place to look.

Attaching is a **swap**, not an addition: each VM has one DVD drive, so
`Set-VMDvdDrive` replaces whatever is loaded (`Add-VMDvdDrive` would add a
second, which nothing here needs). For LabEngine that drive holds the Debian
netinst until the install finishes, and the swap afterwards is mandatory rather
than tidy — the VM boots DVD-first, so leaving the installer attached walks it
back into the installer instead of the system just built. Windows sees the disc
as `D:`; Debian has no automounter without a desktop and needs
`mount -o ro /dev/sr0 /mnt` by hand.

### 0.1d Building the VM

A retail **Win11 24H2 x64** ISO (~5.7 GB, multi-edition) is the right media.
Choose **Pro** at the edition prompt: Home would run the agent fine, but Pro
matches a managed lab machine and carries `gpedit.msc`, which is what T4.5 needs
to reproduce the group-policy conflict C10 describes.

**Install from that ISO directly.** Section 0.1e records an attempt to install
from trimmed media instead; it failed, and stock is what works. Stock media
carries no `autounattend.xml`, so OOBE asks you things the trimmed image
answered automatically — see step 1 below.

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

The networking step also offers *Not Connected* and a **WSL** switch. Ignore
both: Default Switch reaches the internet for provisioning and stays put, and
the WSL switch is created and reconfigured by WSL rather than by you. The
adapter can be changed any time in *VM Settings → Network Adapter*, which is
what step 8 does.

**Turn off automatic checkpoints.** Windows 11 Hyper-V enables them by default
on new VMs, so the machine starts running on a differencing disk the first time
it boots, which collides with the deliberate `baseline` and `pre-service`
checkpoints below. `scripts/setup_lab_vms.ps1` sets
`-AutomaticCheckpointsEnabled $false`; do it by hand if you build a VM any other
way. Clear a stray one with `Get-VMSnapshot -VMName LabClient | Remove-VMSnapshot`
— **never** by deleting the `.avhdx`, which breaks the disk chain and costs you
the VM.

#### Getting it to boot from the DVD at all

This cost an evening on 2026-08-12, and it will cost another on the Engine VM if
forgotten. Three things compound:

- **The media gives you about five seconds.** "Press any key to boot from CD or
  DVD" is baked into the Windows UEFI boot image, not added by Hyper-V, and it
  appears on every boot — including with a completely blank disk.
- **VMConnect renders nothing until it attaches.** Start the VM and *then* open
  its window, and the window opens mid-boot, after the prompt has expired. What
  you are looking at is already history, so every key you press does nothing.
  It reads exactly like a dead keyboard, and that is the trap.
- **A missed prompt falls through to PXE**, which has no boot server on the
  Default Switch and burns 30+ seconds before failing on to the empty disk.

**The order that works:**

1. VM off — `Stop-VM -Name LabClient -TurnOff -Force`
2. Drop PXE from the boot order, so a missed prompt costs seconds, not a minute:
   ```powershell
   $dvd = Get-VMDvdDrive -VMName LabClient
   $hd  = Get-VMHardDiskDrive -VMName LabClient
   Set-VMFirmware -VMName LabClient -BootOrder $dvd, $hd
   ```
3. **Open the console while the VM is still off** — double-click it in Hyper-V
   Manager. Click inside the black area so the window has focus.
4. Start it *from inside that window*: **Action → Start**.
5. Tap the spacebar continuously from the moment you click Start. Do not wait to
   see the prompt.

**Three things that look like the cause and are not.** *View → Enhanced Session*
being greyed out is normal — it tunnels input over RDP into the guest, so with
no guest OS installed it is unavailable rather than disabled, and it is not what
is eating your keystrokes. `Get-VM` reporting `Running` with a healthy uptime
while the screen ignores you is the symptom above, not a hung VM. And the boot
order is worth confirming once with
`Get-VMFirmware -VMName LabClient | Select-Object -ExpandProperty BootOrder`,
but if the DVD is already first, it is not your problem.

**Leave the network connected until provisioning is finished.** Windows 11 24H2
pushes a Microsoft account and an internet connection through OOBE, and the
offline workarounds are a moving target — `oobe\BypassNRO.cmd` was removed in
recent builds, leaving `Shift+F10` → `start ms-cxh:localonly` as the fallback
local-account route. Fighting that buys nothing here. Install with the network
up, then take it down for good once the machine is provisioned.

**Provisioning, in order:**

1. Install Windows. At the edition prompt choose **Windows 11 Pro**, and skip
   the product key — activation is not needed (above). Then complete OOBE by
   hand, since stock media has no unattend file. The local-account route on Pro
   is **"Set up for work or school" → Sign-in options → Domain join instead**,
   which despite the wording joins nothing; it is Microsoft's remaining
   sanctioned path to a local account. Use `lab` / `lab`. `Shift+F10` →
   `start ms-cxh:localonly` is the fallback if that path is missing.
2. Install **Python 3.10+** (the project pins `requires-python = ">=3.10"`).
   Tick *Add python.exe to PATH*.
3. Copy the repository in — Enhanced Session drive redirection is easiest.
   **Copy the working directory; do not `git clone`.** `certs/` is gitignored
   (section 0.4), and a clone leaves this machine on plaintext while the Engine
   uses TLS.
4. `pip install -r requirements.txt -r requirements-client.txt`
   (the VM runs only the Client, so the Admin file is not needed).
5. `pip install -e .` — without it `from common.protocol import ...` will not
   resolve.
6. **Defender is live on stock media**, unlike the trimmed image. It is a
   false-positive risk for the overlay (which disables Task Manager) and for
   Phase 8's PyInstaller-frozen exes. Add exclusions when it first bites rather
   than disabling it blind — a machine with Defender off is not the machine the
   agent ships to.
7. `python -m client --check` — should resolve an id, report three MISSING
   bundles, and say `agent running False`.
8. **Move the adapter to the `LabMonitor` switch** and set a static
   `192.168.100.3/24`, no gateway. Default Switch was only ever for
   provisioning. (Disconnecting the adapter is still how T5.3 simulates network
   loss — temporarily, on purpose.)
9. **Checkpoint: "baseline"**, before anything is installed as a service.

Take a second checkpoint named **"pre-service"** immediately before T5.4's
`install_service`, and revert to it after each attempt. That is the whole reason
the VM is worth its two hours.

### 0.1e The client VM's image — trimmed media was tried and abandoned

**Verdict: install from the stock retail ISO. The trimmed image does not
work.** `scripts/build_client_image.ps1` still builds and everything below still
describes what it does and why, kept as record rather than as instruction.
`scripts/setup_lab_vms.ps1` now defaults `-ClientIso` to the stock media.

**What went wrong**, 2026-08-12, with `K:\win11-labclient.iso`:

- **Windows installs, and then OOBE never finishes.** The desktop appears, the
  machine reboots itself, and it comes back to "choose country or region" —
  forever. Windows records OOBE completion under
  `HKLM\SYSTEM\Setup\Status\ChildCompletion`, and something the trim removed
  stops that from being written.
- **Both Windows Hello enrolment screens fail.** `OOBEMSAHELLO` on the
  Microsoft-account path, `OOBELOCALHELLO` on the local-account path, each
  showing "Something went wrong" with Skip and Try again. The components are
  gone, so Try again fails identically. Both must be skipped by hand.
- **The `autounattend.xml` account is created correctly.** On the second OOBE
  pass, entering `lab` is refused with "type a different user name" — proof the
  account already exists. The unattend file is not at fault; the trim is.

**The escape, recorded but untested.** From a `Shift+F10` prompt, setting
`HKLM\SYSTEM\Setup\Status\ChildCompletion\setup.exe` to `3` and
`HKLM\SYSTEM\Setup\OOBEInProgress` to `0`, then rebooting, should mark setup
complete and break the loop. Not tried here — the image was abandoned instead.

**Why abandoned rather than repaired.** The justification for trimming was disk
(table below), and disk stopped being the constraint: `K:` has ~625 GB free. An
image needing registry surgery to finish installing is a poor foundation for a
phase whose entire purpose is trusting what the machine does — every later
oddity would carry the question "is this our bug or the debloat?". Stock costs
~1 GB more idle RAM, which Dynamic Memory absorbs, and brings Defender back,
which exclusions handle.

**What would change this**: needing several client VMs on a genuinely small
disk. Then fix OOBE completion in the script rather than working around it —
the Appx keep-list is where to look, not the service list.

**The gate table further down no longer gates anything.** It existed to prove a
modified Windows was a sound test bed. Stock Windows needs no such proof.

---

Everything from here is the record of the attempt.

**Why debloat at all.** Not for RAM. Dynamic Memory (section 0.1) already returns
what the guest is not touching, and the gap it leaves is small:

| Image | Idle RAM in use | Disk used |
|---|---|---|
| Stock Win11 24H2 Pro | ~2.0–2.5 GB | ~30 GB |
| tiny11 (`tiny11maker.ps1`) | ~1.2–1.5 GB | ~12–18 GB |
| tiny11 Core (`tiny11Coremaker.ps1`) | ~0.8–1.0 GB | ~8 GB |

The win is **disk** — a trimmed client VM is most of what brings the two-VM plan
inside the space available on this laptop. A second win worth naming:
tiny11 lets Defender go quietly, and Defender is a live nuisance here — the
overlay disables Task Manager and Phase 8 ships PyInstaller-frozen helper exes,
both textbook false positives.

**Why Core is refused.** Core drops WinSxS, the servicing stack, Windows Update,
Defender and WinRE, and its own README says it cannot have features added
afterwards and is for development/testing only. It buys ~500 MB over tiny11 —
which Dynamic Memory largely gives us for free — and pays for it in exactly the
subsystems this phase exists to measure:

- **This VM is the measuring instrument for C11.** If the overlay does not appear
  in T5.4, a Core image makes "SYSTEM in session 0 cannot reach the desktop"
  indistinguishable from "the debloat removed something the graphics stack
  needed". That is the one question the VM was built to answer.
- **T4.5 needs `gpedit.msc`** to reproduce C10. Section 0.1d already chooses Pro
  for that reason; Core's MMC trimming puts it back in doubt.
- **Time sync.** Lockout schedules are HMAC-protected, time-based, 2-hour capped
  and fail closed. If Core's trimming touches the Hyper-V guest services
  (`vmicttimesync`), the guest clock drifts and T2.5 fails in a way that looks
  precisely like a bug in `client/lockout.py`.
- **PySide6 wants the MSVC 2015–2022 redistributable.** On a non-serviceable
  image "install a redistributable" stops being a certainty.

**Alternative worth knowing about: Win11 IoT Enterprise LTSC 2024.** An official
Microsoft SKU, free 90-day evaluation ISO, no Store/Edge/Copilot/consumer apps by
design, ~2 GB idle, fully serviceable, and it has `gpedit.msc`. Enterprise also
matches a managed lab machine more closely than Pro does, and "we used Microsoft's
LTSC lab SKU" is a better sentence at a defence than "we used a modified ISO".
Snapshots make the 90-day limit irrelevant. Either choice is defensible; tiny11
was picked because it starts from the ISO we already have.

**Why our own script rather than tiny11builder.** Same mechanism — DISM against
an offline image, plus offline registry edits — so this is not about tiny11builder
being unsafe. It is about the *removal list being ours*. tiny11builder decides
what a general-purpose debloated Windows should contain; we need a machine that
keeps a specific and slightly unusual set of things (Task Scheduler, MMC/gpedit,
`vmicttimesync`, the servicing stack, a re-enablable Defender) because each one
is named in a Phase 5 test. A list we wrote is a list we can defend line by line,
and when a test misbehaves the first question — "did the trim do this?" — has a
short, readable answer instead of someone else's several-hundred-line script.

`scripts/build_client_image.ps1` is that script, and **it is a keep-list, not a
remove-list**: every provisioned Appx package is removed unless it is named.
Kept, and nothing else — **Notepad, Snipping Tool, Windows Terminal**, the
frameworks those three load against, and a protected set that is the shell
itself (Start menu, File Explorer, OOBE, the credential and print dialogs).
Adding an app back is a deliberate edit; forgetting to strip one is not
possible.

Removed outright rather than merely quietened: Edge, EdgeUpdate, EdgeCore and
WebView2 (nothing here is a WebView2 host — the Admin and both helper windows
are Qt/QML), the Store, OneDrive, Recall, Copilot, Photos, Paint, Media Player,
Xbox, and 20-odd services for hardware or scenarios a lab VM does not have.
Defender is off by policy *and* by service; its binaries stay because it is a
protected component and pulling it offline breaks servicing, and `Start=2`
restores it if a test ever wants a realistic machine.

What the script refuses to touch is the more important list, and its header
carries it with reasons: Task Scheduler, `gpsvc`/MMC/`gpedit.msc`, the `vmic*`
integration services, DWM/`UxSms`, `TermService` (Enhanced Session is how the
repo gets copied in), and the servicing stack. Those are not bloat — each one is
named in a Phase 5 test, and removing them would make this VM unable to answer
the question it was built for.

#### What you actually type, and what each part means

The script takes four things. Nothing here is guesswork — each one is a path you
choose:

| Flag | Plain English | This machine |
|---|---|---|
| `-SourceIso` | **Input.** The Windows ISO you already have. Read only; never modified | `K:\Disc\Win11_24H2_English_x64.iso` |
| `-Scratch` | **Workbench.** A temporary folder the script creates, fills, and wipes at the start of every run. Do not put anything of your own here | `K:\labimage` |
| `-OutputIso` | **Result.** The new, trimmed ISO. This is the file you point the VM at | `K:\win11-labclient.iso` |
| `-DryRun` | **Look, don't touch.** Prints what it *would* remove and stops. Writes nothing | — |

Everything is on `K:` because **`C:` has ~7 GB free and `K:` has ~640 GB**. The
defaults in the script point at `C:` and will refuse to run here — that is the
error working as intended, not a fault. Hyper-V's default VM location is on `C:`
too, so set *Hyper-V Manager → Hyper-V Settings → Virtual Hard Disks / Virtual
Machines* to a `K:` path before creating the VM. Section 0.0's disk constraint,
showing up in practice rather than in principle.

#### Step 1 — the dry run (do this first)

Needs ~3 GB, a few minutes, and **no ADK**. It mounts the ISO's `install.wim`
read-only in place, so it skips both the media copy and the recompress. Open
**Windows PowerShell as Administrator**, then:

```powershell
cd C:\Users\Khonello\Documents\Developer\Languages\Multi\SystemMonitoring
Set-ExecutionPolicy Bypass -Scope Process
.\scripts\build_client_image.ps1 -SourceIso "K:\Disc\Win11_24H2_English_x64.iso" -Scratch K:\labimage -DryRun
```

It prints one line per package, capability and feature it found in the image:

| Line | Meaning |
|---|---|
| `KEEP` | on the keep-list — Notepad, Snipping Tool, Terminal, or a framework they need |
| `PROTECTED` | the shell itself; removing it would break the desktop |
| `REMOVE` | everything else |

**Read that output before building.** If something you want shows as `REMOVE`,
add it to `$KeepAppx` in the script; if something load-bearing shows as `REMOVE`,
add it to `$ProtectedAppx`. That is the whole point of the dry run — it is
cheaper to fix the list here than after a 45-minute build.

**What the dry run showed on our media** (`Win11_24H2_English_x64.iso`, Pro is
index 6), recorded because the next person will wonder whether this is normal:

- **44 of 47 provisioned packages removed.** The three kept are Notepad,
  Snipping Tool and Terminal — exactly the keep-list.
- **No `PROTECTED` lines at all, and that is expected.** The shell apps
  (`Client.CBS`, `StartMenuExperienceHost`, `FileExp`, `CloudExperienceHost`)
  are not *provisioned* packages; they live in `\Windows\SystemApps`, where
  `Remove-ProvisionedAppxPackage` cannot reach them. The shell is safe by
  construction. `$ProtectedAppx` stays as a guard rail because what Microsoft
  provisions has changed before.
- **No framework packages listed either.** VCLibs / UI.Xaml / WindowsAppRuntime
  ship as dependencies inside each app's bundle on 24H2 rather than as separate
  provisioned entries, so keeping the three apps keeps what they need.
- **Copilot and Widgets go as `MicrosoftWindows.Client.WebExperience`** — that
  one package is the host for both. There is no separate `Microsoft.Copilot`
  entry on this media.
- **199 of 425 capabilities removed**, almost all per-locale:
  `Language.Handwriting` (89), `Language.TextToSpeech` (49), `Language.OCR` (35),
  `Language.Speech` (17), plus nine singles. `Language.Basic` is untouched.
- **Optional features: `Recall` reports `absent`.** It is not in 24H2 RTM media —
  it arrives through Windows Update on Copilot+ hardware. It stays in
  `$DisableFeatures` anyway (one `absent` line, and it covers us if the media
  changes), and the `DisableAIDataAnalysis` / `AllowRecallEnablement` policy keys
  block it regardless. `Internet-Explorer-Optional-amd64` is likewise absent
  because IE is now the `Browser.InternetExplorer` *capability*, which is removed.
- **`MSRDC-Infrastructure` was dropped from the disable list** after the dry run
  surfaced it. It is Remote Desktop infrastructure, and Hyper-V Enhanced Session
  — which section 0.1d depends on to copy the repo into the VM — is RDP over
  VMBus. A few MB of saving is not worth putting a documented dependency in
  doubt. This is the dry run doing its job.

**Consequence worth accepting deliberately: the VM will have no image viewer.**
Photos and Edge are both removed, so a saved `.png` has no default handler.
Snipping Tool still displays what it just captured, which is what T4.x evidence
actually needs, and screenshots belong on the host with the results table
anyway — copy them out over Enhanced Session. If you would rather keep a viewer,
add `Microsoft.Windows.Photos` to `$KeepAppx`.

**Some policy writes are refused by the image, and that is expected.** A few
registry keys ship TrustedInstaller-owned with Administrators read-only, and
taking ownership of an offline hive needs a privilege PowerShell does not hold.
The build continues and **lists every refused write at the end of the registry
step** — read that list rather than assuming it is empty. A refusal is only
acceptable if something else reaches the same outcome.

On our 24H2 media, two were refused, and **both concern Widgets**:

| Refused | Covered by |
|---|---|
| `SOFTWARE\Policies\Microsoft\Dsh\AllowNewsAndInterests` | the Widgets host package `MicrosoftWindows.Client.WebExperience` is removed outright |
| `…\Explorer\Advanced\TaskbarDa` (default user) | the same package removal |

So the outcome holds — but note the honest gap. `TaskbarDa` was refused while
`HideFileExt`, `LaunchTo`, `ShowTaskViewButton` and `TaskbarMn` in the *same key*
succeeded, and that is **unexplained**: registry values do not carry their own
ACLs, so the usual TrustedInstaller story does not account for it. It is not
worth chasing, because the package removal already settles Widgets — but it does
mean the belt-and-braces here is thinner than intended, so **confirm it on the
running VM** rather than trusting the policy (gate table below).

Two other removals worth being sure about: `Microsoft.DesktopAppInstaller`
(winget — not needed, Python installs from its own `.exe`; `-KeepWinget` keeps
it) and `Microsoft.SecHealthUI` (the Windows Security window — consistent with
Defender being off, but note that re-enabling Defender later leaves it with no
UI).

#### Step 2 — install the ADK

Only needed for the real build. See the ADK note below.

#### Step 3 — the build

~25 GB of scratch, 30–60 minutes:

```powershell
.\scripts\build_client_image.ps1 -SourceIso "K:\Disc\Win11_24H2_English_x64.iso" -Scratch K:\labimage -OutputIso K:\win11-labclient.iso
```

Then create the Hyper-V VM per section 0.1d, but attach `K:\win11-labclient.iso`
as the DVD instead of the retail ISO. Everything else in 0.1d is unchanged.

#### The remaining flags

`-Edition` (defaults to `Windows 11 Pro`, for the `gpedit.msc` reason in
section 0.1d), `-KeepWinget`, `-RemoveFeaturePayload` for the last GB at the cost
of some serviceability, and `-SkipCompress` for a faster, larger build while
iterating on the list. `-AdminUser`/`-AdminPassword` name the local account the
injected `autounattend.xml` creates (default `lab`/`lab` — fine for an isolated
VM, and section 0.1c explains why that is not a real exposure).

**`commands.md` carries the full parameter table** — every flag, its type, its
default and what it does. This section is the walkthrough; that one is the
reference, and it is the one to update when a flag changes.

#### The one prerequisite: the Windows ADK

**Status when this was written: not installed on the host.** There is a
`C:\Program Files (x86)\Windows Kits\10` folder, but it holds only `Debuggers`,
`Catalogs` and `UnionMetadata` from some other SDK — no `Assessment and
Deployment Kit`. Check with:

```powershell
Test-Path "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
```

**What it is.** The **Windows ADK** (Assessment and Deployment Kit) is
Microsoft's free toolkit for building and deploying Windows images — standard IT
tooling, not something this project invented, and not a third-party download.

**Why we need it.** Exactly one file: `oscdimg.exe`. Producing a *bootable* ISO
is not zipping a folder; the image needs UEFI and BIOS boot records written into
specific places on the media, and no built-in Windows tool does that. `oscdimg`
is Microsoft's tool for it. It is the last step of the build and nothing else in
the project uses it.

**Which one.** ADK **10.1.26100.2454 (December 2024)** — the version that
supports Windows 11 24H2 and 25H2. Listed at
<https://learn.microsoft.com/windows-hardware/get-started/adk-install>, direct
download <https://go.microsoft.com/fwlink/?linkid=2289980>. The download is a
~2.2 MB `adksetup.exe` stub that then fetches only the features you select.

**Already downloaded to `K:\adksetup.exe`**, Authenticode signature checked and
valid (`CN=Microsoft Corporation`). Re-verify any fresh copy the same way:

```powershell
Get-AuthenticodeSignature K:\adksetup.exe | Select-Object Status, SignerCertificate
```

**Installing it.** From an **elevated** prompt:

```powershell
K:\adksetup.exe /quiet /features OptionId.DeploymentTools
```

`/features OptionId.DeploymentTools` is what keeps this to **~500 MB** — the
interactive installer preselects several GB (Windows PE, USMT, the Performance
Toolkit) and none of it is used here. It runs silently with no progress bar.
Confirm with the `Test-Path` above.

**`/installpath` does not work on this host, and the failure is silent.** With
`/quiet` the installer just returns to the prompt; the reason is only in
`%TEMP%\adk\*.log`:

```
ERROR: Cannot set the path to K:\ADK because another installation has already
been detected. Additional programs will have to be installed to the previously
selected install path C:\Program Files (x86)\Windows Kits\10\.
```

An existing `Windows Kits\10` (here: `Debuggers`, `Catalogs`, `UnionMetadata`
from another SDK) pins the install root, and `/installpath` is refused with exit
code `0x3e9`. Elevation is *not* the problem — check `WixBundleElevated = 1` in
the same log before assuming it is. Install to the default location; ~500 MB on
`C:` is affordable even at ~7 GB free (measured: 6.9 → 6.4 GB).

**`/quiet` returns immediately — that is "started", not "finished".** The
bundle detaches, so `Test-Path` run straight afterwards will say `False` and
mean nothing. The install takes a few minutes and is only observable in
`%TEMP%\adk\*.log` or by watching for `adksetup`/`msiexec` processes. Note this
is the *same* silent return that hid the `/installpath` failure above; the shell
gives you no way to tell the two apart, only the log does.

**When a non-default location is unavoidable**, pass the tool's path explicitly
rather than relying on the probe:

```powershell
-OscdimgPath "<somewhere>\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
```

With a default install the flag is unnecessary — the script finds `oscdimg.exe`
on its own.

**No reboot needed**, and nothing about the ADK changes how this machine
behaves; it is a folder of tools, not a service.

**One security note, recorded rather than acted on.** Microsoft flags
CVE-2026-25166 in **WSIM** (Windows System Image Manager), which ships inside
Deployment Tools, and recommends ADK patch KB5079391. We never run WSIM — the
`autounattend.xml` is generated by the script, not authored in WSIM — and the
vulnerability is in processing answer files, so it is not on our path. Apply the
patch anyway if the machine will keep the ADK around; it is a small download
from the ADK servicing page.

The script deliberately **will not download** `oscdimg.exe`, which is where it
differs from `tiny11maker.ps1`. A build tool fetched at runtime and then used to
assemble an operating system image is the one thing here worth being fussy
about.

**The dry run does not need any of this** — run the classification pass first,
and only install the ADK once the keep-list looks right.

**Fallback: `tiny11maker.ps1`.** If the script above fails on your media, clone
<https://github.com/ntdevlabs/tiny11builder>, mount the source ISO, and from an
elevated PowerShell 5.1 prompt run
`.\tiny11maker.ps1 -ISO <letter> -SCRATCH <letter>` (letters only, no colon),
choosing **Pro** at the SKU prompt; output is `tiny11.iso` beside the script.
Do **not** download someone's pre-built `tiny11.iso` — an unverifiable third
party's Windows is a poor choice of measuring instrument.

Either build changes one thing about section 0.1d's install: the injected
`autounattend.xml` bypasses the Microsoft-account requirement, so the
`ms-cxh:localonly` dance is not needed. Keep the 64 GB dynamic VHDX regardless —
it is thin-provisioned and only grows as used, so a smaller disk buys nothing and
costs headroom.

**Gate the image before trusting a single Phase 5 result.** A modified Windows is
only sound as a test bed if it is *shown* to be, so run this before recording
anything in the results table:

| Check | Passes if |
|---|---|
| `python -m client --check` | resolves an id, three MISSING bundles, `agent running False` |
| `python -m client --once` | one collection cycle prints, no collector errors |
| `python -m client --dialog-demo` equivalent (T4.1) | the QML dialog renders and returns its exit code |
| Overlay (T4.2) | renders full-screen, Task Manager policy applies *and* is restored |
| `schtasks /Create` then `/Query` | task registers and is listed |
| `install_service.py` (T5.4) | service registers and starts |
| `w32tm /query /status` | guest clock is tracking the host |
| Taskbar and Start | no Widgets, no Copilot, no Store — the two refused policy writes above are only covered if this holds |

**Keep a stock-Win11 checkpoint as the control.** If any Phase 5 test behaves
strangely, the question "is this our bug or the debloat?" is then answered by a
revert and a re-run rather than by argument.

### 0.1f Building the Engine VM

The small one. Well under an hour, and almost none of it is waiting.

**Media**: a **Debian netinst** for amd64 from `debian.org` — currently
`debian-13.x.x-amd64-netinst.iso`, about 755 MB. Section 0.1 records why this
rather than Alpine or Ubuntu Server. Older figures of ~630 MB were bookworm-era;
netinst images have carried non-free firmware by default since Debian 12, so a
larger file is expected rather than a sign of the wrong download.

**Take Debian 12 or 13, never 11.** Bullseye ships Python 3.9.2, under this
project's `requires-python = ">=3.10"`. Bookworm is 3.11.2, trixie 3.13.5.
Debian 11 was downloaded first here and thrown away for exactly this.

**The boot prompt catches this VM too** — see the boot subsection in section
0.1d. Open the console before starting the VM, not after.

**Hyper-V settings:**

| Setting | Value | Why |
|---|---|---|
| Generation | **2** | UEFI, matching the client VM. Cannot be changed after creation |
| Secure Boot | template ***Microsoft UEFI Certificate Authority***, or off | A Gen 2 VM defaults to the *Microsoft Windows* template, which **will not boot Debian** and fails without naming the reason. This is the setting that costs an evening |
| Memory | **2 GB static to install, 512 MB static to run** | 512 MB is what the Engine *runs* in; it is not enough to *install* in. Debian 13's installer drops into low-memory mode below roughly a gigabyte and stops to ask which udebs to load — a menu no normal install shows. `setup_lab_vms.ps1` creates the VM at 2 GB and `lab_host_finalize.ps1` cuts it back, the same shape as the client VM being created at 4 GB and converted to Dynamic Memory. Dynamic Memory is not used here: it needs the guest balloon driver and buys nothing at this size |
| Virtual processors | 1 | The Engine is single-threaded asyncio |
| Disk | 8 GB dynamic VHDX | ~4 GB used after install; dynamic, so it only grows into it |
| Network | **Default Switch** to provision, `LabMonitor` afterwards | Same pattern as the client VM |
| Automatic Stop Action | **Shut down** | Otherwise Hyper-V holds a `.bin` file the size of assigned RAM the whole time the VM runs |

**At the installer**: deselect everything in tasksel — no desktop, no print
server. Keep *standard system utilities*, and the SSH server if offered, since
`scp` is an easier way to get the repository in than the Hyper-V console.
`LAB-SETUP.md` step 7 lists every screen and the answer given to it; the four
that carry reasoning rather than taste are:

- **Take `Install`, not `Graphical install`, at the GRUB menu.** The ncurses
  installer is lighter and reads better over VMConnect, and the GTK one buys
  nothing on a machine that will never have a display server.
- **The hostname is cosmetic.** Nothing on the isolated switch resolves by name,
  and TLS verifies the fixed identity `labmonitor-engine` carried in the
  certificate rather than the machine's hostname (§0.4) — which is the whole
  reason the Engine's address can change without reissuing anything.
- **The mirror country list only holds countries that host a mirror**, so it
  will not contain yours in much of the world — Ghana is absent. Take
  `enter information manually` at the top of the list and use `deb.debian.org`,
  the anycast CDN, rather than picking a plausible-looking neighbour.
- **The user account is `lab`/`lab`,** matching LabClient, so one credential
  covers both guests on the day.

**Seeing what the guest is actually showing.** `scripts/vm_console_shot.ps1`
saves a PNG of the console straight from the host through Hyper-V's WMI
thumbnail API — no agent, no integration services, no network, nothing typed
into the guest — so it works at a boot menu or halfway through an installer,
which is when nothing else can. That is how the low-memory banner above was
found: the screen it produced looked like expert mode, and the four words naming
the real cause were in the top-left corner.

**Provisioning, in order:**

1. `sudo apt install python3` — the whole dependency list. The Engine imports
   only the standard library.
2. **`python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`.** Do this
   before anything else. The Engine owns all persistence through SQLite, and it
   is the one stdlib module a minimal image can be built without. Debian carries
   it; the check is here so a smaller image chosen later cannot fail quietly.
3. Copy the repository in — **copy the working directory, do not `git clone`**.
   `certs/` is gitignored, and a clone would leave this machine on plaintext
   while the client uses TLS (section 0.4).
4. Nothing to `pip install`. Run from the repo root so `common/` resolves.
5. `python3 -m engine --check` — T1.1 has what to expect.
6. Static `192.168.100.2/24`, no gateway, in `/etc/network/interfaces`. Remove
   the provisioning adapter.
7. **Checkpoint: "baseline"**, so `monitoring.db` can be put back to empty
   between runs.

### 0.3 Install

Three machines, three different installs:

| Machine | Install |
|---|---|
| Host (Admin) | `pip install -r requirements.txt -r requirements-admin.txt`, then `pip install -e .` |
| Client VM | `pip install -r requirements.txt -r requirements-client.txt`, then `pip install -e .` |
| Engine VM | **nothing** — standard library only. Run `python3 -m engine` from the repo root so `common/` resolves. |

`pip install -e .` is what makes `from common.protocol import ...` resolve on
the two Windows machines.

### 0.4 TLS — generated already, but it does not travel by itself

**`certs/` already exists on the host** and does not need regenerating. TLS is
presence-based: once `certs/engine-cert.pem` is there, all three units use it
with no flag.

**`certs/` is gitignored** (`.gitignore:44`, alongside `*.pem` and `*.key`), so
it is **not** in the repository. That makes how you move the code onto each VM
the thing that decides whether TLS works:

| Getting the code onto a VM | Result |
|---|---|
| Copy the working directory (drive redirection, `scp`) | `certs/` comes along. Correct |
| `git clone` on the guest | **No `certs/`.** That machine silently runs plaintext |

A half-configured lab is the bad case: the Engine finds a certificate and
enables TLS, the client does not and connects in plaintext, and the Engine
refuses it. The refusal is logged but does not name the cause. **Copy, don't
clone** — and if you do clone, copy `certs/` in afterwards by hand.

Two more things that only matter if something goes wrong:

- **Do not regenerate the certificate.** `python -m scripts.generate_cert` would
  invalidate every client until the new `certs/` is re-copied everywhere.
  Clients pin that exact file and verify against the fixed identity
  `labmonitor-engine`, not the IP, so addresses can change freely — a new
  certificate cannot.
- **If you need TLS out of the way** while diagnosing something else, `--no-tls`
  on all three. All three, or the Engine refuses the client and the reason is
  not obvious. Put it back before calling Phase 5 done.

- [ ] **T0.1** `Test-NetConnection 192.168.100.2 -Port 5000` from the client VM
      returns `TcpTestSucceeded : True`
- [ ] **T0.2** `certs/` present on all three, same files

### 0.5 The runbook, and the four scripts

**[`LAB-SETUP.md`](LAB-SETUP.md) is the procedure** — ten numbered steps that
build both VMs from nothing on any Windows 11 Pro machine, plus a symptom-first
pitfalls table. Everything above in Part 0 is the *reasoning*; that page is what
you follow with your hands.

It is deliberately machine-agnostic. The lab is built once on a dev box and
again on the presentation machine, which has a different disk layout, so no
drive letter appears in any script: `setup_lab_vms.ps1` picks the fixed drive
with the most free space and finds both ISOs by pattern.

| Script | Runs on | When |
|---|---|---|
| `scripts/setup_lab_vms.ps1` | host | once, before anything — storage, switch, host address and firewall, both VMs |
| `scripts/lab_client_setup.ps1` | inside LabClient | after Windows and Python — venv, packages, Defender exclusions, optional trim, `--check`, then `-SetNetwork` last |
| `scripts/lab_engine_setup.sh` | inside LabEngine | after Debian — `python3`, the `sqlite3` gate, the repo, the static address, `--check` |
| `scripts/lab_host_finalize.ps1` | host | per VM, with the VM off — Dynamic Memory, checkpoint policy, the `LabMonitor` replug, the `baseline` checkpoint |

All four are idempotent and take `-DryRun` (`DRY_RUN=1` for the shell one).
Re-running after fixing one thing is the intended way to use them, not a
recovery path.

**The scripts enforce what this document only explains.** Each refusal exists
because the failure it prevents is silent or misleading: Store Python is refused
because SYSTEM cannot reach it and the symptom surfaces at T5.4; long paths are
checked because pip's error names a file, not a limit; a missing `certs/` is
fatal because presence-based TLS would otherwise leave one machine on plaintext
and the Engine's refusal does not name the cause; Debian 11 is rejected at the
ISO rather than after an install, because its Python 3.9 is under the floor.

---

## Part 1 — Engine, alone (its VM)

Nothing else running for any of this.

### T1.1 — Configuration and database

On the Engine VM, from the repo root:

```bash
python3 -m engine --check
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
ENGINE_LOG_LEVEL=DEBUG python3 -m engine
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

Engine VM running with `ENGINE_LOG_LEVEL=DEBUG`. In the client VM:

```powershell
python -m client --engine 192.168.100.2 -v
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
