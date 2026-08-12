# Lab setup — build the two VMs from scratch

Straightforward steps to reproduce the Phase 5 lab on any Windows 11 Pro
machine. Follow it top to bottom.

**Every PowerShell command here needs an elevated shell** (right-click
PowerShell → *Run as administrator*). Commands marked *in the VM* run inside the
guest; everything else runs on the host.

Deeper reasoning lives in [`testing.md`](testing.md) sections 0.0–0.5. This page
is the procedure. If something goes wrong, jump to [Pitfalls](#pitfalls) — every
entry there cost real hours at least once.

---

## Before you start

| Need | Notes |
|---|---|
| Windows 11 **Pro** host | Home has no Hyper-V. `gpedit.msc` is needed by T4.5 |
| Hyper-V enabled | *Windows Features → Hyper-V* → reboot |
| ~90 GB free on some drive | Any drive. The scripts find it — no drive letter is hardcoded |
| **Windows 11 24H2 x64 ISO** | Retail/stock. Drop it on that drive |
| **Debian 12 or 13 netinst ISO** | [cdimage.debian.org](https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/) — **not 11**, it ships Python 3.9 |
| This repository, on the host | Working copy, not a fresh clone — `certs/` is gitignored |

If `certs/` is missing on the host, generate it once:

```powershell
python -m scripts.generate_cert
```

---

## 1. Host — create both VMs

```powershell
cd <repo>
.\scripts\setup_lab_vms.ps1 -DryRun     # read what it plans to do
.\scripts\setup_lab_vms.ps1
```

Picks a drive, creates `<drive>\LabMonitor\{VMs,VHDs}`, points Hyper-V there,
creates the `LabMonitor` internal switch, gives the host `192.168.100.1`, opens
ICMP on that switch, and creates **LabClient** and **LabEngine** with the
firmware settings that cannot be changed later.

Finds both ISOs by pattern. Pass `-ClientIso` / `-EngineIso` / `-LabRoot` to
override. If the Debian ISO is missing it builds LabClient and skips LabEngine —
re-run later to pick it up.

---

## 2. Install Windows in LabClient

**Order matters.** Do not start the VM first.

1. In Hyper-V Manager, **double-click `LabClient`** to open its console while it
   is still off
2. Click inside the black window so it has focus
3. **Action → Start**
4. **Tap the spacebar continuously** from that moment

Then in Setup:

| Screen | Answer |
|---|---|
| Product key | *I don't have a product key* |
| Edition | **Windows 11 Pro** |
| Installation type | **Custom: Install Windows only** |
| Disk | `Drive 0 Unallocated Space` → Next |

At OOBE, stock media demands a Microsoft account. The way past it:

> **Set up for work or school** → **Sign-in options** → **Domain join instead**

Then create user **`lab`**, password **`lab`**. Skip any PIN offer.

---

## 3. In the VM — install Python

Download Python **3.12** from [python.org](https://www.python.org/downloads/)
(not the Microsoft Store), run it, choose **Customize installation**:

- ☑ Add python.exe to PATH
- ☑ **Install Python for all users**
- Location: **`C:\Python312`**
- Final screen: click **Disable path length limit**

Reboot, then confirm:

```powershell
where.exe python        # C:\Python312\python.exe, no WindowsApps above it
python -V               # 3.12.x
```

---

## 4. Get the repository into the VM

On the **host**, build a disc from your working copy and attach it:

```powershell
$stage = "$env:TEMP\labrepo"
robocopy <repo> $stage /E /XD .venv __pycache__ .pytest_cache /NFL /NDL /NJH /NJS
& "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe" -m -u2 -lLABREPO $stage <drive>:\LabRepo.iso
Set-VMDvdDrive -VMName LabClient -Path <drive>:\LabRepo.iso
```

*In the VM:*

```powershell
mkdir C:\SystemMonitoring
Copy-Item D:\* C:\SystemMonitoring -Recurse -Force
dir C:\SystemMonitoring\certs        # must show two .pem files
```

The same ISO is reused for the Engine VM in step 7, so this is not wasted work.

---

## 5. In the VM — provision the client

```powershell
cd C:\SystemMonitoring
.\scripts\lab_client_setup.ps1 -DryRun
.\scripts\lab_client_setup.ps1 -Trim
```

Checks Python, creates the venv, installs the packages, adds Defender
exclusions, optionally trims services and Appx, then runs `client --check`.

**Expected:** an id resolved, **three MISSING bundles**, `agent running False`.
Missing bundles are correct — packaging is Phase 8.

Then take the network down, last, because it removes internet:

```powershell
.\scripts\lab_client_setup.ps1 -SetNetwork
```

Shut the VM down when it finishes.

---

## 6. Host — finish the client VM

```powershell
.\scripts\lab_host_finalize.ps1 -VMName LabClient
```

Dynamic Memory (2 / 1 / 3 GB), automatic checkpoints off, the `LabMonitor`
replug, and the **baseline** checkpoint.

---

## 7. Install Debian in LabEngine

Same console rule as step 2: **console open first, then Action → Start.**

At the installer, **deselect everything in tasksel** — no desktop, no print
server. Keep *standard system utilities*. Set a root password you'll remember.

Then attach the repo disc:

```powershell
Set-VMDvdDrive -VMName LabEngine -Path <drive>:\LabRepo.iso
```

---

## 8. In the VM — provision the Engine

```sh
mount -o ro /dev/sr0 /mnt
sh /mnt/scripts/lab_engine_setup.sh
```

Installs `python3`, verifies `sqlite3`, copies the repo to `/opt/SystemMonitoring`,
sets `192.168.100.2`, and runs `engine --check`.

**Expected:** transport says **TLS** with a certificate path, authentication
does **not** say BYPASSED, then `Database ready.` and exit 0.

Then `poweroff`.

---

## 9. Host — finish the Engine VM

```powershell
.\scripts\lab_host_finalize.ps1 -VMName LabEngine
```

---

## 10. The gate

Start both VMs. On the Engine:

```sh
cd /opt/SystemMonitoring && ENGINE_LOG_LEVEL=DEBUG python3 -m engine
```

*In the client VM:*

```powershell
Test-NetConnection 192.168.100.2 -Port 5000
```

**`TcpTestSucceeded : True`.** Nothing in Part 1 starts until this passes.

The Administrator runs on the host:

```powershell
.\.venv\Scripts\python.exe -m admin --engine 192.168.100.2
```

You're now at Part 1 of [`testing.md`](testing.md).

---

## The map

```
HOST                     LabClient (Windows)      LabEngine (Debian)
Admin                    Client Agent             Engine
192.168.100.1            192.168.100.3            192.168.100.2
        └──────────── LabMonitor internal switch ────────────┘
                     no gateway, no route out
```

No gateway anywhere is deliberate: the guests reach the host and each other and
nothing else, which keeps the stubbed authentication (`issues.md` C1) off every
real network by construction rather than by a firewall rule.

---

## Pitfalls

Every one of these has bitten. Symptom first, since that's what you'll have.

| Symptom | Cause | Fix |
|---|---|---|
| Keyboard does nothing at the boot prompt; VM falls through to PXE or "boot failed" | VMConnect renders only once attached, so opening the window after starting the VM means the 5-second prompt already expired | Console open **first**, click inside, then *Action → Start*, tapping space throughout |
| *View → Enhanced Session* greyed out | Normal with no guest OS — it needs RDP inside the guest | Not your problem. Ignore it |
| `Get-VM` says `Running` but nothing responds | Same as the first row | As above |
| Windows Setup refuses: "This PC can't run Windows 11" | TPM off. Gen 2 VMs have a virtual one but it is off by default and the wizard never offers it | `setup_lab_vms.ps1` enables it. By hand: *Settings → Security → Enable TPM*, VM off |
| Debian won't boot at all | Secure Boot template defaults to *MicrosoftWindows* | Template must be **MicrosoftUEFICertificateAuthority**, or off |
| OOBE loops back to "choose country or region" forever | Trimmed/debloated media — OOBE completion is never recorded | Use **stock** media. `issues.md` D9 |
| `OOBEMSAHELLO` / `OOBELOCALHELLO`, "Something went wrong" | Windows Hello components stripped from trimmed media | Click **Skip**. Or use stock media and it doesn't happen |
| "Type a different user name" for `lab` | The account already exists from a previous OOBE pass | Symptom of the loop above, not a naming problem |
| `pip` fails: *No such file or directory*, very long path | Long path support off, made worse by Store Python's deep prefix | Enable long paths, reboot. `lab_client_setup.ps1` checks this |
| Packages install "in the wrong place"; `sys.path` confusion | Store Python, or `pip.exe` resolving to a different install than `python` | python.org **all users**, plus a venv, plus always `python -m pip` |
| Service fails at T5.4 for no clear reason | Store Python is per-user and sandboxed; SYSTEM cannot reach it | python.org, **Install for all users** |
| `ping 192.168.100.1` times out from a guest | Host firewall — a new Internal switch is classified **Public** with no inbound ICMP rule | `setup_lab_vms.ps1` sets it Private and adds the rule. Nothing real depends on ICMP; the gate is TCP 5000 |
| Client connects but the Engine refuses it | `certs/` missing on one machine — it's gitignored, so a `git clone` on a guest gets none | **Copy** the working directory; never clone on a guest |
| `pip install -e .` fails oddly after copying from the ISO | Files off a CD keep the read-only attribute | `lab_client_setup.ps1` clears it, or do it by hand |
| A stray `.avhdx` appears; checkpoints behave strangely | Hyper-V takes an **automatic checkpoint** on first start by default | `Set-VM -AutomaticCheckpointsEnabled $false`. Remove strays with `Remove-VMSnapshot` — **never** by deleting the `.avhdx` |
| Time-based lockout tests behave impossibly after a revert | Guest clock is stale; lockout windows are time-based and HMAC-protected | `w32tm /resync` in the guest after **every** revert |
| USB detection (T2.2) never fires in the VM | Hyper-V has no plain USB pass-through | Run T2.1 and T2.2 on the host instead |
| VM creation fails or fills the system drive | Hyper-V's default storage path is on `C:` | `setup_lab_vms.ps1` repoints it. This is not optional |

---

## The scripts

| Script | Where | When |
|---|---|---|
| `scripts/setup_lab_vms.ps1` | host | Step 1 — once, before anything |
| `scripts/lab_client_setup.ps1` | in LabClient | Step 5 — after Windows and Python |
| `scripts/lab_host_finalize.ps1` | host | Steps 6 and 9 — per VM, VM off |
| `scripts/lab_engine_setup.sh` | in LabEngine | Step 8 — after Debian |

All four are **idempotent** and take `-DryRun` (`DRY_RUN=1` for the shell one).
Re-running after fixing one thing is safe and is the intended way to use them.

`scripts/build_client_image.ps1` is **not** part of this procedure — see
`issues.md` D9.
