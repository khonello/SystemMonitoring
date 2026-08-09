# Installation

Three deployable units, each intended for a different machine:

| Unit | Platform | Runs |
|---|---|---|
| **Engine** (`engine/`) | Linux only | Central hub, port 5000, owns the database |
| **Client Agent** (`client/`) | Windows only | Headless, one per lab machine |
| **Administrator** (`admin/`) | Windows | Qt 6 + QML operator console |

> **Packaging does not exist yet.** There is no installer, no bundled Python
> runtime and no frozen helper executables — that is the last phase of the
> project. Everything below runs from source. Three code paths fall back to the
> running interpreter and log a warning when they do: script validation
> (`admin/validation.py`), script execution (`client/executor.py`) and the
> lockout overlay (`client/lockout.py`). **Those fallbacks are for bringing a
> machine up and proving it works, not for shipping.**

## Requirements are split per unit

Deliberately, so a Linux Engine install pulls nothing at all:

| File | For | Contents |
|---|---|---|
| `requirements.txt` | everyone | Test tooling |
| `requirements-admin.txt` | Administrator | PySide6, qasync |
| `requirements-client.txt` | Client Agent | psutil, pywin32, Pillow |

**The Engine imports only the standard library.** It needs no virtualenv and no
`pip install` — that is a property worth preserving, and `engine/cli.py` is
stdlib-only for the same reason.

## Engine (Linux)

```bash
git clone <repo> && cd SystemMonitoring
python3 -m engine --check          # resolved config, prepares the database
python3 -m engine                  # serve
```

`--check` prints the address, database path, caps, retention, outbox TTL and
transport posture, then exits **without binding the port** — so it is safe to
run while an Engine is already serving.

Useful flags (`python3 -m engine --help` for all):

```bash
python3 -m engine --host 0.0.0.0 --port 5000
python3 -m engine --db /var/lib/labmonitor/monitoring.db
python3 -m engine --retention-days 90        # 0 disables pruning
python3 -m engine -v                          # DEBUG, surfaces heartbeats
```

### During development, under WSL

The Engine is Linux-only by design — asyncio there is backed by `epoll`. On a
Windows dev box it runs under WSL, and WSL2 localhost forwarding means the
Windows client reaches it at `127.0.0.1:5000` unchanged:

```bash
wsl -- bash -lc "cd /mnt/c/path/to/SystemMonitoring && python3 -m engine"
```

The database defaults to `monitoring.db` in the working directory. On a
`/mnt/c` DrvFs mount WAL is deliberately **not** enabled — its shared-memory
requirement is unreliable there, and a single-writer process gains little.

## TLS

Generate the Engine's certificate once, then distribute **only the certificate**
(`certs/engine-cert.pem`) with each client package. The key never leaves the
Engine.

```bash
python3 -m scripts.generate_cert       # or: python labmonitor.py certs
```

TLS is **presence-based**: once the certificate exists, the Engine and both
clients enable it automatically. There is no flag to remember. The certificate
is issued for the fixed name `labmonitor-engine` and clients pass that as
`server_hostname` while dialling whatever address the Engine has — so hostname
verification stays on even on DHCP.

To run plaintext deliberately, pass `--no-tls` on each component. Startup always
logs which mode is active.

