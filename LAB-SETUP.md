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

On the **host**, from an elevated shell — one command, which also swaps the disc
into the VM and checks its own work:

```powershell
.\scripts\build_repo_iso.ps1 -AttachTo LabEngine
```

Omit `-AttachTo` to build only; pass `LabEngine,LabClient` for both. `-DryRun`
prints the plan. It finds the lab drive itself, so no drive letter appears here.

`oscdimg.exe`, which does the actual imaging, ships with the **Windows ADK**
(*Deployment Tools* feature). It is the only external tool this procedure needs.

The script exists because this is five commands with two silent failure modes,
both of which cost an evening on 2026-08-13 — a running VM holds the image, so
overwriting it fails outright, and `Set-VMDvdDrive` can leave the drive **empty**
while reporting a path, handing the guest the *previous* disc. So it ejects
before copying, verifies `DvdMediaType` rather than the path, retries once, and
finally mounts the finished image to confirm the scripts are physically on it
and that `lab_engine_setup.sh` hashes equal to the working copy. It refuses to
build at all without `certs/`.

**One thing it cannot do: unmount the disc inside a running guest.** Linux holds
the medium while it is mounted, so `umount /mnt` in the guest comes first. The
script detects the resulting lock and says so instead of failing with a bare IO
error.

What it does under the hood, and why:

| Piece | Why |
|---|---|
| A staging copy | `oscdimg` images a directory as-is. Staging is where the exclusions happen |
| `/XD .venv` | Host-built Windows binaries pinned to the host's interpreter. Each guest builds its own venv in step 5 |
| `/XD __pycache__` | Bytecode compiled by the host's Python version — stale at best on a guest |
| `/XD .pytest_cache` | Scratch |
| `/XF monitoring.db *.db *.db-journal` | **The dev box's database.** Gitignored, so a clone never sees it — but this disc is a *copy of the working directory*, which is exactly the mechanism that carries `certs/` across, and it carries every other ignored file too. Left in, the lab Engine boots with the host's old test data: on 2026-08-13 a phantom client `lab1-pc-01` at `127.0.0.1` appeared in the Admin's sidebar as a machine that does not exist |
| `/XF .coverage` | Same reasoning, less harmful |
| `-m` | Ignore the default image size limit |
| `-u2` | Write **UDF**. ISO 9660 alone truncates and upper-cases names, which would mangle `lab_engine_setup.sh` and every QML file |
| `-lLABREPO` | Volume label. This is how you recognise the drive in the guest — no space after `-l` |
| *(no `-h`)* | `oscdimg` skips hidden files unless told otherwise, so **`.git` is not on the disc**. Deliberate: the guests get a working copy, not a repository, which is the copy-don't-clone rule enforced by construction |

> **The disc is a snapshot, and it goes stale silently.** Re-cut it after *any*
> change to the code or the lab scripts. A stale disc does not announce itself:
> the guest reports "no such file" for a script that is sitting in your editor,
> or — worse — runs an older version of one that exists on both. This has
> already happened twice: on 2026-08-12 `LabRepo.iso` predated
> `lab_engine_setup.sh` and did not contain it at all, and on 2026-08-13 a
> "fixed" script was tested against a disc that had never received the fix. The
> build script's final step exists for exactly that second case — it hashes the
> file on the disc against the working copy rather than trusting the copy.

### Attaching, if you are doing it by hand

`build_repo_iso.ps1 -AttachTo` covers this. By hand: a VM has **one** DVD drive,
so attaching is a swap of the path rather than an addition, and the VM may be
running or off.

```powershell
Get-VMDvdDrive -VMName LabClient | Set-VMDvdDrive -Path <drive>:\LabRepo.iso
Get-VMDvdDrive -VMName LabClient                    # must show DvdMediaType : ISO
```

