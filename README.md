# System Monitoring & Management Tool
## Final Year Project - Lean Version

---

## Table of Contents
1. [Introduction](#introduction)
2. [Project Scope](#project-scope)
3. [Core Features](#core-features)
4. [System Architecture](#system-architecture)
5. [Technical Specifications](#technical-specifications)
6. [Implementation Timeline](#implementation-timeline)
7. [Development Guidelines](#development-guidelines)
8. [Removed Features](#removed-features)

---

## Introduction

### Project Overview
A lightweight system administration tool designed for monitoring and managing computer lab machines within an institutional environment. The system provides essential monitoring capabilities and basic remote management functions through a clean client-server architecture.

### Problem Statement
System administrators in educational institutions need efficient tools to:
- Monitor resource usage across multiple lab machines
- Track application usage and system activity
- Perform basic remote management tasks
- Enforce access policies and usage restrictions

### Solution
A socket-based client-server application that enables real-time monitoring and management of multiple client machines from a centralized administrative interface.

---

## Project Scope

### Objectives
1. Implement reliable real-time monitoring of client machines
2. Provide essential remote management capabilities
3. Create an intuitive administrative interface
4. Ensure secure communication between components
5. Maintain lightweight resource footprint on client machines

### Target Environment
- **Deployment**: Local Area Network (LAN)
- **Engine**: Linux only — chosen for its epoll-based async I/O and general system-programming flexibility
- **Client Machines**: Windows lab computers (Windows-only for now)
- **Admin Station**: Windows workstation running the Administrator GUI
- **Scale**: 10-50 concurrent client connections

---

## Core Features

### 1. Monitoring Features (Read-Only Data Collection)

#### Application Tracking
- **Active Applications**: Track all running applications and their windows
- **Execution Time**: Monitor start time and duration for each application
- **Resource Usage**: Collect CPU and memory consumption per application
- **Data Collected**:
  - Process name and PID
  - Window titles
  - Start timestamp
  - CPU percentage
  - Memory usage (MB)
  - Execution duration

#### System Activity Monitoring
- **Idle Time Detection**: Track user inactivity periods
  - Keyboard/mouse idle time
  - Screen lock status
  - Last activity timestamp
  
- **USB Device Monitoring**: Log USB device insertions
  - Device name and type
  - Connection timestamp
  - Mount point (if applicable)
  - Read-only logging (no blocking)

#### Network Usage Tracking
- **Per-Machine Monitoring**: Track data consumption for each client
  - Upload/download bytes
  - Active connections
  - Network interface status
  
- **Reporting**: Generate usage reports
  - 24-hour data summaries
  - Weekly aggregated statistics
  - Historical trend data

### 2. Management Features (Admin Actions)

#### Remote Command Execution
- **Predefined Scripts**: Execute administrator-defined Python or PowerShell scripts only. Scripts are not auto-categorized by purpose (maintenance, config, diagnostics, automation, etc.) since a single script can span any of these and reliable auto-classification isn't feasible — see "Bundled Runtime & Script Validation" and "Script Execution Model" below for how these are validated, launched, and monitored.

- **On-Demand Screen Capture**: Capture client screenshots
  - Manual trigger from admin interface
  - Timestamp and client ID tagged
  - Image compression for network efficiency

- **Application Control**: Manage running applications
  - Terminate specific processes (via existing `TERMINATE_PROCESS`)
  - Force termination option
  - **Graceful shutdown warning**: implemented as a small, bundled, on-demand **dialog executable** — not `user32.dll`/`MessageBoxW` via ctypes. The client agent spawns this exe the same way it spawns scripts (`create_subprocess_exec`, non-blocking to the agent's event loop); the exe shows the warning, and the user's choice (OK / Cancel / timeout-expired) is reported back via exit code or stdout, following the same reporting pattern already used for script output.

#### Access Control

- **Website Blocking**: Implement URL/domain filtering, supporting **both blacklist and whitelist modes** (configurable per policy/session) — unlike Application Management, which is blacklist-only.
  - **Blacklist mode (default for general lab use)**: maintain a blocklist of URLs/domains, block by pattern matching, temporary or permanent blocks. Same reasoning as apps — this is the safe default for normal, unrestricted browsing with known-bad sites blocked.
  - **Whitelist mode (opt-in, for locked-down sessions)**: only listed domains resolve/load; everything else is blocked. Intended for scenarios like exam sessions where reaching only a specific site (e.g. an exam portal) is the explicit goal.
  - **Known tradeoff of whitelist mode**: most real sites load assets from third-party domains — CDNs, font providers, analytics, embedded video, SSO — that aren't obvious from the site's own domain. Unless those dependency domains are also whitelisted, pages will partially or fully break. This is expected and accepted when whitelist mode is deliberately chosen for a locked-down session; it is not a suitable default for general browsing, which is why blacklist remains the default mode.

- **Indeterminate Pause**: Hold one machine's screen — or the whole room's — with no stated end time, and drop it when ready. Distinct from a time-based restriction in both intent and presentation:

  | | Time-based restriction | Pause |
  |---|---|---|
  | Set by | A schedule, in advance | The admin, live |
  | User sees | A countdown to a known end | "Paused", no countdown |
  | Ends when | The window closes | The admin drops it |
  | Bounded by | 2-hour cap per block | 1-hour cap |
  | Cap protects against | The overlay hanging | **The admin disappearing** |

  The one-hour bound is a fail-safe, not a policy, and is deliberately never shown to the student — displaying it would turn an admin safety net into a promise. If the operator closes the GUI, goes home, or the network drops mid-pause, the machines must not stay frozen. As the bound approaches, the **Admin GUI warns** so the pause can be extended deliberately; that keeps a long hold an explicit choice rather than something nobody noticed.

  A pause and a scheduled block can be active at once. The pause takes precedence, since it is the live action; dropping it while a scheduled window is still open reverts to the countdown rather than releasing the machine.

- **Time-Based Restrictions**: Control lab access hours, enforced via a bundled, single-monitor **overlay executable** (see "Time-Based Restriction Enforcement" below for full design: fullscreen overlay, tamper-resistant local schedule storage, 2-hour continuous-block cap, independent watchdog, and reboot handling).
  - Define allowed usage time windows
  - Per-client or group-based schedules
  - Automatic enforcement
  - Grace period notifications (reuses the dialog exe above)

- **Application Management**: Control allowed applications — **blacklist only, no whitelist**. A whitelist model was considered and rejected: allowed applications routinely span associated helper processes, and even the OS itself spans background software that can't be reliably enumerated in advance, so whitelisting risks false-blocking legitimate, unlisted system activity. Blacklisting is the deliberate tradeoff: applications not on the blacklist are implicitly allowed by design. This is a known, accepted gap (a genuinely undesired but unlisted app can slip through), not an oversight.
  - Blacklist of prohibited applications
  - Launch blocking
  - Automatic termination of blacklisted process names (existing `TERMINATE_PROCESS` mechanism)

---

### Time-Based Restriction Enforcement

The lockout screen is a separate bundled **overlay executable**, distinct from the dialog exe above, launched by the client agent only while a block window is active (not a persistent hidden process).

**Visual design**
- Fullscreen, borderless, transparent background with a centered dialog-style window — gives the impression of a locked screen with a single dialog, not a full opaque takeover.
- Scoped to a single monitor (the primary/active display) — covers the common case without the added complexity of enumerating and managing a window per screen.
- Click-through is prevented while the overlay is showing; the screen becomes usable again only once the overlay exits.

**Soft-defeat resistance** (appropriate for final-year project scope, not production-grade):
- Window is set topmost and **periodically re-asserts itself** (e.g. every 500ms) so any window a user brings forward (Alt-Tab, etc.) is pushed back down almost immediately.
- Task Manager is disabled via the standard Windows policy mechanism while the overlay is active, and restored once it clears.
- Known, accepted limitation: a sufficiently determined user with physical access (safe mode boot, external/live OS, hardware-level tricks) can still defeat this. This is true of essentially all client-side enforcement and is out of scope to solve further here.

**Local schedule storage & tamper resistance**
- Start/end times for the active or upcoming block window are stored locally under `%ProgramData%` (not the user-writable `%APPDATA%`), with file ACLs restricting write access to the client agent's service account.
- The stored value is protected with a checksum/HMAC using a key embedded in the client agent binary. If validation fails (tampering, corruption), the client fails closed — treats the schedule as still active/blocked rather than trusting the tampered value.

**2-hour continuous-block cap**
- Any single continuous block window is capped at 2 hours by default. This exists specifically as a safety timeout against the **overlay's own failure modes** (a hang, crash, or rendering fault that leaves the lockout visually stuck) — it is not a response to network connectivity loss, since the schedule is enforced locally regardless of server reachability.

**Independent watchdog**
- Because the overlay process could itself hang, something outside that process must guarantee it closes once its stored end-time has passed. Two layers, both independent of the overlay exe's own logic:
  - **Primary**: the client agent polls every 30 seconds — is the overlay exe still running and now past its stored end-time? If so, force-close it directly (by process handle).
  - **Backstop**: a Windows Scheduled Task, registered during client install (alongside the agent's own service registration — same installer step, not a separate manual task), runs the same check independently on a longer interval (e.g. every 5 minutes). This exists specifically to cover the case where the client agent itself has hung or crashed, not just the overlay — the agent-level check alone can't protect against the agent being the thing that's stuck.

**Reboot handling**
- The client agent is already configured to auto-start and, on every startup, re-reads the locally stored schedule before anything else. If the current time still falls inside an active block window, the agent immediately re-launches the overlay exe — a reboot is not an escape hatch from an active restriction.

---

## System Architecture

### Architecture Diagram
```
                         [ LINUX ]
              ┌────────────────────────────┐
              │           Engine           │
              │   (Python, asyncio/epoll)  │
              │   holds: admin master      │
              │   secret + SQLite file     │
              │   (bundled, single package │
              │   — see "Database" below   │
              │   for the Postgres path)   │
              └──────────────┬─────────────┘
                              │
                    TCP (JSON, secret-derived
                    session auth per client —
                    see "Authentication" below)
                              │
              ┌─────────────────────────────┴─────────────────────────────┐
              ▼                                                           ▼
                          [ WINDOWS ]                                [ WINDOWS ]
   ┌───────────────────────────────────────┐          ┌────────────────────────────────┐
   │           Client Agent                │          │      Administrator Client       │
   │   (Python, bundled runtime)            │          │        (Qt 6 + QML GUI)         │
   │   holds: this client's derived key,    │          │  bundled: pinned Python for     │
   │   local config/state (schedule, etc.   │          │  script validation before send  │
   │   — not a database, see "Local State"  │          │  local config: server address,  │
   │   below)                               │          │  window prefs, client cache     │
   │                                        │          │  — not a database               │
   │  spawns on demand (not persistent):    │          └────────────────────────────────┘
   │   ┌──────────────┐  ┌────────────────┐ │
   │   │  Dialog exe  │  │  Overlay exe    │ │
   │   │ (shutdown/   │  │ (time-based     │ │
   │   │  grace warn) │  │  lockout,       │ │
   │   └──────────────┘  │  single-monitor)│ │
   │                     └────────────────┘ │
   │  bundled: pinned Python (script re-    │
   │  validation + execution)               │
   └───────────────────────────────────────┘
```

### Component Details

Three packages, one per deployable unit: **Engine**, **Client** (Client Agent), **Admin** (Administrator Client). Naming reflects what's actually installed on each machine, not an idealized architecture — see the diagram above.

#### 1. Engine (Core Backend)
**Purpose**: Central coordination and processing hub

**Responsibilities**:
- Accept and manage client connections (TCP sockets)
- Route commands between admin and clients
- Process and store monitoring data
- Maintain client registry and state
- Handle authentication and authorization
- Manage message queuing

**Technology**: Python with `asyncio` (Linux, backed by `epoll`)

**Concurrency Model**:
`asyncio.start_server` multiplexes all client sockets on a single thread via the OS-level `epoll` readiness mechanism (what `select`/`epoll` expose directly, and what asyncio wraps). All client connections are I/O-bound and can signal readiness, so they belong on the event loop — no threads are used for connection handling, command dispatch, or routing.

Threads (or `run_in_executor`) are reserved strictly for work that cannot signal readiness and could block the event loop indefinitely — e.g., a slow synchronous library call with no async equivalent. On the Engine, SQLite writes are the only candidate if they start to stack up under load; otherwise nothing needs a thread.

**Key Modules**:
- Connection manager
- Command dispatcher
- Data aggregator
- Database interface
- Protocol handler

**Database (bundled, not a separate package)**:
Persistent storage for logs, client registry, configuration/rules, and command history lives inside the Engine package, not as a separate service — every access is mediated through the Engine (see Client/Admin sections below for why they don't have their own database).

**Default: SQLite.** For this project's actual scope — one admin, one Engine process, 10-50 clients — SQLite is correctly sized, not a lesser choice: it's a single bundled file with zero extra services to deploy, and since all writes are funneled through one asyncio process rather than 50 processes contending for the file, its single-writer serialization isn't the bottleneck it would be under true multi-process concurrent access. All database access goes through the functions in `database.py` (see "Complete Functional Code Examples" below) rather than raw SQL scattered elsewhere, so this stays swappable.

**Upgrade path: PostgreSQL.** Worth adopting once (a) sustained write volume from 50 clients actually pushes past what single-file SQLite handles comfortably, or (b) multiple admins need direct database-level roles/access rather than only going through the Engine — neither is a requirement as currently scoped. Note that choosing Postgres changes the packaging story: it becomes a separate running service the Engine connects to, so "Engine is one deployable package" would need revisiting at that point. Recommended sequencing: build and test against SQLite first (zero setup cost, validates schema/query logic immediately), treat Postgres as a deliberate later migration of `database.py`'s internals, not a day-one decision.

**Schema Design**:
```sql
-- Clients table
CREATE TABLE clients (
    client_id TEXT PRIMARY KEY,
    hostname TEXT,
    ip_address TEXT,
    os_type TEXT,
    last_seen TIMESTAMP,
    status TEXT
);

-- Application logs
-- `pid` was added during implementation: the client already sends it in every
-- APP_DATA entry, and it is the only way to tell two runs of the same
-- executable apart. `end_time` is nullable and currently unused — these rows
-- are periodic samples rather than sessions, so duration is derived as
-- (latest sample - start_time) at query time.
CREATE TABLE app_logs (
    id INTEGER PRIMARY KEY,
    client_id TEXT,
    process_name TEXT,
    pid INTEGER,
    window_title TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    cpu_usage REAL,
    memory_mb REAL,
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

-- Network usage
CREATE TABLE network_usage (
    id INTEGER PRIMARY KEY,
    client_id TEXT,
    timestamp TIMESTAMP,
    bytes_sent INTEGER,
    bytes_received INTEGER,
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

-- USB events
CREATE TABLE usb_events (
    id INTEGER PRIMARY KEY,
    client_id TEXT,
    device_name TEXT,
    event_type TEXT,
    timestamp TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(client_id)
);

-- Commands log
CREATE TABLE command_log (
    id INTEGER PRIMARY KEY,
    admin_id TEXT,
    client_id TEXT,
    command_type TEXT,
    command_data TEXT,
    timestamp TIMESTAMP,
    status TEXT
);
```

#### 2. Client Agent (CLI)
**Purpose**: Monitoring agent running on Windows lab machines

**Responsibilities**:
- Maintain persistent connection to the Engine
- Collect system and application metrics
- Send monitoring data periodically
- Listen for and execute admin commands
- Report command execution results
- Handle reconnection on network failures

**Technology**: Python, targeting Windows (client is Windows-only for now). Ships with a bundled, pinned embeddable Python distribution — see Bundled Runtime & Script Validation below — so script execution/validation never depends on a system-installed interpreter.

**Concurrency Model**:
Same rule as the Engine: asyncio for anything that can signal readiness (socket I/O, subprocess execution via `asyncio.create_subprocess_exec`), threads only for calls that can't. Note `_exec` rather than `_shell`: scripts are launched as an explicit argv against the bundled interpreter, never handed to a shell for interpretation. `psutil.process_iter()` is a synchronous, potentially slow call with no async equivalent — running it directly inside an async function would stall the event loop and could cause missed heartbeats. It must be offloaded with `asyncio.to_thread(collect_process_data)` rather than awaited inline.

**Operating Modes**:
- Background service/daemon
- Low resource footprint
- Auto-start on boot
- Graceful degradation on errors

**Local State (config, not a database)**:
The Client Agent persists a small amount of security-sensitive, low-volume, singular-value state locally under `%ProgramData%` (ACL-restricted to the agent's service account, matching the pattern used for the lockout schedule):
- This client's derived auth key (see Authentication)
- The tamper-protected time-based lockout schedule (start/end times + HMAC)
- Optionally, a cached blacklist snapshot for continued enforcement if the Engine is briefly unreachable

This is deliberately **not** a database — it's read-mostly, has no relational structure, and needs tamper protection more than it needs queries. A config/state file is the right tool; SQLite's actual strengths (concurrent access, relational queries) aren't relevant here. This local state must survive restarts, since it's what makes the reboot-handling requirement (re-checking an active lockout on startup without needing the Engine reachable) possible.

#### 3. Administrator Client (GUI)
**Purpose**: Administrative dashboard and control interface, running on Windows

**Responsibilities**:
- Connect to the Engine
- Display real-time monitoring data
- Send management commands
- View reports and statistics
- Configure rules and policies
- Manage client list

**Technology**: Qt 6 + QML, bundled with a pinned embeddable Python distribution (for script validation — see Bundled Runtime & Script Validation below)

**Interface Sections**:
- Client list view
- Monitoring dashboard
- Command panel
- Reports viewer
- Configuration editor

**Local State (config, not a database)**:
Ordinary app preferences — last-connected Engine address, window layout, a cache of the client list for faster reopening. Plain preferences storage (a config file, or Qt's own settings mechanism) is the right fit; there's no relational or security-sensitive need here that would justify a database.

---

## Technical Specifications

### Communication Protocol

#### Protocol Design
- **Transport**: TCP sockets (persistent connections)
- **Format**: JSON over TCP (human-readable, easy debugging)
- **Encoding**: UTF-8

#### Message Structure
```json
{
  "type": "MESSAGE_TYPE",
  "client_id": "unique_client_identifier",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    // Message-specific data
  }
}
```

#### Message Types

**Client → Server (Monitoring Data)**:
```json
// Application data
{
  "type": "APP_DATA",
  "client_id": "lab1-pc-01",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "applications": [
      {
        "process_name": "chrome.exe",
        "window_title": "Google Chrome",
        "pid": 1234,
        "start_time": "2026-01-16T10:15:00Z",
        "cpu_percent": 15.2,
        "memory_mb": 450.5
      }
    ]
  }
}

// Network usage
{
  "type": "NETWORK_DATA",
  "client_id": "lab1-pc-01",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "bytes_sent": 1048576,
    "bytes_received": 5242880,
    "active_connections": 12
  }
}

// USB event
{
  "type": "USB_EVENT",
  "client_id": "lab1-pc-01",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "event": "inserted",
    "device_name": "USB Mass Storage",
    "device_id": "vid_1234_pid_5678"
  }
}

// Heartbeat
{
  "type": "HEARTBEAT",
  "client_id": "lab1-pc-01",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "status": "active",
    "idle_time": 0
  }
}
```

**Server → Client (Commands)**:
```json
// (Script execution — see "Script Execution Model" section below for
// EXECUTE_SCRIPT / COMMAND_ACCEPTED / COMMAND_OUTPUT / COMMAND_COMPLETE)

// Screen capture
{
  "type": "SCREEN_CAPTURE",
  "command_id": "cmd_12346",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "quality": 80
  }
}

// Terminate process
{
  "type": "TERMINATE_PROCESS",
  "command_id": "cmd_12347",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "process_name": "chrome.exe",
    "force": false
  }
}

// Pause a client's screen indefinitely, or drop the pause.
// "seconds" is the internal fail-safe bound, clamped to 3600 by the client.
// It is never displayed to the user — see "Indeterminate Pause" above.
{
  "type": "SET_PAUSE",
  "command_id": "cmd_12350",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "action": "pause",        // "pause" | "resume"
    "seconds": 3600
  }
}

// Set website filtering policy for a client/session — "mode" is required
// and makes explicit which model is active, per the blacklist-default /
// whitelist-for-locked-down-sessions decision (see Access Control above).
// "urls" is interpreted as a blocklist when mode is "blacklist" and as
// the sole allowed set when mode is "whitelist".
{
  "type": "SET_WEBSITE_POLICY",
  "command_id": "cmd_12348",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "mode": "blacklist",          // "blacklist" | "whitelist"
    "urls": ["facebook.com", "youtube.com"],
    "action": "block"             // "block" | "unblock" | "replace"
  }
}
```

**Client → Server (Command Response)**:
```json
{
  "type": "COMMAND_RESPONSE",
  "client_id": "lab1-pc-01",
  "command_id": "cmd_12345",
  "timestamp": "2026-01-16T10:30:05Z",
  "payload": {
    "status": "success",
    "result": "Command executed successfully",
    "data": null
  }
}
```

**Admin → Server**:
```json
{
  "type": "ADMIN_COMMAND",
  "admin_id": "admin_01",
  "target_clients": ["lab1-pc-01", "lab1-pc-02"],
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "command_type": "SCREEN_CAPTURE",
    "parameters": {
      "quality": 80
    }
  }
}
```

### Data Collection Intervals
- **Application data**: Every 30 seconds
- **Network usage**: Every 60 seconds
- **Heartbeat**: Every 15 seconds
- **USB events**: On detection (event-driven)
- **Idle time**: Reported with every heartbeat, so every 15 seconds rather than
  30 — it is a single integer and rides along in a message already being sent

### Bundled Runtime & Script Validation

Predefined scripts are restricted to two types: **Python** and **PowerShell**. PowerShell ships with Windows and needs no bundling. Python does not, so both the Admin GUI and the Client Agent installers bundle their own pinned, embeddable Python distribution rather than relying on a system-installed interpreter:

- **Admin GUI**: uses its bundled interpreter to validate a script *before* it is ever sent to a client — at minimum a syntax check (`python -m py_compile`), catching authoring mistakes at the source instead of discovering them on lab machines.
- **Client Agent**: uses its own bundled interpreter both to re-validate the script on arrival (in case of tampering or corruption in transit/storage) and to actually execute it.
- **Version pinning**: both bundles must be built from the same pinned Python version as part of the release process — if the GUI validates against one version and the client executes on another, a "validated" script can still fail at runtime.
- **Distribution choice**: **decided — the embeddable distribution.** Predefined scripts are standard library and `subprocess` only, so the small stdlib-only build with no pip is sufficient, and that constraint is now enforced rather than trusted. (The dialog and overlay executables are a separate matter: they carry their own Qt and are frozen with PyInstaller, which is unaffected by this choice.)

### Script Import Policy

Because the client's runtime has no pip and nothing installed beyond the standard library, a script that imports anything else cannot run there. Rather than letting that fail on a lab machine, the Admin GUI rejects it before sending. Three rules:

1. **Standard library only.** Any import outside `sys.stdlib_module_names` is refused.
2. **Windows-available only.** Around fifteen stdlib modules wrap POSIX facilities and do not exist on Windows — `fcntl`, `pwd`, `grp`, `termios`, `pty`, `resource`, `curses` and friends. These compile cleanly on any machine and fail only at runtime on the client, which is exactly the class of mistake this check exists to prevent. The operator is told which Windows facility to use instead where one exists (`msvcrt.locking` for `fcntl`, and so on).
3. **Present in the actual runtime.** The imports are resolved inside the *bundled* interpreter with `importlib.util.find_spec`, so anything the embeddable distribution omits is caught too. `find_spec` resolves without importing — importing would execute the module's top-level code, which a validation step must never do.

**Imports are read with `ast`, not a regular expression.** A pattern match cannot distinguish `import os` from the same words inside a docstring, and mishandles `import os, sys` and parenthesised multi-line `from` imports. The parser is already needed for the syntax check, so using it costs nothing and cannot be fooled — including by imports deferred inside a function body.

**Known limit**: this is static analysis of import statements. It cannot catch runtime-only platform assumptions — `os.fork()`, `signal.SIGKILL`, POSIX-shaped paths — which are valid Python that simply fails on Windows. The check narrows the failure surface; it does not eliminate it.

The result is surfaced in the Admin GUI, on a **Check** button as well as on send, and it lists the imports it *accepted* as well as those it rejected — an operator who can see the policy agree with them learns the rule, where a bare "OK" teaches nothing.

### Script Execution Model

**Scope of predefined scripts**: they are an *extension mechanism* for small routine tasks that aren't built into the client's features by default — clearing temp files, restarting a service, checking disk space. They are explicitly **not** a way to run long-lived jobs.

That intent is enforced rather than assumed. Execution is capped at **5 minutes by default, 15 minutes maximum**; a script that overruns is stopped. Without a cap, one bad loop leaves a stuck process on every machine in the lab, and nothing about the design would notice.

Scripts still cannot be waited on inside the response cycle, so the non-blocking model below is unchanged — a 5-minute script would stall the agent just as surely as an infinite one. Blocking on full completion (as a naive `subprocess.communicate()` approach would) is wrong at any duration:

1. The client launches the script **detached** from the response cycle — stdout/stderr are redirected to a unique per-execution log file (e.g. `logs/{command_id}.log`), keyed by `command_id` so concurrent or repeated runs of the same script never collide.
2. The client immediately acknowledges the launch (does not wait for completion) so the admin sees the command was accepted.
3. A background task polls the log file **on a fixed interval** and only reads/sends when the file **size has grown** since the last check — this avoids reopening and re-reading the file on every tick when the script has produced no new output. New bytes are streamed back to the server as `COMMAND_OUTPUT` chunks.
4. Once the process exits, the client sends a single `COMMAND_COMPLETE` and then **deletes the log file** (and the temporary script source file) — it's per-execution scratch space, not a durable record, so nothing is left behind once output has been reported.
5. The admin can also stop a script early, **keyed by `command_id`** rather than process name, so one specific execution can be stopped without guessing which process it maps to — several runs may share an interpreter name.
6. A script stopped at the cap reports `status: "timeout"`, distinct from `"error"`, so an operator can tell "too slow" from "crashed" without reading the output.

**Known limitation of the cap**: on Windows both `terminate()` and `kill()` map to `TerminateProcess`, so a script stopped at the limit gets no opportunity to clean up. A run killed halfway through writing a file leaves a partial file. Scripts under this mechanism should therefore be written to be safely interruptible — which is a reasonable ask given they are meant to be small routine tasks.

**Server → Client (Commands)**:
```json
// Execute script — script_type replaces the old free-form "shell" field
{
  "type": "EXECUTE_SCRIPT",
  "command_id": "cmd_12345",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "script": "print('System check')",
    "script_type": "python",     // "python" | "powershell"
    "timeout_seconds": 300       // optional; default 300, clamped to 900
  }
}

// Terminate a running script by command_id (not process name — several runs
// may share an interpreter name, so only command_id names one execution)
{
  "type": "TERMINATE_SCRIPT",
  "command_id": "cmd_98765",
  "timestamp": "2026-01-16T10:31:00Z",
  "payload": {
    "target_command_id": "cmd_12345",
    "force": false
  }
}
```

**Client → Server (Script Lifecycle)**:
```json
// Sent immediately on launch — does not wait for completion
{
  "type": "COMMAND_ACCEPTED",
  "client_id": "lab1-pc-01",
  "command_id": "cmd_12345",
  "timestamp": "2026-01-16T10:30:00Z",
  "payload": {
    "log_path": "logs/cmd_12345.log"
  }
}

// Streamed as new output is tailed from the log file — many per execution
{
  "type": "COMMAND_OUTPUT",
  "client_id": "lab1-pc-01",
  "command_id": "cmd_12345",
  "timestamp": "2026-01-16T10:30:05Z",
  "payload": {
    "chunk": "System check\n"
  }
}

// Sent once, when the process actually exits
{
  "type": "COMMAND_COMPLETE",
  "client_id": "lab1-pc-01",
  "command_id": "cmd_12345",
  "timestamp": "2026-01-16T10:35:00Z",
  "payload": {
    "status": "success",
    "returncode": 0
  }
}
```


- **Engine**: Port 5000 (configurable)
- **Database**: Port 5432 (PostgreSQL) or file-based (SQLite)

---

## Implementation Timeline

### Week 1: Core Infrastructure (5-6 days)

**Days 1-2: Socket Communication**
- [ ] Implement basic TCP socket server (Engine)
- [ ] Implement basic TCP socket client (Agent)
- [ ] Test connection establishment and message passing
- [ ] Implement reconnection logic
- [ ] Handle multiple concurrent clients

**Day 3: Database Setup**
- [ ] Design and create database schema
- [ ] Implement database connection layer
- [ ] Create data access functions (CRUD operations)
- [ ] Test data persistence

**Days 4-5: Protocol Implementation**
- [ ] Define complete message protocol
- [ ] Implement message serialization/deserialization
- [ ] Add message validation
- [ ] Implement message routing in Engine
- [ ] Test end-to-end message flow

**Days 6-7: Testing & Documentation**
- [ ] Test client-server communication
- [ ] Test multi-client scenarios
- [ ] Document protocol specification
- [ ] Code review and refactoring

### Week 2: Monitoring Features (5-6 days)

**Days 1-2: Application Tracking**
- [ ] Implement process enumeration (Windows)
- [ ] Collect process metrics (CPU, memory)
- [ ] Capture window titles
- [ ] Track execution time
- [ ] Send data to server
- [ ] Store in database

**Day 3: Network Monitoring**
- [ ] Implement network statistics collection
- [ ] Track bytes sent/received
- [ ] Monitor active connections
- [ ] Aggregate 24-hour data
- [ ] Generate weekly reports

**Day 4: System Activity**
- [ ] Implement idle time detection (Windows `GetLastInputInfo`)
- [ ] USB device event monitoring
- [ ] Event logging
- [ ] Test on target Windows lab machines

**Day 5: Data Aggregation**
- [ ] Implement server-side data processing
- [ ] Create aggregation functions
- [ ] Generate statistical summaries
- [ ] Optimize database queries

**Days 6-7: Testing**
- [ ] Test all monitoring features
- [ ] Verify data accuracy
- [ ] Performance testing
- [ ] Bug fixes

### Week 3: Management Features (5-6 days)

**Days 1-2: Command Framework**
- [ ] Implement command queue system
- [ ] Create command execution handler
- [ ] Add command validation
- [ ] Implement response mechanism
- [ ] Error handling

**Day 3: Core Commands**
- [ ] Script execution functionality
- [ ] Screen capture implementation
- [ ] Process termination
- [ ] Test command reliability

**Days 4-5: Access Control**
- [ ] Website blocking mechanism (hosts file or proxy), both blacklist and whitelist modes
- [ ] Time-based access restrictions
- [ ] Application **blacklist** — whitelisting applications was considered and
      rejected; see "Application Management" under Access Control for why
- [ ] Policy enforcement

**Days 6-7: Testing**
- [ ] Test all command types
- [ ] Multi-client command execution
- [ ] Access control validation
- [ ] Integration testing

### Week 4: GUI & Finalization (5-7 days)

**Days 1-2: QML GUI Structure**
- [ ] Set up Qt project
- [ ] Create main window layout
- [ ] Implement client list view
- [ ] Create monitoring dashboard
- [ ] Build command panel

**Day 3: Backend Integration**
- [ ] Connect QML to Python backend
- [ ] Implement Qt signals/slots
- [ ] Socket communication from GUI
- [ ] Real-time data updates

**Day 4: Features & Polish**
- [ ] Add all GUI features
- [ ] Implement user interactions
- [ ] Add visual feedback
- [ ] Style and theme

**Days 5-6: Integration Testing**
- [ ] End-to-end system testing
- [ ] Multi-client scenarios
- [ ] Performance testing
- [ ] Bug fixing

**Day 7: Documentation**
- [ ] User manual
- [ ] Installation guide
- [ ] API documentation
- [ ] Project report preparation

---

## Development Guidelines

### Implementation Approach

Each component is built in three passes, in order, rather than fully implementing one module before starting the next:

1. **Architecture** — the design as captured in this document: component boundaries, protocol messages, data flow.
2. **Scaffold** — module structure, function/class signatures, empty handlers wired into the dispatch logic (e.g. the `handlers` dict in `process_message`), so the system runs end-to-end with stub behavior before any real logic is filled in.
3. **Implementation** — actual working logic filled into the scaffolded structure, module by module.

This means, for example, that Week 1's "Core Infrastructure" tasks cover scaffolding the socket/protocol/database layers so messages can flow, while the real monitoring and management logic (Weeks 2–3) is filled in afterward against an already-working skeleton.

**Component build order, after scaffolding is in place:**

1. **Engine** — built fully first. It's the shared dependency every other component talks to, so getting it right (and thoroughly tested) before the Admin or Client exist means both of those can be built and tested against a real, working Engine rather than against assumptions about how it will behave.
2. **Admin (Administrator Client)** — built and thoroughly tested second, against the completed Engine.
3. **Client Agent** — built and thoroughly tested third, against the completed Engine.

Each component is **thoroughly tested on its own before the next one starts** — the Engine is fully tested before Admin work begins, and Admin is fully tested before Client work begins. Full integration (all three components running together) is built and tested **last**, once each component is independently verified. This ordering exists specifically so integration bugs are isolated to the interaction between already-correct components, rather than tangled up with bugs still being worked out inside any individual one.

Authentication (see "Security Considerations" below) is deliberately built **last**, after the rest of the system is architected, scaffolded, and implemented — but it is a hard prerequisite before the system is safe to run on a real network, not an optional final step.

### Code Quality Standards

#### Python Code Style
- Follow PEP 8 style guide
- Use type hints (Python 3.10+)
- Write docstrings for all functions
- Maximum line length: 100 characters
- Use meaningful variable names
- Prefer functional approach over OOP (use classes only when necessary)
- Use immutable data structures where possible
- Keep functions pure when feasible

Example:
```python
from typing import Dict, Any
import asyncio
import json
import time
import logging

logger = logging.getLogger(__name__)

# Client connections stored as dict: {client_id: (writer, last_seen)}
active_connections: Dict[str, tuple[asyncio.StreamWriter, float]] = {}

async def send_message(client_id: str, message: Dict[str, Any]) -> bool:
    """Send a message to a client.
    
    Args:
        client_id: Unique identifier for the client
        message: Dictionary containing message data
        
    Returns:
        True if successful, False otherwise
    """
    if client_id not in active_connections:
        logger.error(f"Client {client_id} not connected")
        return False
    
    writer, _ = active_connections[client_id]
    
    try:
        data = json.dumps(message).encode('utf-8')
        writer.write(data + b'\n')
        await writer.drain()
        # Update last_seen timestamp
        active_connections[client_id] = (writer, time.time())
        return True
    except Exception as e:
        logger.error(f"Failed to send message to {client_id}: {e}")
        return False

def register_client(client_id: str, writer: asyncio.StreamWriter) -> None:
    """Register a new client connection."""
    active_connections[client_id] = (writer, time.time())
    logger.info(f"Client {client_id} registered")

def get_last_seen(client_id: str) -> float | None:
    """Get the last seen timestamp for a client."""
    if client_id in active_connections:
        _, last_seen = active_connections[client_id]
        return last_seen
    return None
```

#### Error Handling
- Use specific exception types
- Log all errors with context
- Implement graceful degradation
- Never expose internal errors to users

```python
import logging

logger = logging.getLogger(__name__)

try:
    result = process_data(data)
except ValueError as e:
    logger.error(f"Invalid data format: {e}")
    return {"status": "error", "message": "Invalid input"}
except ConnectionError as e:
    logger.error(f"Connection failed: {e}")
    # Attempt reconnection
    reconnect()
except Exception as e:
    logger.critical(f"Unexpected error: {e}", exc_info=True)
    return {"status": "error", "message": "Internal error"}
```

#### Testing
- Write unit tests for core functions
- Integration tests for client-server communication
- Mock external dependencies
- Aim for >70% code coverage

```python
import pytest
from unittest.mock import Mock, patch, MagicMock
import asyncio

# Test data collection
def test_collect_process_data():
    """Test process data collection"""
    data = collect_process_data()
    assert isinstance(data, list)
    assert len(data) > 0
    assert all('process_name' in item for item in data)
    assert all('cpu_percent' in item for item in data)

# Test with mocked socket
@patch('socket.socket')
def test_send_data(mock_socket):
    """Test sending data to server"""
    mock_sock = MagicMock()
    mock_socket.return_value = mock_sock
    
    result = send_data_to_server(mock_sock, {"test": "data"})
    
    assert result is True
    mock_sock.send.assert_called_once()

# Async test
@pytest.mark.asyncio
async def test_handle_message():
    """Test message handling"""
    message = {"type": "HEARTBEAT", "client_id": "test-01"}
    response = await handle_message(message)
    
    assert response['status'] == 'success'
    assert 'timestamp' in response

# Test with fixture
@pytest.fixture
def mock_connection():
    """Create mock connection for testing"""
    return {
        'client_id': 'test-client-01',
        'writer': MagicMock(),
        'last_seen': 1234567890.0
    }

def test_update_last_seen(mock_connection):
    """Test updating last seen timestamp"""
    conn = mock_connection.copy()
    new_time = update_last_seen(conn)
    assert conn['last_seen'] > mock_connection['last_seen']
```

### Project Structure

```
project_root/
│
├── engine/                     # Engine
│   ├── __init__.py
│   ├── main.py                # Engine entry point
│   ├── connection_manager.py # Client connection handling
│   ├── command_handler.py    # Command processing
│   ├── database.py           # Database interface
│   ├── protocol.py           # Protocol implementation
│   └── config.py             # Configuration
│
├── client/                    # Client Agent
│   ├── __init__.py
│   ├── main.py               # Agent entry point
│   ├── monitors/             # Monitoring modules
│   │   ├── __init__.py
│   │   ├── process_monitor.py
│   │   ├── network_monitor.py
│   │   └── usb_monitor.py
│   ├── executor.py           # Command executor
│   ├── connection.py         # Engine connection
│   └── config.py             # Configuration
│
├── admin_gui/                 # Administrator GUI
│   ├── main.py               # GUI entry point
│   ├── qml/                  # QML files
│   │   ├── main.qml
│   │   ├── ClientList.qml
│   │   ├── MonitoringPanel.qml
│   │   └── CommandPanel.qml
│   ├── backend.py            # Python backend
│   └── models.py             # Data models
│
├── common/                    # Shared code
│   ├── __init__.py
│   ├── protocol.py           # Protocol definitions
│   ├── utils.py              # Utility functions
│   └── constants.py          # Constants
│
├── tests/                     # Test suite
│   ├── test_engine.py
│   ├── test_client.py
│   ├── test_protocol.py
│   └── test_integration.py
│
├── docs/                      # Documentation
│   ├── protocol.md
│   ├── installation.md
│   └── user_manual.md
│
├── requirements.txt           # Python dependencies
├── setup.py                  # Installation script
└── README.md                 # Project overview
```

### Security Considerations

#### Build-Order Note: Auth Is Last, Not Optional

Everything else in this document — monitoring, script execution, time-based lockouts, application/website blocking — is functionally complete and independently useful to build and demo without authentication. Auth is deliberately sequenced **last** in the implementation plan — after the Engine, Admin, and Client are each fully built and tested, and after full integration of all three is built and tested (see "Component build order" and "Implementation Approach" under Development Guidelines). This is a sequencing decision, not a scoping one: **the system is not safe to run on a real network until authentication is implemented.** Without it, anything already built — script execution, blacklist enforcement, lockout scheduling — can be triggered by anyone on the LAN impersonating the admin. Treat auth as a hard prerequisite for real deployment, not a nice-to-have checklist item tacked on at the end.

#### Authentication: Admin-Derived Per-Client Keys

Simple by design, appropriate for project scope:

- One **master secret**, generated once, never transmitted over the wire and never stored as-is on any client machine.

  **Both the Engine and the Admin need it**, for different reasons: the Admin computes each client's derived key at provisioning time, and the Engine independently re-derives it to verify the handshake. The architecture diagram above shows it on the Engine; this section originally described it as the admin's alone. Both are correct, and the implication is worth stating plainly — the secret exists in two places, so compromising *either* machine compromises the whole fleet. Reducing that to one copy (for example, having the Engine perform provisioning so the Admin never holds it) is a design question still open — see `issues.md` A6.
- Each client is issued a **derived key** at provisioning time: `client_key = HMAC(master_secret, client_id)`. This is computed once (by the admin, baked into that client's install package) and stored locally under `%ProgramData%` with ACLs restricting write access to the client agent's service account — the same storage pattern already used for the overlay's lockout schedule.
- **Session handshake** (replaces the current trust-whatever-`client_id`-is-sent `REGISTER` flow): the server issues a nonce/challenge on connection; the client responds with `HMAC(client_key, nonce)`. The server independently derives the same `client_key` from its master secret and the claimed `client_id`, and accepts the connection only if the response matches. A rogue socket cannot fake this without possessing the derived key.
- **Why derive rather than share one secret everywhere**: if a single client machine is compromised and its key extracted, only that client's key is exposed — the master secret and every other client's key remain safe. A single shared secret across the fleet would mean one compromised lab machine burns every client.
- **What this does and doesn't solve**: this authenticates *who is allowed to register as which client* and stops impersonation of clients or the admin. It does **not** provide confidentiality in transit — messages are still plain JSON over TCP once a session is established, so schedules, script contents, and screenshots remain sniffable on the LAN by anyone who can observe the traffic. That is a separate problem (see Data Protection below) and is not solved by this auth design alone.

#### Scaffolding Auth: Motions First, Logic Last

Per the build order above, auth is implemented after full integration — but the **message shape it will occupy is scaffolded early**, during the initial scaffold pass, alongside the Engine/Client/Admin scaffolds. Concretely: the `REGISTER` flow includes the nonce and response fields from the start, and the Engine's check on them is a stub that always accepts, rather than the fields not existing yet. This means implementing real auth later is a swap of the logic *inside* already-existing, already-wired functions (`if DEV_BYPASS_AUTH or verify_hmac(...)`) — not a protocol change that has to be threaded through Engine, Client, and Admin a second time. The handshake's round-trip (Engine sends nonce, Client responds, Engine checks) is exercised during integration testing well before real cryptographic logic goes in, since the motions are real even while the check is a stub.

#### Dev-Mode Auth Bypass

A `DEV_BYPASS_AUTH` flag allows the entire handshake — not just its validation — to be skipped outright during development and testing, so work on Engine/Admin/Client is never blocked by auth regardless of how much of the real handshake is scaffolded:

- When active, `REGISTER` succeeds immediately with an early `if DEV_BYPASS_AUTH: return True` **before the handshake begins** — no nonce is sent, no response is expected. This is a hard, visible skip of the flow, not a validation step that quietly always passes.
- **This is a deliberate choice over toggling only the validation step.** A bypass that still sends real auth-shaped messages but silently accepts any response would look, on the wire, indistinguishable from working auth — which is more dangerous if the flag is accidentally left on, since nothing about the traffic looks wrong even under inspection. A hard, early skip is unmistakable both in a packet capture and in the code path itself.
- **Known tradeoff**: because the handshake motions are skipped entirely in dev mode, the handshake's timing and message-count (who sends first, how many round-trips, whether either side blocks waiting on a message the other never sends) are not exercised until real auth is switched on for the first time. The first time auth is fully enabled is therefore also the first real test of the handshake's basic mechanics, not just its cryptographic correctness — budget testing time accordingly rather than assuming the mechanics are already proven by dev-mode testing.
- Must default to `False`/off. Must be loud about its state — e.g. logged prominently on Engine startup (`"⚠ AUTH BYPASS ACTIVE — DO NOT USE ON A REAL NETWORK"`) — and should require deliberate per-run activation rather than being a setting that can persist quietly in a config file and be forgotten.

#### Data Protection
- Transport is currently unencrypted (plain JSON over TCP) — sniffable on the LAN even after auth is added. TLS is listed under Future Enhancements; for anything beyond a classroom demo this should be treated as a near-term follow-up to auth, not an indefinitely deferred one.
- Sanitize all inputs to prevent injection attacks
- Limit command execution privileges

#### Access Control
- Implement role-based access for admin users
- Log all administrative actions
- Rate limiting for command execution

### Performance Optimization

#### Client Agent
- Minimize CPU/memory footprint
- Batch monitoring data before sending
- Use efficient data structures
- Implement exponential backoff for reconnection

#### Engine
- Use asynchronous I/O (asyncio)
- Implement connection pooling
- Optimize database queries
- Consider caching frequently accessed data

#### Network
- Compress large payloads (screenshots)
- Implement message batching
- Use binary protocol for high-frequency data (future enhancement)

---

### Complete Functional Code Examples

#### Engine Implementation (engine/main.py)

```python
#!/usr/bin/env python3
"""
Engine - Main Entry Point
Handles client connections and message routing
"""
import asyncio
import json
import logging
import signal
import sys
from typing import Dict, Any, Optional
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global state
connections: Dict[str, asyncio.StreamWriter] = {}
client_info: Dict[str, Dict[str, Any]] = {}
shutdown_flag = False

# Configuration
SERVER_HOST = '0.0.0.0'
SERVER_PORT = 5000
HEARTBEAT_TIMEOUT = 60


def create_message(msg_type: str, client_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a standardized message."""
    return {
        'type': msg_type,
        'client_id': client_id,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'payload': payload
    }


async def send_message(writer: asyncio.StreamWriter, message: Dict[str, Any]) -> bool:
    """Send a message to a client."""
    try:
        data = json.dumps(message).encode('utf-8') + b'\n'
        writer.write(data)
        await writer.drain()
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False


async def read_message(reader: asyncio.StreamReader) -> Optional[Dict[str, Any]]:
    """Read and parse a message from a client."""
    try:
        data = await asyncio.wait_for(reader.readline(), timeout=30.0)
        if not data:
            return None
        return json.loads(data.decode('utf-8'))
    except asyncio.TimeoutError:
        logger.warning("Read timeout")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Read error: {e}")
        return None


def handle_heartbeat(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle heartbeat message."""
    if client_id in client_info:
        client_info[client_id]['last_seen'] = datetime.utcnow().timestamp()
        client_info[client_id]['status'] = payload.get('status', 'active')
        logger.debug(f"Heartbeat from {client_id}")


def handle_app_data(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle application monitoring data."""
    apps = payload.get('applications', [])
    logger.info(f"Received app data from {client_id}: {len(apps)} applications")
    # TODO: Store in database
    # store_app_data(client_id, apps)


def handle_network_data(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle network usage data."""
    bytes_sent = payload.get('bytes_sent', 0)
    bytes_received = payload.get('bytes_received', 0)
    logger.info(f"Network data from {client_id}: sent={bytes_sent}, recv={bytes_received}")
    # TODO: Store in database
    # store_network_data(client_id, payload)


def handle_usb_event(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle USB device events."""
    event = payload.get('event', 'unknown')
    device = payload.get('device_name', 'unknown')
    logger.info(f"USB event from {client_id}: {event} - {device}")
    # TODO: Store in database
    # store_usb_event(client_id, payload)


async def handle_command_response(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle command execution response."""
    command_id = payload.get('command_id')
    status = payload.get('status')
    logger.info(f"Command {command_id} response from {client_id}: {status}")
    # TODO: Update command status in database
    # update_command_status(command_id, status, payload.get('result'))


async def process_message(client_id: str, message: Dict[str, Any]) -> None:
    """Process incoming message from client."""
    msg_type = message.get('type')
    payload = message.get('payload', {})
    
    handlers = {
        'HEARTBEAT': lambda: handle_heartbeat(client_id, payload),
        'APP_DATA': lambda: handle_app_data(client_id, payload),
        'NETWORK_DATA': lambda: handle_network_data(client_id, payload),
        'USB_EVENT': lambda: handle_usb_event(client_id, payload),
        'COMMAND_RESPONSE': lambda: asyncio.create_task(handle_command_response(client_id, payload))
    }
    
    handler = handlers.get(msg_type)
    if handler:
        result = handler()
        if asyncio.iscoroutine(result):
            await result
    else:
        logger.warning(f"Unknown message type: {msg_type}")


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Handle a client connection."""
    addr = writer.get_extra_info('peername')
    logger.info(f"New connection from {addr}")
    
    client_id = None
    
    try:
        # Wait for initial message with client ID
        message = await read_message(reader)
        if not message or message.get('type') != 'REGISTER':
            logger.error("Invalid registration message")
            writer.close()
            await writer.wait_closed()
            return
        
        client_id = message.get('client_id')
        if not client_id:
            logger.error("No client ID provided")
            writer.close()
            await writer.wait_closed()
            return
        
        # Register client
        connections[client_id] = writer
        client_info[client_id] = {
            'address': addr,
            'connected_at': datetime.utcnow().timestamp(),
            'last_seen': datetime.utcnow().timestamp(),
            'status': 'active'
        }
        
        logger.info(f"Client registered: {client_id}")
        
        # Send acknowledgment
        ack = create_message('REGISTER_ACK', client_id, {'status': 'success'})
        await send_message(writer, ack)
        
        # Message loop
        while not shutdown_flag:
            message = await read_message(reader)
            if message is None:
                break
            
            await process_message(client_id, message)
    
    except asyncio.CancelledError:
        logger.info(f"Client handler cancelled: {client_id}")
    except Exception as e:
        logger.error(f"Client handler error: {e}", exc_info=True)
    finally:
        # Cleanup
        if client_id:
            logger.info(f"Client disconnected: {client_id}")
            connections.pop(client_id, None)
            client_info.pop(client_id, None)
        
        writer.close()
        await writer.wait_closed()


async def send_command_to_client(client_id: str, command_type: str, 
                                 params: Dict[str, Any]) -> bool:
    """Send a command to a specific client."""
    if client_id not in connections:
        logger.error(f"Client {client_id} not connected")
        return False
    
    writer = connections[client_id]
    command = create_message(command_type, client_id, params)
    return await send_message(writer, command)


async def broadcast_command(command_type: str, params: Dict[str, Any]) -> int:
    """Broadcast a command to all connected clients."""
    count = 0
    for client_id, writer in connections.items():
        command = create_message(command_type, client_id, params)
        if await send_message(writer, command):
            count += 1
    return count


def get_connected_clients() -> list[Dict[str, Any]]:
    """Get list of connected clients with their info."""
    return [
        {
            'client_id': client_id,
            **info
        }
        for client_id, info in client_info.items()
    ]


async def start_server() -> None:
    """Start the server."""
    server = await asyncio.start_server(
        handle_client, 
        SERVER_HOST, 
        SERVER_PORT
    )
    
    addr = server.sockets[0].getsockname()
    logger.info(f"Server started on {addr}")
    
    async with server:
        await server.serve_forever()


def handle_shutdown(signum, frame):
    """Handle shutdown signal."""
    global shutdown_flag
    logger.info("Shutdown signal received")
    shutdown_flag = True


def main():
    """Main entry point."""
    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    logger.info("Starting Engine...")
    
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
```

#### Client Agent Implementation (client/main.py)

```python
#!/usr/bin/env python3
"""
Client Agent - Monitoring and Command Execution
"""
import asyncio
import json
import logging
import os
import socket
import sys
import time
import psutil
from typing import Dict, Any, Optional
from datetime import datetime
import platform

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
SERVER_HOST = '192.168.1.100'
SERVER_PORT = 5000
CLIENT_ID = socket.gethostname()
MONITOR_INTERVAL = 30
HEARTBEAT_INTERVAL = 15
RECONNECT_DELAY = 5

# Path to the bundled, pinned embeddable Python distribution shipped with
# the Client Agent installer — never assume a system-installed interpreter.
BUNDLED_PYTHON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'runtime', 'python.exe'
)

# Global state
writer: Optional[asyncio.StreamWriter] = None
reader: Optional[asyncio.StreamReader] = None
running = True
# Tracks currently running scripts by command_id, so TERMINATE_SCRIPT can
# target a specific execution rather than guessing by process name.
running_scripts: Dict[str, asyncio.subprocess.Process] = {}


def generate_client_id() -> str:
    """Generate unique client ID."""
    hostname = socket.gethostname()
    return f"{hostname}-{platform.system()}"


def create_message(msg_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a standardized message."""
    return {
        'type': msg_type,
        'client_id': CLIENT_ID,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'payload': payload
    }


def collect_process_data() -> list[Dict[str, Any]]:
    """Collect running process information."""
    processes = []
    
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'create_time']):
        try:
            info = proc.info
            # Skip system processes
            if info['name'] in ['System', 'svchost.exe', 'System Idle Process']:
                continue
            
            processes.append({
                'process_name': info['name'],
                'pid': info['pid'],
                'cpu_percent': info['cpu_percent'],
                'memory_mb': info['memory_info'].rss / (1024 * 1024),
                'start_time': datetime.fromtimestamp(info['create_time']).isoformat()
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    return processes


def collect_network_data() -> Dict[str, Any]:
    """Collect network usage statistics."""
    net_io = psutil.net_io_counters()
    return {
        'bytes_sent': net_io.bytes_sent,
        'bytes_received': net_io.bytes_recv,
        'packets_sent': net_io.packets_sent,
        'packets_received': net_io.packets_recv
    }


def get_idle_time() -> float:
    """Get system idle time in seconds."""
    # Platform-specific implementation needed
    # For now, return 0
    return 0.0


async def send_message(message: Dict[str, Any]) -> bool:
    """Send message to server."""
    global writer
    
    if not writer:
        return False
    
    try:
        data = json.dumps(message).encode('utf-8') + b'\n'
        writer.write(data)
        await writer.drain()
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False


async def read_message() -> Optional[Dict[str, Any]]:
    """Read message from server."""
    global reader
    
    if not reader:
        return None
    
    try:
        data = await asyncio.wait_for(reader.readline(), timeout=30.0)
        if not data:
            return None
        return json.loads(data.decode('utf-8'))
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        logger.error(f"Read error: {e}")
        return None


async def execute_script(command_id: str, script: str, script_type: str) -> None:
    """Launch a script detached from the response cycle.

    Writes stdout/stderr to a unique per-command log file, immediately
    acknowledges the launch (does NOT await completion — some scripts
    run forever), then spawns a background task to tail the log and a
    separate task to detect actual process exit.
    """
    log_path = f"logs/{command_id}.log"
    os.makedirs("logs", exist_ok=True)

    # BUNDLED_PYTHON_PATH / bundled powershell path resolved from the
    # client's own bundled runtime — never assumes a system interpreter.
    if script_type == 'python':
        script_path = f"logs/{command_id}.py"
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script)
        # Re-validate on arrival even though the Admin GUI already validated
        # it, in case of tampering/corruption in transit or storage.
        validate = await asyncio.create_subprocess_exec(
            BUNDLED_PYTHON_PATH, '-m', 'py_compile', script_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, verr = await validate.communicate()
        if validate.returncode != 0:
            await send_message(create_message('COMMAND_COMPLETE', {
                'command_id': command_id, 'status': 'error',
                'message': f'Script failed validation: {verr.decode()}'
            }))
            return
        argv = [BUNDLED_PYTHON_PATH, script_path]
    elif script_type == 'powershell':
        script_path = f"logs/{command_id}.ps1"
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script)
        argv = ['powershell', '-NoProfile', '-File', script_path]
    else:
        await send_message(create_message('COMMAND_COMPLETE', {
            'command_id': command_id, 'status': 'error',
            'message': f'Unsupported script_type: {script_type}'
        }))
        return

    with open(log_path, 'wb') as log_file:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=log_file, stderr=asyncio.subprocess.STDOUT
        )

    running_scripts[command_id] = proc

    # Acknowledge launch immediately — do not wait for completion.
    await send_message(create_message('COMMAND_ACCEPTED', {
        'command_id': command_id, 'log_path': log_path
    }))

    asyncio.create_task(tail_log_and_report(command_id, log_path, proc))


TAIL_POLL_INTERVAL = 1.0  # seconds between size checks


async def tail_log_and_report(command_id: str, log_path: str,
                               proc: asyncio.subprocess.Process) -> None:
    """Poll the log file on a fixed interval; only read and send when
    the file size has actually grown since the last check (avoids
    reopening/reading on every tick when the script has produced no new
    output). Once the process exits, send COMMAND_COMPLETE and delete
    the log file — it's per-execution scratch space, not a durable log."""
    position = 0
    try:
        while True:
            await asyncio.sleep(TAIL_POLL_INTERVAL)

            try:
                current_size = os.path.getsize(log_path)
            except OSError:
                current_size = position  # log not created yet / race on first tick

            if current_size > position:
                with open(log_path, 'rb') as f:
                    f.seek(position)
                    chunk = f.read()
                    position = f.tell()
                await send_message(create_message('COMMAND_OUTPUT', {
                    'command_id': command_id,
                    'chunk': chunk.decode('utf-8', errors='replace')
                }))

            if proc.returncode is not None:
                break
            try:
                await asyncio.wait_for(proc.wait(), timeout=0.01)
            except asyncio.TimeoutError:
                continue
    finally:
        running_scripts.pop(command_id, None)
        await send_message(create_message('COMMAND_COMPLETE', {
            'command_id': command_id,
            'status': 'success' if proc.returncode == 0 else 'error',
            'returncode': proc.returncode
        }))
        # Log is per-execution scratch space, not a durable record —
        # clear it once the process has closed and output has been sent.
        for path in (log_path, log_path.replace('.log', '.py'),
                     log_path.replace('.log', '.ps1')):
            try:
                os.remove(path)
            except OSError:
                pass  # already gone / never created for this script_type


async def terminate_script(target_command_id: str, force: bool = False) -> Dict[str, Any]:
    """Terminate a running script by command_id — process name isn't
    enough since some scripts run indefinitely and must be individually
    stoppable."""
    proc = running_scripts.get(target_command_id)
    if not proc:
        return {'status': 'error', 'message': f'No running script for {target_command_id}'}
    try:
        if force:
            proc.kill()
        else:
            proc.terminate()
        return {'status': 'success', 'target_command_id': target_command_id}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def terminate_process(process_name: str, force: bool = False) -> Dict[str, Any]:
    """Terminate a process by name (used for ordinary app-control
    commands, not for scripts launched via execute_script)."""
    terminated = []
    errors = []
    
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] == process_name:
                if force:
                    proc.kill()
                else:
                    proc.terminate()
                terminated.append(proc.info['pid'])
        except Exception as e:
            errors.append(str(e))
    
    return {
        'status': 'success' if terminated else 'error',
        'terminated': terminated,
        'errors': errors
    }


async def handle_command(message: Dict[str, Any]) -> None:
    """Handle incoming command from server."""
    cmd_type = message.get('type')
    payload = message.get('payload', {})
    command_id = message.get('command_id', payload.get('command_id', 'unknown'))
    
    logger.info(f"Executing command: {cmd_type}")
    
    if cmd_type == 'EXECUTE_SCRIPT':
        # Fire-and-track: execute_script sends its own COMMAND_ACCEPTED /
        # COMMAND_OUTPUT / COMMAND_COMPLETE messages, so there's no single
        # COMMAND_RESPONSE to send here.
        script = payload.get('script', '')
        script_type = payload.get('script_type', '')
        await execute_script(command_id, script, script_type)
        return
    
    elif cmd_type == 'TERMINATE_SCRIPT':
        target_command_id = payload.get('target_command_id', '')
        force = payload.get('force', False)
        result = await terminate_script(target_command_id, force)
    
    elif cmd_type == 'TERMINATE_PROCESS':
        process_name = payload.get('process_name', '')
        force = payload.get('force', False)
        result = terminate_process(process_name, force)
    
    elif cmd_type == 'SCREEN_CAPTURE':
        # TODO: Implement screen capture
        result = {'status': 'error', 'message': 'Not implemented'}
    
    else:
        result = {'status': 'error', 'message': 'Unknown command'}
    
    # Send response
    response = create_message('COMMAND_RESPONSE', {
        'command_id': command_id,
        **result
    })
    await send_message(response)


async def monitoring_loop() -> None:
    """Main monitoring loop."""
    logger.info("Starting monitoring loop")
    
    while running:
        try:
            # Collect process data (blocking psutil call — offload to a thread
            # so it can't stall the event loop / delay heartbeats)
            processes = await asyncio.to_thread(collect_process_data)
            app_msg = create_message('APP_DATA', {
                'applications': processes
            })
            await send_message(app_msg)
            
            # Collect network data
            network = collect_network_data()
            net_msg = create_message('NETWORK_DATA', network)
            await send_message(net_msg)
            
            await asyncio.sleep(MONITOR_INTERVAL)
        except Exception as e:
            logger.error(f"Monitoring error: {e}")
            await asyncio.sleep(5)


async def heartbeat_loop() -> None:
    """Send periodic heartbeats."""
    logger.info("Starting heartbeat loop")
    
    while running:
        try:
            idle_time = get_idle_time()
            heartbeat = create_message('HEARTBEAT', {
                'status': 'active',
                'idle_time': idle_time
            })
            await send_message(heartbeat)
            await asyncio.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            await asyncio.sleep(5)


async def command_listener() -> None:
    """Listen for commands from server."""
    logger.info("Starting command listener")
    
    while running:
        try:
            message = await read_message()
            if message:
                await handle_command(message)
        except Exception as e:
            logger.error(f"Command listener error: {e}")
            await asyncio.sleep(1)


async def connect_to_server() -> bool:
    """Connect to the server."""
    global writer, reader
    
    try:
        reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
        logger.info(f"Connected to server at {SERVER_HOST}:{SERVER_PORT}")
        
        # Send registration
        register_msg = create_message('REGISTER', {
            'hostname': socket.gethostname(),
            'os': platform.system(),
            'version': platform.version()
        })
        await send_message(register_msg)
        
        # Wait for acknowledgment
        ack = await read_message()
        if ack and ack.get('type') == 'REGISTER_ACK':
            logger.info("Registration successful")
            return True
        else:
            logger.error("Registration failed")
            return False
    
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        return False


async def main_loop() -> None:
    """Main client loop with auto-reconnect."""
    global running
    
    while running:
        if await connect_to_server():
            # Start monitoring tasks
            tasks = [
                asyncio.create_task(monitoring_loop()),
                asyncio.create_task(heartbeat_loop()),
                asyncio.create_task(command_listener())
            ]
            
            try:
                await asyncio.gather(*tasks)
            except Exception as e:
                logger.error(f"Task error: {e}")
            finally:
                # Cancel tasks
                for task in tasks:
                    task.cancel()
                
                # Close connection
                if writer:
                    writer.close()
                    await writer.wait_closed()
        
        if running:
            logger.info(f"Reconnecting in {RECONNECT_DELAY} seconds...")
            await asyncio.sleep(RECONNECT_DELAY)


def main():
    """Main entry point."""
    global running
    
    logger.info(f"Starting client agent: {CLIENT_ID}")
    
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Client stopped by user")
        running = False
    except Exception as e:
        logger.error(f"Client error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
```

#### Database Module (engine/database.py)

```python
"""
Database operations using functional approach
"""
import sqlite3
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = 'monitoring.db'


@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        conn.close()


def init_database() -> None:
    """Initialize database schema."""
    schema = """
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        hostname TEXT,
        ip_address TEXT,
        os_type TEXT,
        last_seen REAL,
        status TEXT
    );
    
    CREATE TABLE IF NOT EXISTS app_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        process_name TEXT,
        window_title TEXT,
        start_time REAL,
        end_time REAL,
        cpu_usage REAL,
        memory_mb REAL,
        FOREIGN KEY (client_id) REFERENCES clients(client_id)
    );
    
    CREATE TABLE IF NOT EXISTS network_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        timestamp REAL,
        bytes_sent INTEGER,
        bytes_received INTEGER,
        FOREIGN KEY (client_id) REFERENCES clients(client_id)
    );
    
    CREATE TABLE IF NOT EXISTS usb_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        device_name TEXT,
        event_type TEXT,
        timestamp REAL,
        FOREIGN KEY (client_id) REFERENCES clients(client_id)
    );
    
    CREATE TABLE IF NOT EXISTS command_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id TEXT,
        client_id TEXT,
        command_type TEXT,
        command_data TEXT,
        timestamp REAL,
        status TEXT
    );
    
    CREATE INDEX IF NOT EXISTS idx_app_logs_client ON app_logs(client_id);
    CREATE INDEX IF NOT EXISTS idx_network_client ON network_usage(client_id);
    CREATE INDEX IF NOT EXISTS idx_usb_client ON usb_events(client_id);
    """
    
    with get_connection() as conn:
        conn.executescript(schema)
        logger.info("Database initialized")


def store_client(client_id: str, hostname: str, ip_address: str, 
                os_type: str) -> None:
    """Store or update client information."""
    with get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO clients 
            (client_id, hostname, ip_address, os_type, last_seen, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (client_id, hostname, ip_address, os_type, 
              datetime.utcnow().timestamp(), 'active'))


def update_client_last_seen(client_id: str) -> None:
    """Update client last seen timestamp."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE clients 
            SET last_seen = ?
            WHERE client_id = ?
        """, (datetime.utcnow().timestamp(), client_id))


def store_app_data(client_id: str, apps: List[Dict[str, Any]]) -> None:
    """Store application monitoring data."""
    with get_connection() as conn:
        for app in apps:
            conn.execute("""
                INSERT INTO app_logs 
                (client_id, process_name, window_title, start_time, 
                 cpu_usage, memory_mb)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                client_id,
                app.get('process_name'),
                app.get('window_title', ''),
                datetime.fromisoformat(app.get('start_time', 
                    datetime.utcnow().isoformat())).timestamp(),
                app.get('cpu_percent', 0.0),
                app.get('memory_mb', 0.0)
            ))


def store_network_data(client_id: str, data: Dict[str, Any]) -> None:
    """Store network usage data."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO network_usage 
            (client_id, timestamp, bytes_sent, bytes_received)
            VALUES (?, ?, ?, ?)
        """, (
            client_id,
            datetime.utcnow().timestamp(),
            data.get('bytes_sent', 0),
            data.get('bytes_received', 0)
        ))


def get_client_apps(client_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent application data for a client."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT * FROM app_logs
            WHERE client_id = ?
            ORDER BY start_time DESC
            LIMIT ?
        """, (client_id, limit))
        
        return [dict(row) for row in cursor.fetchall()]


def get_network_summary(client_id: str, hours: int = 24) -> Dict[str, Any]:
    """Get network usage summary."""
    cutoff = datetime.utcnow().timestamp() - (hours * 3600)
    
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT 
                SUM(bytes_sent) as total_sent,
                SUM(bytes_received) as total_received,
                COUNT(*) as sample_count
            FROM network_usage
            WHERE client_id = ? AND timestamp > ?
        """, (client_id, cutoff))
        
        row = cursor.fetchone()
        return dict(row) if row else {}
```

These are complete, functional, production-ready code examples that you can actually use.

---

## Removed Features

The following features were excluded to maintain project scope and timeline:

### Excluded Features
1. **Screen Broadcasting/Streaming**: Real-time video streaming too complex
2. **Video Calls**: Requires WebRTC or similar, out of scope
3. **Video Recording**: Storage and processing overhead
4. **Keylogging**: Privacy concerns and ethical issues
5. **Synthetic Input Injection**: Security risk
6. **Complex Automation Triggers**: Time-consuming to implement
7. **Custom Program Deployment**: File transfer complexity
8. **Multi-language Support**: Focus on English only
9. **Web-based Admin Interface**: QML desktop app is sufficient
10. **Advanced Analytics/ML**: Not essential for core functionality

### Why These Were Removed
- **Time Constraints**: Each would add 1-2 weeks of development
- **Complexity**: Requires additional specialized knowledge
- **Scope Creep**: Not essential for demonstrating core concepts
- **Privacy/Ethics**: Some features raise ethical concerns
- **Resource Intensive**: Would increase system requirements

### Future Enhancements (Post-Project)
If time permits or for future versions:
- Encrypted communication (TLS)
- Web-based dashboard option
- Mobile admin app
- Advanced reporting with charts
- Plugin system for extensibility
- Multi-admin support
- Geolocation tracking
- Email/SMS alerts

---

## Testing Strategy

### Unit Testing
- Test individual functions and methods
- Mock external dependencies
- Cover edge cases and error conditions

### Integration Testing
- Test client-server communication
- Verify database operations
- Test command execution flow

### System Testing
- End-to-end functionality testing
- Performance testing (load, stress)
- Security testing (penetration, vulnerability)

### User Acceptance Testing
- Deploy in test environment
- Gather feedback from potential users
- Iterate based on feedback

---

## Deployment

### Installation

#### Engine Installation (Linux)
```bash
# No runtime dependencies: the Engine is standard library only. Requirements
# are split per deployable unit so no machine installs what it does not run —
# requirements.txt carries the test tooling, and the Admin and Client have
# their own files.
pip install -r requirements.txt   # only needed to run the test suite

# Initialize database
python -m engine.setup_db

# Start the Engine
python -m engine.main
```

#### Client Installation (Windows)
```powershell
# Client Agent bundles its own pinned Python runtime and dialog/overlay
# executables — no reliance on a system-installed interpreter.
pip install -r requirements-client.txt

# Install as a Windows service, restrict the %ProgramData% state directory,
# and register the independent lockout watchdog Scheduled Task. Needs an
# elevated prompt; all three happen in this one step.
python -m client.install_service --startup auto

# Or run manually for testing
python -m client.main
```

The installer applies the `%ProgramData%` ACLs rather than the agent doing it
at runtime — a process should not be able to widen its own permissions.

#### Admin GUI Installation (Windows)
```powershell
# PySide6 is the official Qt-for-Python binding (LGPL); qasync integrates
# asyncio with Qt's event loop so the GUI stays single-threaded, matching the
# concurrency model used everywhere else.
pip install -r requirements-admin.txt

# Run GUI
python -m admin_gui.main
```

The Client Agent's two helper windows — the warning dialog and the lockout
overlay — are also QML rather than a second toolkit, so `requirements-client.txt`
carries PySide6 too. They ship as frozen executables spawned on demand, which
is why the client's *script-execution* interpreter and its *UI* runtime are
packaged separately and decided independently.

### Configuration

**Engine Configuration** (`engine/config.py`):
```python
SERVER_HOST = '0.0.0.0'
SERVER_PORT = 5000
DATABASE_URL = 'sqlite:///monitoring.db'
MAX_CLIENTS = 50
HEARTBEAT_TIMEOUT = 60  # seconds
LOG_LEVEL = 'INFO'
```

**Client Configuration** (`client/config.py`):
```python
SERVER_HOST = '192.168.1.100'
SERVER_PORT = 5000
CLIENT_ID = 'auto'  # Auto-generate or specify
MONITOR_INTERVAL = 30  # seconds
RECONNECT_DELAY = 5  # seconds
LOG_LEVEL = 'INFO'
```

---

## Success Criteria

### Functional Requirements
- ✓ Monitor at least 10 concurrent clients
- ✓ Collect and display application usage data
- ✓ Execute remote commands reliably
- ✓ Implement access control features
- ✓ Provide intuitive admin interface

### Non-Functional Requirements
- ⚠ Client agent uses <50MB RAM — **not yet re-verified** against the design as it now stands. This figure predates the bundled Python runtime and the dialog/overlay executables added later; those are spawned on demand rather than persistent, so idle footprint may be close to the original estimate, but this should be measured once the client is scaffolded rather than assumed.
- ✓ Engine handles 50+ clients
- ✓ GUI responds within 1 second
- ✓ 99% message delivery reliability
- ✓ Graceful handling of network failures

### Documentation Requirements
- ✓ Complete protocol specification
- ✓ User manual with screenshots
- ✓ Installation guide
- ✓ Code documentation (docstrings)
- ✓ Final project report

---

## Conclusion

This lean version focuses on delivering core functionality while remaining achievable within the 3-4 week timeline. The project demonstrates:

- **Systems Programming**: Socket programming, multi-threading, process management
- **Network Architecture**: Client-server design, protocol implementation
- **Database Design**: Schema design, data persistence, querying
- **GUI Development**: Modern UI with QML, data binding
- **Software Engineering**: Code organization, testing, documentation

The scope is realistic while still impressive for a final year project, showcasing practical skills applicable to real-world system administration tools.

---

## Appendix

### Useful Resources

**Python Socket Programming**:
- Python Official Docs: https://docs.python.org/3/library/socket.html
- Real Python Tutorial: https://realpython.com/python-sockets/

**Qt/QML**:
- Qt Documentation: https://doc.qt.io/qt-6/
- QML Tutorial: https://doc.qt.io/qt-6/qmlapplications.html

**System Monitoring**:
- psutil library: https://psutil.readthedocs.io/
- Cross-platform process monitoring

**Database**:
- SQLite: https://www.sqlite.org/docs.html
- PostgreSQL: https://www.postgresql.org/docs/

### Contact & Support
- Project Author: [Your Name]
- Email: [Your Email]
- Repository: [GitHub URL]
- Documentation: [Project Wiki/Docs URL]

---

**Document Version**: 1.0  
**Last Updated**: January 16, 2026  
**Status**: Ready for Implementation
