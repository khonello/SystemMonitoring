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

## 4. Get the repository into the VM — `LabRepo.iso`

### Why a disc

The `LabMonitor` switch has **no gateway and no route out**, which is the whole
point of it (see [The map](#the-map)). That rules out every ordinary way of
moving code:

| Not available | Why |
|---|---|
| `git clone` in the guest | No route to the internet — and `certs/` is gitignored, so a clone leaves that machine on plaintext ([§0.4](testing.md)) |
| A network share / `scp` | Nothing is listening, and the Engine guest has no desktop and no SSH configured until after step 8 |
| Copy-paste, drag-and-drop | Needs Enhanced Session, which needs RDP running *inside* the guest. Debian has no desktop; Windows has one only after OOBE |
| A USB stick | Hyper-V has no plain USB pass-through (same reason T2.2 moves to the host) |

A DVD image is the one transport **both** guests read natively with zero setup,
before any network or account exists. It is also read-only, so a guest cannot
mutate the source, and one image serves both machines.

### Build it

On the **host**, from an elevated shell:

```powershell
$stage = "$env:TEMP\labrepo"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue   # never merge into a stale stage
robocopy <repo> $stage /E /XD .venv __pycache__ .pytest_cache /NFL /NDL /NJH /NJS
& "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe" -m -u2 -lLABREPO $stage <drive>:\LabRepo.iso
```

`oscdimg.exe` ships with the **Windows ADK** (*Deployment Tools* feature). It is
the only external tool this procedure needs.

What each part is doing:

| Piece | Why |
|---|---|
| A staging copy | `oscdimg` images a directory as-is. Staging is where the exclusions happen |
| `/XD .venv` | Host-built Windows binaries pinned to the host's interpreter. Each guest builds its own venv in step 5 |
| `/XD __pycache__` | Bytecode compiled by the host's Python version — stale at best on a guest |
| `/XD .pytest_cache` | Scratch |
| `-m` | Ignore the default image size limit |
| `-u2` | Write **UDF**. ISO 9660 alone truncates and upper-cases names, which would mangle `lab_engine_setup.sh` and every QML file |
| `-lLABREPO` | Volume label. This is how you recognise the drive in the guest — no space after `-l` |
| *(no `-h`)* | `oscdimg` skips hidden files unless told otherwise, so **`.git` is not on the disc**. Deliberate: the guests get a working copy, not a repository, which is the copy-don't-clone rule enforced by construction |

**Verify before trusting it** — mount the image on the host and look:

```powershell
$m = Mount-DiskImage 'K:\LabRepo.iso' -PassThru | Get-Volume
Get-ChildItem "$($m.DriveLetter):\scripts"   # all four lab scripts must be here
Get-ChildItem "$($m.DriveLetter):\certs"     # two .pem files
Dismount-DiskImage -ImagePath 'K:\LabRepo.iso'
```

> **The disc is a snapshot, and it goes stale silently.** Re-cut it after *any*
> change to the code or the lab scripts. A stale disc does not announce itself:
> the guest reports "no such file" for a script that is sitting in your editor,
> or — worse — runs an older version of one that exists on both. This has
> already happened once, on 2026-08-12, when `LabRepo.iso` predated
> `lab_engine_setup.sh` and did not contain it at all.

### Attach it

A VM has **one** DVD drive, so attaching is a swap of the path rather than an
addition. The VM may be running or off:

```powershell
Set-VMDvdDrive -VMName LabClient -Path <drive>:\LabRepo.iso
```

`Get-VMDvdDrive -VMName LabClient` shows what is loaded now. If you ever need
both discs at once, `Add-VMDvdDrive` gives a second drive — not needed here,
since Windows is installed by the time this disc is wanted.

*In the VM* the disc appears as **`D:`**, labelled `LABREPO`:

```powershell
mkdir C:\SystemMonitoring
Copy-Item D:\* C:\SystemMonitoring -Recurse -Force
dir C:\SystemMonitoring\certs        # must show two .pem files
```

Copy off the disc rather than working from `D:` — the tree must be writable, and
step 5 installs into it. Files copied off a CD keep the **read-only** attribute;
`lab_client_setup.ps1` clears it.

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

The VM is created with **2 GB** for this, and step 9 cuts it back to the 512 MB
the Engine runs in. Do not install at 512 MB: Debian 13 drops into low-memory
mode and stops to ask which installer components to load.

### Screen by screen

Every answer below was walked on 2026-08-12/13. The ones in bold are the ones
that are not the default, or that cost time here.

**Enter is the right key everywhere except one page.** On every screen in this
table, Enter confirms the answer and moves on, exactly as you would expect —
which is precisely why tasksel catches people. There, Enter still means "accept
this page", but the page is a set of checkboxes rather than a single answer, so
Enter pressed on a ticked line confirms it instead of clearing it. **Space** is
the toggle. One page, one different key, and getting it wrong installs a full
desktop.

| Screen | Answer | Why |
|---|---|---|
| GRUB boot menu | **Install**, not *Graphical install* | The ncurses installer is lighter and behaves better over VMConnect. The GTK one buys nothing on a headless server |
| Language | English | Cosmetic |
| Location | **`other` → `Africa` → `Ghana`** | The first list is a short one of common choices, not the world. If your country is not on it, it is behind `other`, grouped by continent — it is not missing |
| Keyboard | US, or your layout | Cosmetic |
| Hostname | **`labengine`** | Cosmetic. Nothing on this switch resolves by name, and TLS verifies the fixed identity `labmonitor-engine` from the certificate, **not** the machine's hostname |
| Domain name | **blank** | There is no domain. An invented one only shows up later in prompts |
| Root password | anything you'll remember | `lab_engine_setup.sh` needs root |
| Full name for the new user | **`lab`** | Mirrors LabClient's account, so both guests share one credential |
| Username / password | `lab` / `lab` | As above |
| Partitioning method | **Guided — use entire disk** | Not LVM, not encrypted. Nothing here needs either, and a plain layout is one less thing to explain at the defence |
| Disk | the 8 GB virtual disk (the only one) | |
| Partitioning scheme | **All files in one partition** | |
| Write changes | **Finish partitioning** → **Yes** | First irreversible step. Everything before it lives in RAM, so a restart up to here is free |
| Scan extra installation media | **No** | One disc, and it has what the base system needs |
| Debian archive mirror — country | **`enter information manually`**, at the very top of the list | **Ghana is not in the list** — the list only holds countries that host a mirror. Picking a random neighbour is worse than the CDN |
| Mirror hostname / directory | **`deb.debian.org`** / `/debian` | Anycast CDN: it resolves to whichever mirror is genuinely nearest, from anywhere |
| HTTP proxy | blank | |
| Popularity contest | No | |
| **tasksel** (software selection) | **untick everything except *standard system utilities*.** SSH server optional | See below |
| GRUB bootloader | Yes, to the disk (`/dev/sda`) | |

This step needs the internet, which the VM has because it is still on the
**Default Switch**. It moves to the isolated `LabMonitor` switch at step 9.

### What tasksel is, and why every doc here shouts about it

`tasksel` — "task select" — is Debian's software-selection screen, a checkbox
list of package bundles: *Debian desktop environment*, *GNOME*, *web server*,
*print server*, *SSH server*, *standard system utilities*. **Space** toggles the
highlighted line; **Enter accepts the whole page as it stands**, wherever the
cursor is. That is not a warning in the abstract — it happened here on
2026-08-13. Enter was pressed *intending to untick* the highlighted desktop
entry, and instead confirmed the page with the desktop still selected; the next
screen was *Select and install software* retrieving 1882 files.

**The count is the tell.** A minimal install pulls a few hundred files. If that
progress line reads four digits, a desktop is going in — power off and redo the
install rather than trying to purge it afterwards. Nothing is lost at that
point: the repository does not reach this VM until step 8.

**Clearing the parent line is not enough.** *Debian desktop environment* has the
individual desktops indented beneath it — GNOME, Xfce, KDE Plasma, Cinnamon,
MATE, LXDE, LXQt — and **`... GNOME` is separately ticked by default**. It is
its own task: leaving it selected installs the desktop even with the parent
cleared. Check that line specifically before continuing; it is the one that
survives a careless pass.

Untick everything except **standard system utilities** — that bundle is what
gives a usable shell environment and brings `python3` with it, which is the
Engine's entire dependency list. A desktop would cost roughly a gigabyte of disk
and a working set this VM does not have at its runtime 512 MB, on a machine
whose only job is a headless asyncio process.

Then swap the Debian netinst out for the repo disc. LabEngine's single DVD drive
is holding the installer media until now, and Debian is on the VHDX by this
point, so nothing is lost:

```powershell
Set-VMDvdDrive -VMName LabEngine -Path <drive>:\LabRepo.iso
```

Leaving the netinst attached is not harmless — the VM boots DVD-first, so it
would walk back into the installer instead of the system you just built.

---

## 8. In the VM — provision the Engine

Linux does not mount discs by itself without a desktop, so mount it by hand. The
DVD drive is `/dev/sr0`; `-o ro` is explicit because the medium is read-only and
a read-write attempt just fails less clearly:

```sh
mount -o ro /dev/sr0 /mnt
ls /mnt/scripts                     # the four lab scripts; if they are absent, the disc is stale — re-cut it (step 4)
sh /mnt/scripts/lab_engine_setup.sh
```

Invoke it as `sh <path>`, not `./lab_engine_setup.sh`. The image is written by a
Windows tool, so the execute bit is not something to rely on, and the mount is
read-only so `chmod +x` cannot fix it in place. `sh` sidesteps the question.

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
| Debian installer says *Low memory mode* and asks which installer components to load | The Engine VM has 512 MB. Debian 13 drops into low-memory mode below roughly a gigabyte — 512 MB is the figure the Engine **runs** in, not one it installs in | Power off, `Set-VMMemory LabEngine -StartupBytes 2GB`, install, and let step 9 cut it back. The scripts now do both halves |
| Your country is not in the Debian mirror list | The list holds only countries that host a mirror. Ghana does not | Top of the list → **`enter information manually`** → `deb.debian.org`, `/debian`. The CDN beats any hand-picked neighbour |
| The Debian installer is sluggish, or its window is awkward over VMConnect | *Graphical install* was chosen at the GRUB menu | Reboot the VM and take plain **Install**. Nothing in this build needs the GTK installer |
| *Select and install software* is retrieving **1000+ files** | A desktop is being installed. Enter on the tasksel page **accepts what is ticked** — it does not toggle the highlighted line, and the desktop entries are ticked by default | Power off and redo the install. ~8 minutes, versus untangling a desktop from an 8 GB disk. A minimal install retrieves a few hundred files, not thousands — that count is the tell |
| Tempted to `apt purge` the desktop instead of reinstalling | A purged desktop task leaves residue, and `gdm` will have been enabled on a headless box | Reinstall. The VM holds nothing yet — the repo arrives at step 8, after this |
| OOBE loops back to "choose country or region" forever | Trimmed/debloated media — OOBE completion is never recorded | Use **stock** media. `issues.md` D9 |
| `OOBEMSAHELLO` / `OOBELOCALHELLO`, "Something went wrong" | Windows Hello components stripped from trimmed media | Click **Skip**. Or use stock media and it doesn't happen |
| "Type a different user name" for `lab` | The account already exists from a previous OOBE pass | Symptom of the loop above, not a naming problem |
| `pip` fails: *No such file or directory*, very long path | Long path support off, made worse by Store Python's deep prefix | Enable long paths, reboot. `lab_client_setup.ps1` checks this |
| Packages install "in the wrong place"; `sys.path` confusion | Store Python, or `pip.exe` resolving to a different install than `python` | python.org **all users**, plus a venv, plus always `python -m pip` |
| Service fails at T5.4 for no clear reason | Store Python is per-user and sandboxed; SYSTEM cannot reach it | python.org, **Install for all users** |
| `ping 192.168.100.1` times out from a guest | Host firewall — a new Internal switch is classified **Public** with no inbound ICMP rule | `setup_lab_vms.ps1` sets it Private and adds the rule. Nothing real depends on ICMP; the gate is TCP 5000 |
| Client connects but the Engine refuses it | `certs/` missing on one machine — it's gitignored, so a `git clone` on a guest gets none | **Copy** the working directory; never clone on a guest |
| `pip install -e .` fails oddly after copying from the ISO | Files off a CD keep the read-only attribute | `lab_client_setup.ps1` clears it, or do it by hand |
| A lab script is "not found" in the guest, but it is right there in your editor | `LabRepo.iso` predates the script. The disc is a snapshot, and nothing warns you | Re-cut the ISO (step 4) and verify it mounted on the host first. Bit us on 2026-08-12 |
| A script runs in the guest but behaves like an older version | Same cause, worse symptom — the file exists on the stale disc, just out of date | As above. Check the disc's copy against the repo, not just its presence |
| `mount /dev/sr0` says *no medium found* | No ISO in the VM's DVD drive, or it still holds the Debian netinst | `Get-VMDvdDrive -VMName LabEngine` on the host, then `Set-VMDvdDrive` to `LabRepo.iso` |
| LabEngine boots back into the Debian installer | The netinst is still attached and the VM boots DVD-first | Swap the DVD path to `LabRepo.iso` (step 7) |
| `./lab_engine_setup.sh` → *Permission denied* | No execute bit off a Windows-authored image, and the mount is read-only so `chmod` cannot help | `sh /mnt/scripts/lab_engine_setup.sh` |
| Filenames on the disc are truncated or upper-cased | Built without `-u2`, so it is ISO 9660 only | Rebuild with `-u2` |
| Both VMs show *Cannot connect to virtual machine configuration storage* | The lab drive reconnected after the Hyper-V service enumerated it — common with an external or secondary disk | `Restart-Service vmms -Force` with the VMs off. The configs are fine |
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

### Reading a guest's console without looking at it

```powershell
.\scripts\vm_console_shot.ps1 -VMName LabEngine
```

Saves a PNG of whatever is on the guest's screen, read from the host through
Hyper-V's WMI thumbnail API — no agent in the guest, no integration services, no
network, nothing typed. It works at a boot menu or mid-installer, which is
precisely when nothing else can see anything, and it makes the screen quotable
in a log or to someone helping remotely.

It is a diagnostic aid, not part of the procedure. It earned its way in here on
2026-08-13: the Debian installer had stopped on a list of kernel udebs that
reads exactly like expert mode, and the words that named the actual cause —
*Low memory mode* — were four small words in the top-left corner.