**Check `DvdMediaType`, not the path.** A path with `DvdMediaType : None` behind
it means the drive is empty and the guest is still reading whatever it had. If
you ever need both discs at once, `Add-VMDvdDrive` gives a second drive — not
needed here, since Windows is installed by the time this disc is wanted.

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
| Location | your country — if it is not on the first list, **`other` → continent → country** | That first list is a shortlist of common choices, not the world. Ghana, for one, is only behind `other` → `Africa`. It is not missing, it is one level down |
| Keyboard | **the layout your physical keyboard actually has** — see the test below | Not cosmetic, and the only screen here whose wrong answer follows you into every later command |
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
| Debian archive mirror — country | **`enter information manually`**, at the very top of the list | Different list, different reason from the location screen: this one holds **only countries that host a mirror**, so in much of the world yours is genuinely absent (Ghana is). Picking a plausible neighbour is worse than the CDN |
| Mirror hostname / directory | **`deb.debian.org`** / `/debian` | Anycast CDN: it resolves to whichever mirror is genuinely nearest, from anywhere |
| HTTP proxy | blank | |
| Popularity contest | No | |
| **tasksel** (software selection) | **untick everything except *standard system utilities*.** SSH server optional | See below |
| GRUB bootloader | Yes, to the disk (`/dev/sda`) | |

This step needs the internet, which the VM has because it is still on the
**Default Switch**. It moves to the isolated `LabMonitor` switch at step 9.

### The keyboard, and the two-second test that settles it

**The question is about the physical keyboard in front of you, not about where
you are.** Look at the `2` key and read the symbol printed above the 2:

| Printed above `2` | Your layout is | Pick |
|---|---|---|
| `@` | US | `English (US)` |
| `"` | UK | `English (UK)` |

That one key is decisive because `@` and `"` swap places between the two
layouts. **Do not pick by country.** `English (Ghana)` is in that list and is
US-derived; choosing it while typing on a UK keyboard gives exactly the mismatch
this section exists to prevent. This machine's keyboard prints `"`, so the lab
here runs `English (UK)` in a Ghanaian office, and that is the correct answer,
not an inconsistency.

**The symptom, if it is already wrong:** `|` types as `>`, and `\` types as `<`.

That signature identifies the cause precisely. UK and most European keyboards
are 105-key **ISO** boards with an extra key between left Shift and `Z` — keycode
86, which US 104-key boards do not have at all. The US console keymap assigns
`<` and `>` to that key. So the pipe you typed is a *redirect*: the shell builds
a different, perfectly valid command, runs it, and the error you get back
belongs to something else entirely. Here it surfaced as a `dpkg` usage error
about conflicting `-c` and `-l` flags, which has nothing to do with the actual
problem and sends you looking in the wrong place.

**Fixing it afterwards** — as root (see step 8 for `su -`):

```sh
dpkg-reconfigure keyboard-configuration
```

| Dialog | Answer |
|---|---|
| Keyboard model | **Generic 105-key PC** — usually already highlighted |
| Keyboard layout | the list offers **only US variants**. Your layout is behind **`Other`**, the last entry at the bottom — the same "one level down" pattern as the location screen |
| Country of origin | e.g. **`English (UK)`**. Sits directly above `English (US)`; a kernel log line may print over that row, which obscures the text but not the highlight |
| Layout variant | the **plain** entry — not Dvorak, Colemak, Macintosh or "intl." |
| Key to function as AltGr | **`The default for the keyboard layout`**, the top entry. The highlight starts on *Left Alt*, six lines down, so this one needs arrowing **up** |
| Compose key | **`No compose key`** |

Then apply and verify without rebooting:

```sh
setupcon
grep XKB /etc/default/keyboard      # XKBMODEL="pc105", XKBLAYOUT="gb" (or "us")
```

Type `|` and `\` at the prompt to confirm, then **Ctrl+C** to discard the line
rather than running it.

> **When the last dialog closes, the console is often not repainted.** The dead
> dialog stays on screen and the machine looks frozen — it is not, and your
> Enter presses are going to the shell underneath it. `clear` proves it. This
> cost a "it just stuck there" here on 2026-08-13; the giveaway in the capture
> was three `root@labengine:~#` prompts stacked below the ghost dialog.

**Getting it right on the install screen skips all of the above.** The
reconfigure exists because that screen was answered with the default.

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

**There is no `sudo` on this VM.** Debian installs `sudo`, and puts the first
user in its group, *only when the root password is left blank* at install. We
set one (step 7), so `sudo` is genuinely not there — `sudo: command not found`
is correct behaviour, not a broken install. Become root instead:

