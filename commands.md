# Command reference

Every program in the project, what it takes, and why the entry points are shaped
the way they are.

`README.md` is the design specification and can lag the code. This file
describes what the code does *now* — if the two disagree, this one and `--help`
are right.

## Contents

- [The one thing that trips people up](#the-one-thing-that-trips-people-up)
- [Engine](#engine--python--m-engine)
- [Client Agent](#client-agent--python--m-client)
- [Administrator](#administrator--python--m-admin)
- [Shared scripts](#shared-scripts)
- [Lab provisioning — `build_client_image.ps1`](#lab-provisioning--build_client_imageps1)
- [Lab provisioning — `setup_lab_vms.ps1`](#lab-provisioning--setup_lab_vmsps1)
- [labmonitor.py](#labmonitorpy--dev-box-dispatcher)
- [Diagnostics index](#diagnostics-index)

---

## The one thing that trips people up

`python client/main.py` and `python -m client.main` **ignore all flags**. They
are the environment-variable-only path and always were.

| Invocation | Runs | Flags? |
|---|---|---|
| `python -m client` | `client/__main__.py` → `client/cli.py` → `client.main` | **yes** |
| `python -m client.main` | `client/main.py` | no — env vars only |
| `python client/main.py` | `client/main.py` | no — env vars only |

The same holds for `engine` and `admin`.

**Why.** Each `config.py` reads every setting from `os.environ` into
module-level `Final` constants **at import time**, and `main.py` imports those
constants at module level. A flag therefore has to reach the environment
*before* the component is imported. `cli.py` is what does that:

```python
args = build_parser().parse_args(argv)
os.environ.update(_env_from(args))      # flags become env vars
...
from client.main import main            # imported only now
```

Putting argparse inside `main.py` would not work: `from client.config import
ENGINE_HOST` at the top of the file has already frozen the old value by the
time `parse_args` runs. The three `main.py` files are left untouched on purpose
so a service or Scheduled Task invocation keeps working unchanged.

Consequences worth knowing:

- Every flag has an environment-variable equivalent, because setting that
  variable is *all the flag does*.
- Flags win over an already-set variable.
- None of the three entry points takes a positional argument. All flags are
  optional.

One extra note on `python client/main.py` specifically: that form puts
`client/` on `sys.path[0]` rather than the repo root, so it only resolves
`from client import ...` because the project is installed editable. Prefer the
`-m` form.

---

## Engine — `python -m engine`

Linux only in production (asyncio backed by `epoll`); runs under WSL on a dev
box. Imports nothing but the standard library, so WSL needs no venv — and
`engine/cli.py` is stdlib-only to keep that true.

| Flag | Env var | Default | Meaning |
|---|---|---|---|
| `--host ADDR` | `ENGINE_HOST` | `0.0.0.0` | Address to **bind**. Note the asymmetry: on the Engine this is what to listen on; on the client and admin the same-named variable is what to *connect to*. |
| `--port N` | `ENGINE_PORT` | `5000` | Listening port. |
| `--db PATH` | `ENGINE_DB` | `monitoring.db` | SQLite file. The Engine owns all persistence; neither other unit has a database. |
| `--retention-days N` | `ENGINE_RETENTION_DAYS` | `30` | Prune monitoring data older than N days. `0` disables pruning, and `--check` says so explicitly. The real retention period is an open decision (`issues.md` section A). |
| `--no-tls` | `ENGINE_TLS=0` | off | Serve plaintext **even though** `certs/engine-cert.pem` exists. TLS is presence-based — it enables itself when the certificate is there, so there is no flag to forget — and this is the deliberate escape hatch. |
| `--dev-bypass-auth` | `DEV_BYPASS_AUTH=1` | off | Skips the registration handshake *entirely*: no nonce is ever sent, so a forgotten flag is visible in a packet capture rather than passing quietly as a validation step. Logs a warning per peer. Development only. |
| `-v`, `--verbose` | `ENGINE_LOG_LEVEL=DEBUG` | `INFO` | DEBUG surfaces heartbeats. |
| `--check` | — | — | Prints the resolved configuration and prepares the database, then exits. |

`--check` reports listen address, database path, max clients, max admins,
heartbeat timeout, log level, retention, outbox TTL, transport and
authentication state, then initialises the database. It deliberately **does not
bind the port**, so it is safe to run while an Engine is already serving.
Returns 1 if the certificate is missing or the database cannot be prepared.

```bash
wsl -- bash -lc "cd /mnt/c/.../SystemMonitoring && python3 -m engine --check"
wsl -- bash -lc "cd /mnt/c/.../SystemMonitoring && python3 -m engine -v --dev-bypass-auth"
```

WSL2 localhost forwarding means a Windows client reaches it at `127.0.0.1:5000`
unchanged.

**Also in this package**

| Command | Arguments | Purpose |
|---|---|---|
| `python -m engine.setup_db [PATH]` | one optional positional, defaults to `DATABASE_PATH` | Create the schema without serving. |

---

## Client Agent — `python -m client`

Windows only, headless in production.

| Flag | Env var | Default | Meaning |
|---|---|---|---|
| `--engine HOST` | `ENGINE_HOST` | `127.0.0.1` | Engine address to **connect to**. |
| `--port N` | `ENGINE_PORT` | `5000` | Engine port. |
| `--id NAME` | `CLIENT_ID` | `hostname-platform` | Identity on the wire **and** the local state directory. See [client identity](#client-identity) below. |
| `--no-tls` | `CLIENT_TLS=0` | off | Plaintext even if the pinned certificate is present. |
| `-v`, `--verbose` | `CLIENT_LOG_LEVEL=DEBUG` | `INFO` | DEBUG logging. |
| `--check` | — | — | Resolved configuration, local state, missing bundles. Exits. |
| `--once` | — | — | One collection cycle, printed. No sockets, no Engine. Exits. |
| `--top N` | — | `10` | How many processes `--once` prints, busiest CPU first. Only meaningful with `--once`. |

`--check` reports configuration, transport, which bundled components are
**missing** (pinned Python runtime, dialog exe, overlay exe — all absent until
the packaging phase, each falling back to the running interpreter with a logged
warning), the state directory and whether it is writable, live `lockout active`
and `paused` state read through the same fail-closed helpers the agent uses, the
cached blacklist size, and whether an agent is already running under this id.

`--once` is the flag for bringing up a new machine. It primes CPU counters,
waits a second, then collects and prints processes, network counters, USB
events, idle time and screen-lock state. Because it touches no network, "does
psutil see processes here" can be answered separately from "is the Engine
reachable".

```powershell
.\.venv\Scripts\python.exe -m client --check
.\.venv\Scripts\python.exe -m client --once --top 20
.\.venv\Scripts\python.exe -m client --engine 192.168.1.50 --id lab1-pc-07 -v
```

### Client identity

`CLIENT_ID` defaults to `f"{socket.gethostname()}-{platform.system()}"`
(`common/utils.py`), so **on a real deployment you never have to set it** — one
machine, one hostname, one id. Set `--id` when the hostname is not the name you
want in the Admin console and the audit trail, or when running several agents on
one dev box.

The id is *not* derived from a MAC address, and deliberately so: a hostname is
the name a lab already uses on its own signage and asset register, so an
operator seeing `lab1-pc-07` in the console knows which desk to walk to, whereas
a MAC address means nothing to them. MAC addresses are also less stable than
they look — they change with the adapter, differ between Wi-Fi and Ethernet on
the same machine, and are randomised by default on modern Windows Wi-Fi. Since
the id keys both the Engine's records and the local state directory, a value
that silently changes when someone docks a laptop would split one machine's
history in two.

The trade-off is that a rename produces a new id and therefore new history. That
is the right way round: renames are rare and deliberate, adapter changes are
neither.

Two rules that follow from the id keying local state:

- **State is per client, not per machine.** `STATE_DIR` is
  `STATE_ROOT / state_component(CLIENT_ID)`. `CLIENT_ID` arrives from the
  environment unvalidated, so it is sanitised to one path component *and*
  suffixed with a hash of the original — sanitising alone is lossy, and
  `lab1/pc-01` colliding with `lab1_pc-01` would silently reunite two machines'
  state.
- **Out-of-process readers must be told which id.** A Windows service and a
  Scheduled Task inherit nothing from the installer's environment, so
  `install_service.py` bakes `--id` into **both** command lines. Get this wrong
  and the watchdog resolves a different directory, finds no schedule, and
  releases a blocked machine.

### One agent per id

Starting a second agent under an id that already has one running exits 1 with
the resolved lock path in the message. Two agents under *different* ids on one
box are allowed — see `issues.md` B24 and D8.

`python -m client --check` prints `agent running   True/False` for this id.

### Also in this package

Each has its own argparse and is spawned on demand, not persistently.

| Command | Arguments | Purpose |
|---|---|---|
| `python -m client.watchdog` | `--id NAME` | One-shot lockout enforcement pass, independent of the agent. The installer runs it every ~5 min as SYSTEM. `--id` must match the agent's, or it reads the wrong state directory and releases a blocked machine. |
| `python -m client.overlay_app` | `--until ISO` (**required**), `--mode scheduled\|pause`, `--message TEXT`, `--id NAME` | Fullscreen lockout overlay. `scheduled` shows a countdown; `pause` deliberately shows none. Exits 0 if `--until` has already passed, 2 if it is unparseable, and 0 without showing anything if an overlay is already up for this client — it holds a lock in `STATE_DIR` so every launcher can see it (`issues.md` B25), which is what `--id` is for. Takes over the screen and disables Task Manager until `--until`, so run it somewhere you are not working. |
| `python -m client.dialog_app` | `--message TEXT` (**required**), `--title T`, `--timeout N` (default 60, `0` waits forever), `--allow-cancel` | Warning dialog. **The answer is the exit code**: `0` acknowledged, `1` cancelled, `2` timed out, `3` bad arguments. Note `--help` also exits 3 — argparse raises `SystemExit(0)` and the broad `except SystemExit` maps it to `EXIT_BAD_ARGS`. Cosmetic (the help text still prints), but it means the exit code cannot distinguish help from a genuine argument error. |
| `python -m client.install_service` | `--startup auto\|demand\|delayed-auto`, `--uninstall` | Service, state-directory ACLs and watchdog Scheduled Task, in one step. Needs an elevated prompt. Takes no `--id` — it reads `CLIENT_ID` from config and bakes it into the command lines it registers. |

Both helper windows are QML. `LABMONITOR_UI_HEADLESS=1` loads and validates
their QML without showing anything.

---

## Administrator — `python -m admin`

Windows, Qt 6 + QML over a Python backend, single-threaded via qasync.

| Flag | Env var | Default | Meaning |
|---|---|---|---|
| `--engine HOST` | `ENGINE_HOST` | `127.0.0.1` | **Prefills** the connect field; does not auto-connect. |
| `--port N` | `ENGINE_PORT` | `5000` | Prefilled port. |
| `--id NAME` | `ADMIN_ID` | `admin-<hostname>` | Identity. Lands in `command_log.admin_id` for every command sent, so it is the audit trail's operator field. |
| `--no-tls` | `ADMIN_TLS=0` | off | Plaintext even if the pinned certificate is present. |
| `-v`, `--verbose` | `ADMIN_LOG_LEVEL=DEBUG` | `INFO` | DEBUG logging. |
| `--check` | — | — | Resolved configuration, then exits. |
| `--check-qml` | — | — | Loads every QML file offscreen, reports errors and warnings, exits. Renders nothing. |

The address is also remembered in QSettings once a connection succeeds;
`--engine` overrides what the window is prefilled with.

Read from the environment, with no flag:

| Env var | Default | What it is |
|---|---|---|
| `ADMIN_CAPTURE_DIR` | `~/LabMonitor/captures` | Where returned screen captures are written, as `<client>-<timestamp>.jpeg`. Operator output, so it lives with the operator's files rather than in the repository — a console installed read-only must still be able to save one. The client id reaches a filename and is peer-supplied text, so it is sanitised before it does |

`--check-qml` is the one to reach for after touching a `.qml` file. It loads the
whole tree on the offscreen platform with the same context properties
`admin/main.py` sets, **under the same Controls style the console runs**
(`admin/style.py`, called by both), collects every Qt warning and exits 1 if
there are any — no window, no Engine connection, nothing to close. A check
running under a different style than the app would be checking a different tree
of controls than the one that ships.

```powershell
.\.venv\Scripts\python.exe -m admin --check-qml
.\.venv\Scripts\python.exe -m admin --engine 192.168.1.50 --id ms-lab-supervisor
```

This package ships no companion executables — the console is the only program in
it. The lockout overlay and warning dialog belong to the Client Agent and run on
the lab machine.

---

## Shared scripts

| Command | Arguments | Purpose |
|---|---|---|
| `python -m scripts.generate_cert` | `--dir PATH` (default `certs/`), `--days N`, `--identity NAME` (default `TLS_IDENTITY`), `--force` | Generate the Engine's self-signed certificate. `--identity` is the fixed name clients pass as `server_hostname`, which is what keeps hostname verification on even when the Engine's address changes. `--force` replaces an existing certificate. |
| `python -m scripts.bench_database` | none | Measure SQLite write cost. Re-run before changing the synchronous-write decision. |

---

## Lab provisioning — `build_client_image.ps1`

> **Not used by the Phase 5 lab any more.** The media this produces installs
> Windows and then loops OOBE forever — the completion flag is never written, and
> both Windows Hello enrolment screens fail. The client VM is built from the
> **stock** retail ISO instead. `testing.md` section 0.1e has the full account
> and what would change the decision. Kept, and documented, because the script
> works as designed and the keep-list is worth having; it is the *result* that is
> unusable. `setup_lab_vms.ps1` defaults to stock media accordingly.

The odd one out in this file: PowerShell, run on the **host**, and it builds no
part of the system. It produces trimmed Windows 11 install media. Rationale and
the keep/remove decisions live in `testing.md` section 0.1e; this is the flag
reference.

```powershell
# Elevated Windows PowerShell 5.1, from the repo root
Set-ExecutionPolicy Bypass -Scope Process
.\scripts\build_client_image.ps1 -SourceIso <path> [-Scratch <dir>] [-OutputIso <path>] [-DryRun]
```

| Parameter | Type | Default | What it is |
|---|---|---|---|
| `-SourceIso` | path, **required** | — | **Input.** The untouched retail ISO. Mounted read-only; never written to |
| `-Scratch` | directory | `%SystemDrive%\labimage` | **Workbench.** Created, filled, and **deleted at the start of every run** — keep nothing of your own here. ~3 GB for a dry run, ~25 GB for a build |
| `-OutputIso` | path | `.\win11-labclient.iso` | **Result.** The trimmed ISO to install the VM from. Unused by `-DryRun` |
| `-DryRun` | switch | off | Mount, classify, print, discard. Writes nothing and needs no ADK. **Run this first** |
| `-Edition` | string | `Windows 11 Pro` | Which edition to keep from multi-edition media. Pro is the default because T4.5 needs `gpedit.msc` (`issues.md` C10) |
| `-AdminUser` | string | `lab` | Local account created by the injected `autounattend.xml`, which is also what skips 24H2's Microsoft-account requirement |
| `-AdminPassword` | string | `lab` | Password for the above. Weak on purpose and acceptable only because the VM is on an isolated switch — `testing.md` 0.1c |
| `-OscdimgPath` | path | probe | Full path to `oscdimg.exe`, for an ADK installed outside its default location. Without it the script probes the ADK default and `PATH` |
| `-KeepWinget` | switch | off | Keep App Installer. Off because Python is installed from its own `.exe` |
| `-RemoveFeaturePayload` | switch | off | Also delete disabled features' payload from the component store. Saves ~1 GB, costs some serviceability |
| `-SkipCompress` | switch | off | Skip the final `/Export-Image` recompress. Faster, larger ISO — for iterating on the keep-list |

**Output labels.** One line per provisioned package, then per capability:

| Label | Meaning |
|---|---|
| `KEEP` | on `$KeepAppx` — Notepad, Snipping Tool, Terminal, plus the frameworks they load against |
| `PROTECTED` | on `$ProtectedAppx` — the shell itself. Start menu, File Explorer, OOBE, credential and print dialogs |
| `REMOVE` | everything else. The model is a keep-list, so this is the default outcome |

**Prerequisite: `oscdimg.exe` from the Windows ADK**, for the build only. The
script resolves it from the ADK's default location or `PATH` and **will not
download it** — see `testing.md` section 0.1e.

**Two behaviours worth knowing.** The script tolerates an ISO left attached by a
previous failed run and reuses it, rather than making every retry start with a
manual `Dismount-DiskImage`. And on any failure inside the mounted image it
unmounts with `/Discard`, so a bad run never leaves a half-modified image
mounted under `-Scratch`.

---

## Lab provisioning — `setup_lab_vms.ps1`

The other host-side script. It builds the Phase 5 lab itself: Hyper-V storage on
`K:`, the `LabMonitor` Internal switch, and both VMs. It installs no operating
system — that half stays interactive. `testing.md` sections 0.1, 0.1d and 0.1f
are the rationale; this is the flag reference.

```powershell
# Elevated Windows PowerShell 5.1, from the repo root
.\scripts\setup_lab_vms.ps1 -DryRun
.\scripts\setup_lab_vms.ps1
```

| Parameter | Default | What it is |
|---|---|---|
| `-ClientIso` | `K:\Win11-LabClient.iso` | Trimmed media from `build_client_image.ps1` |
| `-EngineIso` | `K:\debian-netinst.iso` | Debian netinst. **Missing is not fatal** — the Engine VM is skipped with a notice and the rest still runs; re-run once it has downloaded |
| `-LabRoot` | `K:\LabMonitor` | Where VMs and VHDXs go. Refuses `C:`, which has under 5 GB free |
| `-ClientName` / `-EngineName` | `LabClient` / `LabEngine` | VM names |
| `-SwitchName` | `LabMonitor` | Internal switch, and the `vEthernet (…)` adapter named after it |
| `-HostIp` / `-Prefix` | `192.168.100.1` / `24` | Host address on that adapter |
| `-DryRun` | off | Print every action, change nothing. **Run this first** |

**Why this exists rather than the wizard.** Three settings cannot be changed
after a VM is created, and all three fail with messages that do not name the
cause: Generation 2; the virtual TPM (present on Gen 2 but **off by default**,
and the wizard never offers it — Windows Setup then refuses with "This PC can't
run Windows 11"); and the Secure Boot template, which defaults to
*MicrosoftWindows* and will not boot Debian. The script sets all three per VM,
along with `AutomaticStopAction ShutDown` — otherwise Hyper-V holds a `.bin`
file the size of assigned RAM the whole time a VM runs.

**Idempotent.** Existing directories, switches, addresses and VMs are reported
and left alone, so it is safe to re-run after fixing one thing. That is also how
the Engine VM gets added once its ISO arrives.

**What it deliberately leaves undone.** Dynamic Memory is not applied to the
client VM — Windows Setup misbehaves under a moving allocation, so the VM is
created with a static 4 GB and the script prints the exact `Set-VM` line to run
afterwards. Both VMs are created on *Default Switch* for provisioning internet
and move to `LabMonitor` by hand later.

---

## Lab provisioning — the guest/host scripts

`setup_lab_vms.ps1` creates the VMs; these fill them in, keep them fed
with current code, and let you see their screens.
[`LAB-SETUP.md`](LAB-SETUP.md) is the step-by-step order. All are idempotent,
all take a dry-run switch, and **all need an elevated shell** (root, for the
shell script).

### `lab_client_setup.ps1` — inside LabClient

```powershell
.\scripts\lab_client_setup.ps1 [-RepoPath C:\SystemMonitoring] [-PythonExe C:\Python312\python.exe]
                               [-Trim] [-SetNetwork] [-StaticIp 192.168.100.3] [-DryRun]
```

| Parameter | Default | What it is |
|---|---|---|
| `-RepoPath` | `C:\SystemMonitoring` | Short path on purpose — pip nests deeply |
| `-PythonExe` | `C:\Python312\python.exe` | The **all-users** base interpreter the venv is built from |
| `-Trim` | off | Disable services and remove Appx that no Phase 5 test touches |
| `-SetNetwork` | off | Apply the static address. **Do this last** — it removes the VM's internet |
| `-DryRun` | off | Print, change nothing |

**It refuses rather than warns on four things**, each because the failure it
prevents surfaces late and misleadingly: Store Python (per-user and sandboxed,
so the T5.4 service running as SYSTEM cannot reach it), Python below 3.10, a
missing `certs/` (presence-based TLS would leave this machine on plaintext), and
a repo with no `pyproject.toml`. It also enables long-path support and clears
the read-only attribute that files copied off `LabRepo.iso` carry.

### `lab_engine_setup.sh` — inside LabEngine

```sh
sh /mnt/scripts/lab_engine_setup.sh              # DRY_RUN=1 to preview
REFRESH=1 sh /mnt/scripts/lab_engine_setup.sh    # copy a newer disc over an existing tree
```

POSIX `sh`, not bash — a netinst with everything deselected has `dash`. Installs
`python3`, **fails hard if `sqlite3` is missing** (the Engine owns all
persistence and it is the one stdlib module a stripped build can lack), copies
the repo off `/dev/sr0`, writes the static address with **no gateway line**, and
runs `engine --check`. Rejects Debian 11 by `VERSION_ID` — Python 3.9 is under
the floor.

| Override | Default | What it is |
|---|---|---|
| `REPO` | `/opt/SystemMonitoring` | Where the repository lands |
| `RUN_AS` | `lab` | **The account that will run the Engine.** The script runs as root, so everything it copies is root-owned, and `chmod u+w` grants write to the *owner* — not to whoever serves. Without the `chown` this drives, the Engine accepts a client and dies on `attempt to write a readonly database`. `--check` is also run as this user, since a check under a different identity than the program proves nothing about the program |
| `REFRESH` | `0` | `1` **replaces** an existing tree with the disc's copy — the old directory is removed, not merged into, so a module deleted upstream stops importing and the guest cannot end up running a mixture of two versions. Without it an existing repository is left alone, which is right for provisioning and useless for iterating |
| `FRESH_DB` | `0` | A refresh preserves `monitoring.db` across the replace, because the Engine owns all persistence and a code update should not silently discard the record. `1` starts with an empty database instead |
| `STATIC_IP` / `NETMASK` | `192.168.100.2` / `255.255.255.0` | Address on the isolated switch |
| `DRY_RUN` | `0` | Print, change nothing |

It **reuses a mount you already made** rather than creating its own. You reach
this script by mounting the disc, so an earlier version's `mkdir /mnt/labrepo`
tried to create a directory inside the read-only medium it had just been handed.

### `build_repo_iso.ps1` — host, whenever code changes

```powershell
.\scripts\build_repo_iso.ps1 [-AttachTo LabEngine,LabClient] [-RepoPath <path>]
                             [-IsoPath <drive>:\LabRepo.iso] [-DryRun]
```

Cuts `LabRepo.iso` from the working copy and swaps it into the named VMs. Finds
the lab drive itself. Stages with `robocopy` (dropping `.venv`, `__pycache__`,
`.pytest_cache`, and **`*.db`** — the dev box's `monitoring.db` otherwise puts a
phantom client in the lab Engine's roster), images with `oscdimg`, then:

- **Verifies before attaching, never after.** Mounting an ISO on the host takes
  the medium from every guest holding it, so checking the placed file would
  empty both drives — the guest then fails with `Can't open blockdev`, which
  reads as a guest fault.
- Confirms the scripts and both `.pem` files are physically on the image, and
  hashes `lab_engine_setup.sh` against the working copy. Presence is not
  freshness: a "fixed" script was once tested against a disc that never
  received the fix.
- **Refuses CRLF in any `.sh`.** dash reports it as `set: Illegal option -`,
  naming neither the file nor the cause. `.gitattributes` pins these to LF, but
  anything writing a file outside git can undo that.
- Ejects before copying (a running VM holds the image), then checks
  `DvdMediaType` rather than the returned path, and retries once.

It cannot `umount` inside a running guest — Linux holds the medium — so it
detects that lock and names the fix. [`LAB-SETUP.md`](LAB-SETUP.md) has the
recovery procedure for a disc that has dropped out of a guest.

### `vm_console_shot.ps1` — host, any running VM

```powershell
.\scripts\vm_console_shot.ps1 -VMName LabEngine [-Width 800] [-Height 600] [-Out <path>]
```

Saves a PNG of a guest's console, read from the host through Hyper-V's WMI
thumbnail API — no agent, no integration services, no network, nothing typed
into the guest. It works at a boot menu or mid-installer, which is when nothing
else can see anything, and it makes the screen quotable rather than described.
A diagnostic aid, not part of the procedure. Drop to `640x480` if a larger
request is refused: it cannot exceed the guest's current video mode.

### `lab_host_finalize.ps1` — host, per VM, VM off

```powershell
.\scripts\lab_host_finalize.ps1 -VMName LabClient [-SkipCheckpoint] [-DryRun]
```

Dynamic Memory (2 / 1 / 3 GB — skipped for `LabEngine`, which stays static at
512 MB since ballooning buys nothing there), automatic checkpoints off plus any
stray one merged away, the `LabMonitor` replug, and the `baseline` checkpoint.
Refuses to run on a VM that is not `Off`: memory mode cannot change while it
runs, and a checkpoint of a running VM captures memory, which a baseline does
not want.

---

## `labmonitor.py` — dev-box dispatcher

```
python labmonitor.py <command> [flags]
```

A convenience for a machine with all three units checked out. **Not deployed** —
in production each unit runs from its own package, which is why every flag lives
in the components' `cli.py` and none live here.

It is not argparse. It splits `argv[0]` as the command and passes everything
else through **verbatim**:

```python
command, rest = argv[0], argv[1:]
if command == "client":
    from client.cli import run     # imported inside the branch
    return run(rest)
```

Two consequences:

- `labmonitor.py client --help` gives you the *client's* help. With argparse
  subparsers the parent would intercept `--help`; here nothing touches `rest`
  until the component builds its own parser.
- `run(rest)` is the identical function `python -m client` calls, so
  `labmonitor.py client --once` and `python -m client --once` are equivalent in
  every respect.

Imports sit inside their branches deliberately: a top-level
`from admin.cli import run` would drag PySide6 into `labmonitor.py engine`, and
the Engine is meant to import nothing but the standard library.

| Command | Dispatches to |
|---|---|
| `engine` / `client` / `admin` | that package's `cli.run(rest)` |
| `overlay` | `client.overlay_app` (prints a stderr warning first) |
| `dialog` | `client.dialog_app` |
| `certs` | `scripts.generate_cert` |
| `initdb` | `engine.setup_db` |

Exit codes: bare, `-h`, `--help` or `help` prints usage and returns **0**; an
unknown command prints usage to stderr and returns **2**; anything else returns
whatever the component returned.

The dispatcher relaxes no deployment constraint. `labmonitor.py engine` on
Windows will start and bind a port, but the Engine is Linux-only by design and
that is not the configuration to verify against — `--check` is the exception,
since it only resolves configuration and prepares the database. The client and
its helpers are still Windows-only, and `install_service` (not in the table) still
needs elevation.

---

## Diagnostics index

Everything here runs with nothing else started — reach for these before
debugging an integration.

| Command | Answers |
|---|---|
| `python -m engine --check` | Is this box configured the way I think, and is the database writable? Does not bind the port. |
| `python -m client --check` | What id and paths did the agent resolve, what is missing from the bundle, is a lockout live, is an agent already running? |
| `python -m client --once` | Does collection actually work on this machine? |
| `python -m admin --check` | What did the console resolve? |
| `python -m admin --check-qml` | Does the QML tree load without warnings? |
| `python -m pytest -q` | 289 tests. |
| `python -m scripts.bench_database` | What does a SQLite write cost here? |
