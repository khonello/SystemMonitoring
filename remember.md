# Things to remember

One page. Everything here is either a way to lose an afternoon or a way to
damage a machine. Details live in the linked docs; this is the list you reread
after a week away.

## Before you run anything

**`python -m client`, not `python client/main.py`.** The path forms silently
ignore every flag — config is read into `Final` constants at import time, so
`cli.py` has to set the environment *before* importing the component. Same for
`engine` and `admin`. → [commands.md](commands.md)

**`--check` first, always.** Each unit answers "did I resolve what you think I
did" without touching the network: `engine --check`, `client --check`,
`admin --check-qml`. Most integration bugs are configuration bugs.

## Safety

**Never run the Engine on a network you do not control.** Authentication is a
stub that accepts anyone (`issues.md` C1). Anyone who reaches port 5000 can
register as an **admin** and issue commands. TLS does not help — encryption
without authentication only means the attacker's session is private too. Phase 5
needs no network at all, so run it offline. → [testing.md](testing.md) §0.1c

**Never launch the overlay on a machine you are using.** It covers the screen,
disables Task Manager and re-asserts topmost every 500ms. It always restores the
policy on exit and closes at its `--until` time, but "always" is exactly what
`issues.md` C11 questions.

**Snapshot the VM before `install_service`.** It registers a boot-start service
*and* a Scheduled Task that runs every 5 minutes as SYSTEM, and what they enforce
blacks out a screen. `--uninstall` removes both, but a snapshot is the only
undo that works when the machine is locked.

**`w32tm /resync` after every snapshot revert.** Lockout schedules are time-based
and HMAC-protected. A stale VM clock makes block windows look expired or not yet
started, which reads exactly like an enforcement bug.

## Things that fail silently

**`--id` must match everywhere.** `STATE_DIR` is derived from `CLIENT_ID`, so the
agent, the watchdog and the installer must all resolve the same one. A service
and a Scheduled Task inherit nothing from the installer's environment, which is
why `install_service.py` bakes `--id` into both command lines. Get it wrong and
the watchdog finds no schedule and *releases a blocked machine*.

**Regenerating the TLS certificate breaks every client** until the new `certs/`
is copied to each one — they pin it. The fixed identity `labmonitor-engine` is
what lets the Engine's *address* change freely; the certificate itself cannot.

**Never disable `check_hostname` or `verify_mode` to "make TLS work."** That
quietly reduces TLS to obfuscation. `ENGINE_TLS=0` is the honest escape hatch.

**A tamper check that fails means still blocked.** Lockout state fails closed by
design. If validation fails, that is the answer, not an error to route around.

## Open, and worth not rediscovering

**C11 gates Phase 6** — the agent's service and the watchdog task both run as
SYSTEM in session 0, isolated from the interactive desktop, so the overlay may
render where nobody can see it while every log line reports success. Unverified;
needs elevation. `testing.md` T5.5–T5.7 measure it.

**C12 and C14 are fixed** (now B25 and B26). The overlay holds its own lock in
`STATE_DIR`, so every launcher can see it; `dialog_app --help` exits 0.

**Check `issues.md` section D before "fixing" anything that looks missing.**
Eight things there are decisions, not gaps.

## Naming

| | |
|---|---|
| `issues.md` **A/B/C/D** | needs your decision / resolved / open / accepted limitation. The letter is the status, so an item's letter changes when it is fixed (C13 → B21). Numbers are never reused. |
| `testing.md` **T<part>.<n>** | test ID: part number, then sequence. T5.5 is Part 5, test 5. |

## The five docs

| | |
|---|---|
| [README.md](README.md) | design spec. Can lag the code — where they disagree, the code is newer |
| [todo.md](todo.md) | the phase plan |
| [issues.md](issues.md) | what is wrong, undecided or unproven |
| [commands.md](commands.md) | every command and flag. Tracks the code |
| [testing.md](testing.md) | the Phase 5 manual test plan |
