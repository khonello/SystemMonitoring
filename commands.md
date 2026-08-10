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
| `--retention-days N` | `ENGINE_RETENTION_DAYS` | `30` | Prune monitoring data older than N days. `0` disables pruning, and `--check` says so explicitly. The real retention period is an open decision (`issues.md` §A). |
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
| `python -m client.overlay_app` | `--until ISO` (**required**), `--mode scheduled\|pause`, `--message TEXT` | Fullscreen lockout overlay. `scheduled` shows a countdown; `pause` deliberately shows none. Exits 0 if `--until` has already passed, 2 if it is unparseable. ⚠️ **Takes over the screen and disables Task Manager** — ask before running it on a machine in use. |
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

`--check-qml` is the one to reach for after touching a `.qml` file. It loads the
whole tree on the offscreen platform with the same context properties
`admin/main.py` sets, collects every Qt warning and exits 1 if there are any —
no window, no Engine connection, nothing to close.

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
| `python -m pytest -q` | 270 tests. |
| `python -m scripts.bench_database` | What does a SQLite write cost here? |