```sh
su -
```

The `-` matters: it loads root's environment, including `/usr/sbin` on `PATH`,
which is where `mount` lives. Everything in this step runs as root, so drop
`sudo` from any command you are copying from elsewhere.

**Fix the keyboard first if `|` does not type as `|`** — step 7's keyboard
section has the test, every dialog answer, and the repaint trap that makes the
last screen look frozen. Nothing below needs a pipe, so this is not blocking,
but it will bite the moment you improvise a command.

**Confirm the install really is minimal** before building anything on top of it:

```sh
df -h /
dpkg -l > /tmp/p; grep -c '^ii' /tmp/p
```

**~1.2 GB used and ~313 packages** is right (measured 2026-08-13). A desktop
that survived tasksel reads as 4–5 GB and well over 1500 packages. Note the
pipe-free second command — this is the check you want *before* the keyboard is
sorted out, so it is written to work either way.

Linux does not mount discs by itself without a desktop, so mount it by hand. The
DVD drive is `/dev/sr0`; `-o ro` is explicit because the medium is read-only and
a read-write attempt just fails less clearly:

```sh
mount -o ro /dev/sr0 /mnt
ls /mnt/scripts                     # freshness check, not the point — see below
sh /mnt/scripts/lab_engine_setup.sh
```

**That mounts the whole project, not just the scripts.** `/mnt` is the entire
disc: `engine/`, `common/`, `certs/`, every doc. The `ls` is only a cheap test
that you have a *current* cut of the disc — `scripts/` is the directory that
came up missing when the ISO was stale, so it is the fastest tell.

**The script then copies all of it to `/opt/SystemMonitoring`** — it mounts the
disc a second time of its own accord, `cp -r`s the lot including dotfiles,
unmounts, and `chmod -R u+w`s the result, because files off a CD arrive
read-only. The Engine is not run from `/mnt` for two reasons that both matter:
the mount is **read-only** and the Engine *writes* (it owns all persistence, and
`monitoring.db` is created in the repo root), and the mount is **transient** —
eject the disc or reboot and it is gone.