## Client Agent (Windows)

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt -r requirements-client.txt
.\.venv\Scripts\pip install -e .
```

The editable install matters: it is what makes `from common.protocol import ...`
resolve from every entry point. Running `python client/main.py` directly puts
`client/` on `sys.path`, not the repo root, and fails.

Verify the machine before involving the network:

```powershell
.\.venv\Scripts\python -m client --check    # config, paths, what is missing
.\.venv\Scripts\python -m client --once     # one real collection cycle, printed
```

`--once` proves psutil sees processes, window titles resolve, network counters
read and idle detection works — with no Engine in the picture. Then connect:

```powershell
.\.venv\Scripts\python -m client --engine 10.0.0.5 -v
.\.venv\Scripts\python -m client --engine 10.0.0.5 --id lab1-pc-07
```

`--id` overrides the default `hostname-platform` identity, which also lets one
machine pose as several clients while testing.

### Local state

The agent keeps its security-sensitive state — the derived auth key and the
tamper-protected lockout schedule — under
`%ProgramData%\SystemMonitoring\<client>`, never `%APPDATA%`: it must not be
writable by the logged-in user. `client --check` prints the resolved path.

The directory is **per client**, so several agents on one machine do not share
one lockout schedule. That has an operational consequence: a Windows service and
a Scheduled Task inherit nothing from the environment you install from, so
`client/install_service.py` bakes `--id` into both command lines. If you
register either by hand, include it — a watchdog resolving the wrong directory
finds no schedule and releases a machine that should stay blocked.

`client/install_service.py` registers the service, sets the ACLs on the state
root (inherited by each client directory) and installs the watchdog Scheduled
Task in one step. It needs an elevated prompt.

The lockout schedule is HMAC-protected and **fails closed**: if validation
fails, the machine is treated as still blocked. Editing the file to escape early
gets you a locked screen, not an early release.

## Administrator (Windows)

```powershell
.\.venv\Scripts\pip install -r requirements.txt -r requirements-admin.txt
.\.venv\Scripts\pip install -e .

.\.venv\Scripts\python -m admin --check-qml   # loads every QML file, no window
.\.venv\Scripts\python -m admin --engine 10.0.0.5
```

`--check-qml` renders nothing and exits — the fastest way to confirm a QML edit
before opening a window.

The address that actually connects is remembered in QSettings, so `--engine` is
only needed the first time or to override.

## Development launcher

On a machine with all three checked out, `labmonitor.py` dispatches to any of
them without remembering module paths. It is a dev convenience and is not
deployed:

```powershell
python labmonitor.py                       # list everything
python labmonitor.py engine --check
python labmonitor.py client --once
python labmonitor.py admin  --check-qml
python labmonitor.py dialog --message "Test" --timeout 15
python labmonitor.py certs
python labmonitor.py initdb
```

Each subcommand imports its component lazily, so `labmonitor.py engine` never
pulls in PySide6.

> `labmonitor.py overlay` takes over the primary display and disables Task
> Manager. It closes at its `--until` time and always restores the policy on
> exit, including on a crash — but do not run it on a machine someone is using.

## Verifying end to end

Bring the three up in order and confirm each before starting the next:

1. **Engine** — `python3 -m engine -v`; it logs its listen address, transport
   mode and auth posture.
2. **Client** — `python -m client --engine <addr> -v`; the Engine logs a
   registration, then heartbeats every 15s.
3. **Administrator** — `python -m admin --engine <addr>`; the client appears in
   the roster and live telemetry starts filling the dashboard.

Then exercise a round trip: select the client, terminate a harmless process, and
confirm it appears in Reports → command history.

## Configuration reference

Every flag sets an environment variable, and the variable works on its own. The
flags exist because config is read at import time, so they are applied to the
environment before the component loads.

| Variable | Unit | Flag |
|---|---|---|
| `ENGINE_HOST` / `ENGINE_PORT` | all | `--host`/`--port`, `--engine`/`--port` |
| `ENGINE_DB` | engine | `--db` |
| `ENGINE_RETENTION_DAYS` | engine | `--retention-days` |
| `ENGINE_OUTBOX_TTL` | engine | — |
| `ENGINE_TLS` / `CLIENT_TLS` / `ADMIN_TLS` | each | `--no-tls` |
| `CLIENT_ID` / `ADMIN_ID` | client / admin | `--id` |
| `*_LOG_LEVEL` | each | `-v` |
| `DEV_BYPASS_AUTH` | engine | `--dev-bypass-auth` |

## Before deploying to real machines

- **Authentication is not finished.** `verify_challenge_response` accepts any
  response, so anyone on the network can register as any client or as an admin.
  Run this on an isolated or trusted network until that lands.
- **Get institutional sign-off.** The system captures screenshots on demand,
  logs USB insertions, records every running application and window title, and
  can lock a user out of a machine. Most institutions require ethics review or
  IT approval before that points at computers real students use.