It then checks `certs/` for both the certificate and the key, and refuses to
continue without them. That is precisely the copy-versus-clone difference from
step 4: a clone would leave this machine serving plaintext while the client
speaks TLS, and the Engine's refusal of that client never names the cause.

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
| A guest's console is entirely black and looks hung | Usually the guest blanked its display after idle. Hyper-V's synthetic video reports that as a black framebuffer, which is indistinguishable from a hang by eye | Click into the console and tap **Shift** or **Ctrl** — a modifier wakes it without typing into whatever has focus. **Before assuming a hang, ask the host**: `Get-VMIntegrationService -VMName <vm>` (Heartbeat `OK` means something in the guest is still answering) and `(Get-VM <vm>).CPUUsage` (a hang sits at 0% or pegs at 100%; ordinary work is in between) |
| `Get-VM` says `Running` but nothing responds | Same as the first row | As above |
| Windows Setup refuses: "This PC can't run Windows 11" | TPM off. Gen 2 VMs have a virtual one but it is off by default and the wizard never offers it | `setup_lab_vms.ps1` enables it. By hand: *Settings → Security → Enable TPM*, VM off |
| Debian won't boot at all | Secure Boot template defaults to *MicrosoftWindows* | Template must be **MicrosoftUEFICertificateAuthority**, or off |
| Debian installer says *Low memory mode* and asks which installer components to load | The Engine VM has 512 MB. Debian 13 drops into low-memory mode below roughly a gigabyte — 512 MB is the figure the Engine **runs** in, not one it installs in | Power off, `Set-VMMemory LabEngine -StartupBytes 2GB`, install, and let step 9 cut it back. The scripts now do both halves |
| Your country is not in the Debian mirror list | The list holds only countries that host a mirror. Ghana does not | Top of the list → **`enter information manually`** → `deb.debian.org`, `/debian`. The CDN beats any hand-picked neighbour |
| The Debian installer is sluggish, or its window is awkward over VMConnect | *Graphical install* was chosen at the GRUB menu | Reboot the VM and take plain **Install**. Nothing in this build needs the GTK installer |
| *Select and install software* is retrieving **1000+ files** | A desktop is being installed. Enter on the tasksel page **accepts what is ticked** — it does not toggle the highlighted line, and the desktop entries are ticked by default | Power off and redo the install. ~8 minutes, versus untangling a desktop from an 8 GB disk. A minimal install retrieves a few hundred files, not thousands — that count is the tell |
| Tempted to `apt purge` the desktop instead of reinstalling | A purged desktop task leaves residue, and `gdm` will have been enabled on a headless box | Reinstall. The VM holds nothing yet — the repo arrives at step 8, after this |
| `sudo: command not found` in LabEngine | Debian installs `sudo` **only** when the root password is left blank at install. We set one | `su -` (with the dash, for root's `PATH`). Nothing here needs `sudo` installed |
| A client appears in the Admin's roster that does not exist — e.g. `lab1-pc-01` at `127.0.0.1` | The dev box's `monitoring.db` travelled on the disc. Gitignore does not help: the disc is a copy of the working directory, by design | `rm -f /opt/SystemMonitoring/monitoring.db` on the Engine and restart it — the schema is recreated empty. `build_repo_iso.ps1` now excludes `*.db` |
| Engine accepts a client, then `sqlite3.OperationalError: attempt to write a readonly database` | `/opt/SystemMonitoring` is owned by **root** (the setup script copied it as root) while the Engine runs as `lab`. `chmod u+w` grants write to the *owner*, which is not the same thing | `chown -R lab:lab /opt/SystemMonitoring` as root. `lab_engine_setup.sh` now does this, and re-running it fixes an existing tree |
| `engine --check` says `Database ready` but the Engine cannot write | The check ran as **root** and the Engine runs as `lab`. A check under a different identity than the program proves nothing about the program | The script now runs `--check` as the account that will run the Engine (`RUN_AS`, default `lab`) |
| `\|` types as `>` and `\` types as `<` in the guest console | Keyboard has the extra key left of Z (keycode 86, UK/European); the US console keymap gives `<`/`>` from it. A pipe becomes a redirect, so the command *runs* and fails as something else | As root: `dpkg-reconfigure keyboard-configuration`, pick your real layout, then `setupcon`. Step 7 has the `2`-key test and every dialog answer |
| An error that makes no sense for the command you typed | Same cause as the row above, one step removed — the shell ran a *different* command than the one you meant | Check the line as the shell saw it before debugging the tool it names |
| A `dpkg-reconfigure` / installer dialog appears frozen; Enter does nothing | The dialog already exited and the console was never repainted. The shell prompt is underneath the ghost | `clear`. If prompts are stacking up at the bottom of the screen, that is the confirmation |
| Your keyboard layout is not in the layout list | The list shows variants of the *currently selected* language only | **`Other`** at the bottom → full country list. Same pattern as the location screen |
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
| Re-cutting the ISO fails: *the file is being used by another process* | A running VM holds the image it has mounted | Eject first (`Set-VMDvdDrive -Path $null`), copy, re-attach. Do it before the guest mounts the disc, not after |
| A guest that had the disc mounted suddenly cannot: `mount: fsconfig() failed: /dev/sr0: Can't open blockdev` | The medium was taken away underneath it. Mounting the ISO **on the host** — to inspect it, or to verify it — ejects it from every guest holding it | Re-attach and mount again; `reboot` the guest if its view of the drive stays stale. Verify an image *before* attaching it, never after: `build_repo_iso.ps1` checks the temporary copy for exactly this reason |
| `Set-VMDvdDrive` reports an error, or appears to work but the drive is empty | Ejecting and re-attaching in quick succession can fail transiently — the drive object churns | **Always verify**: `Get-VMDvdDrive` must show `DvdMediaType : ISO`, not just a path. Re-issue with explicit `-ControllerNumber 0 -ControllerLocation 1` |
| LabEngine boots back into the Debian installer | The netinst is still attached and the VM boots DVD-first | Swap the DVD path to `LabRepo.iso` (step 7) |
| `./lab_engine_setup.sh` → *Permission denied* | No execute bit off a Windows-authored image, and the mount is read-only so `chmod` cannot help | `sh /mnt/scripts/lab_engine_setup.sh` |
| Filenames on the disc are truncated or upper-cased | Built without `-u2`, so it is ISO 9660 only | Rebuild with `-u2` |
| Both VMs show *Cannot connect to virtual machine configuration storage* | The lab drive reconnected after the Hyper-V service enumerated it — common with an external or secondary disk | `Restart-Service vmms -Force` with the VMs off. The configs are fine |
| A stray `.avhdx` appears; checkpoints behave strangely | Hyper-V takes an **automatic checkpoint** on first start by default | `Set-VM -AutomaticCheckpointsEnabled $false`. Remove strays with `Remove-VMSnapshot` — **never** by deleting the `.avhdx` |
| Time-based lockout tests behave impossibly after a revert | Guest clock is stale; lockout windows are time-based and HMAC-protected | `w32tm /resync` in the guest after **every** revert |
| USB detection (T2.2) never fires in the VM | Hyper-V has no plain USB pass-through | Run T2.1 and T2.2 on the host instead |
| VM creation fails or fills the system drive | Hyper-V's default storage path is on `C:` | `setup_lab_vms.ps1` repoints it. This is not optional |

---

## What is scripted, and what you do by hand

| Stage | Who does it | Why |
|---|---|---|
| Storage, switch, host address, firewall, both VMs | `setup_lab_vms.ps1` | Scripted |
| **Install Windows in LabClient** | **you** | Setup and OOBE are interactive. An `unattend.xml` could drive it, but the lab is built twice in this project's life and an answer file that drifts is worse than a table of answers you can read. The trimmed-image route was tried and abandoned — `issues.md` D9 |
| **Install Python in LabClient** | **you** | The two choices that matter — *install for all users* and *disable path length limit* — are on the installer's first and last screens, and both fail late and misleadingly when missed |
| Venv, packages, Defender, static address | `lab_client_setup.ps1` | Scripted |
| Cut the repo disc and swap it into a VM | `build_repo_iso.ps1` | Scripted, including the eject-copy-attach dance and verifying the disc afterwards |
| **Copy the repo off `D:` inside LabClient** | **you** | Two commands, and the script that would do it lives on the disc being copied |
| **Install Debian in LabEngine** | **you** | Same reasoning as Windows. A preseed file is possible and is one more artefact to maintain, get wrong, and keep in step with a procedure that already documents every answer |
| **`umount /mnt` before re-cutting the disc** | **you** | The host cannot take a medium away from a guest that has it mounted. Nothing on the host can reach inside the guest to do this |
| **`mount -o ro /dev/sr0 /mnt` in LabEngine** | **you** | Irreducible: the provisioning script *is on the disc*, so something has to mount it before anything can run. One command |
| `python3`, `sqlite3` check, repo copy, static IP, `--check` | `lab_engine_setup.sh` | Scripted, and it reuses the mount you already made |
| Memory, checkpoint policy, switch replug, `baseline` | `lab_host_finalize.ps1` | Scripted, per VM, VM off |
| Read a guest's screen | `vm_console_shot.ps1` | Scripted — works at a boot menu or mid-installer |
| **The T0.1 / T0.2 gate** | **you** | Two commands, and the point is to look at the result |

The pattern: **anything interactive by nature stays manual and is documented
answer by answer; anything mechanical is a script that checks its own work.**
The manual steps are exactly the OS installers, the one mount that bootstraps
everything else, and the gate you are meant to read.

## The scripts

| Script | Where | When |
|---|---|---|
| `scripts/setup_lab_vms.ps1` | host | Step 1 — once, before anything |
| `scripts/build_repo_iso.ps1` | host | Step 4, and again after **any** code or script change |
| `scripts/lab_client_setup.ps1` | in LabClient | Step 5 — after Windows and Python |
| `scripts/lab_host_finalize.ps1` | host | Steps 6 and 9 — per VM, VM off |
| `scripts/lab_engine_setup.sh` | in LabEngine | Step 8 — after Debian |

All five are **idempotent** and take `-DryRun` (`DRY_RUN=1` for the shell one).
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
