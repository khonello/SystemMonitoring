# Open Issues

Known problems, deferred decisions and unverified claims — things that are
*wrong, undecided or unproven*, as opposed to simply not built yet.

This is not the roadmap. Work that is merely scheduled for a later phase lives
in [todo.md](todo.md); an item only belongs here if it would still be a problem
after its phase is finished, or if it blocks a phase from starting.

Four sections, and the difference between the last two matters:

| | |
|---|---|
| **[A](#a--needs-your-decision)** | Needs your decision — policy and approvals, not code |
| **[B](#b--resolved)** | Resolved, kept so the reasoning survives |
| **[C](#c--still-open-scheduled-work)** | Not finished. Each has a phase |
| **[D](#d--accepted-limitations)** | Deliberately not being built, with what would change that |

Section D exists so a considered decision is never mistaken for a gap nobody
noticed. If you are wondering "why doesn't it do X", look there before
assuming X was overlooked.

Phases 0–4 are complete. Packaging moved to Phase 8 (see C2), and Phase 5 is
manual per-system verification.

**Scope: a project defence, demonstrated on VMs.** Not a deployment. That is
what makes A2 inapplicable for now, and it changes what C11 blocks — a
hand-run agent shows the overlay normally, so the demo path never enters
session 0. C11 gates a real *install*, not the demonstration.

**Currently blocking: nothing for the defence.** C1 (authentication accepts
anyone) and C11 (enforcement may not reach the screen under a service install)
both gate deployment, and both are worth being able to answer questions about
rather than being caught by.

**Numbering.** The letter is the section, so an item's letter changes when its
status does — C13 became B21 when it was fixed. The number is allocation order,
not priority, and is never reused, so a reference in an old commit still resolves.
Test IDs in [testing.md](testing.md) are a separate scheme: `T<part>.<n>`.

---

## A — Needs your decision

These are yours: policy, scope, licensing and approvals. Each says what happens
by default if you do nothing, so none of them is silently blocking.

### A1. Retention period — 30 days chosen as a default, needs your sign-off

Pruning is now implemented and scheduled (see B3). It deletes monitoring data
older than **30 days**, sweeping every 6 hours.

That number is a guess made to unblock the work. It keeps the README's "weekly
aggregated statistics" and "historical trend data" workable while bounding
growth, but the right value depends on how long your institution expects lab
activity records to be kept.

Change it with `ENGINE_RETENTION_DAYS`, or set `ENGINE_RETENTION_DAYS=0` to
disable pruning entirely (the Engine logs a warning when you do).

### A2. Institutional approval — **not applicable at current scope**

**Current scope is a project defence, demonstrated entirely on VMs.** No real
lab machine, no real student, no institutional deployment. Nothing needs
approving to build, test or present it, and this entry is not blocking anything.

Recorded because the requirement is real at a different scope, and because a
defence panel may well ask about it. The system captures screenshots on demand,
logs USB insertions, tracks every running application and window title, and can
lock a user out of a machine. Pointed at real computers used by real people,
that is the kind of thing most institutions gate behind ethics review or IT
sign-off. The README's "Removed Features" section shows the project already
reasoned this way once — keylogging was cut on exactly these grounds, and that
is a good answer to give if asked.

**What would make this live:**

- A pilot on real lab machines, even a handful, even voluntarily — the moment
  the monitored person is not you.
- A sale or institutional trial. At that point approval is the buyer's process
  to run, but they will expect the software to have answers ready: what is
  collected, how long it is kept (A1), who can see it (D5), and what the
  monitored person is told.

Nothing in the code depends on this; it gates where you are allowed to point it.

### A3. How the master secret and per-client keys get onto machines

Phase 7 needs `client_key = HMAC(master_secret, client_id)` baked into each
client's install package. The README describes the scheme but not the
operational process: where the master secret is generated, how it is stored so
it is not lost, and how per-machine keys reach 50 lab computers.

This is a deployment process question rather than a coding one, and it shapes
what Phase 7 actually has to build. Related: A6.

*(A4 is answered — TLS was brought into scope and implemented. See
[B12](#b12-transport-encryption--done).)*

*(A5 is answered and has moved to [B11](#b11-script-import-policy--done).)*

### A6. Admins authenticate as if they were clients — is that what you want?

The README says the admin holds *the master secret itself*, while each client
gets a derived key. The implemented handshake does not distinguish them: an
admin registers and answers the nonce challenge exactly like a client.

For Phase 7 that leaves a genuine design question — should an admin prove
possession of the master secret directly, or be issued a derived key like any
other peer? The second is simpler and safer (a compromised admin workstation
does not burn the whole fleet), but it departs from what the README describes.

Not urgent, but decide before Phase 7 rather than during it.

---

## B — Resolved

### B1. Idle admin connections were dropped after 60 seconds — **DONE**

`engine/main.py` applied the heartbeat timeout to every peer, and nothing made
an Admin GUI send traffic, so an operator reading a dashboard was disconnected
after a minute.

**Fixed** by giving the Admin GUI its own heartbeat task on the same 15s
interval a Client Agent uses (`admin/connection.py`, `_heartbeat`). One
uniform liveness rule was preferred over a per-role timeout: the alternative
means two timeouts to reason about, and an admin that has genuinely crashed
should still be reaped.

Covered by `test_admin_heartbeat_keeps_the_session_alive`.

### B2. `MAX_CLIENTS` counted admins as clients — **DONE**

**Fixed** with separate caps: `MAX_CLIENTS` (50) counts only Client Agents,
`MAX_ADMINS` (5) counts only admins. A full lab can still be administered.

Covered by three tests, including
`test_admin_can_connect_when_clients_are_at_capacity`.

### B3. Retention was implemented but never called — **DONE (period needs sign-off: A1)**

**Fixed** with a `prune_loop` background task in `engine/main.py`, alongside
the existing reaper.

Two details worth keeping:

- Deletion is **batched** (5,000 rows per statement) with an `await` between
  passes. An unbounded `DELETE` across millions of rows would block the event
  loop for as long as it took.
- The sweep runs via `asyncio.to_thread` on its own short-lived connection.
  This is the one place on the Engine where the README's "threads only for work
  that cannot signal readiness" rule genuinely applies.

### B4. `get_app_usage_summary` cost grows with table size — **DONE, via retention**

Investigated properly and the obvious fix did not survive measurement.

Adding a composite `(client_id, start_time, process_name)` index looked like it
helped — the summary went 29ms to 20ms — but repeating the benchmark showed
insert timings varying by **more than the effect being measured** (22ms, 39ms,
27ms across identical runs on this machine). The summary itself held at ~25ms
in every configuration.

So the index was reverted rather than kept on the strength of a single noisy
run. Bounding table growth (B3) is the fix that actually addresses this query's
cost. The reasoning is recorded in the schema comment in `engine/database.py`
so it is not re-litigated from scratch.

**If you re-measure, do it on an otherwise idle machine.**

### B5. asyncio ↔ Qt event-loop integration undecided — **DONE**

**Decided: qasync.**

The deciding argument was consistency with the project's own concurrency rule.
The README is explicit that threads are only for work that cannot signal
readiness — sockets can, so a socket thread would have contradicted the model
used everywhere else. qasync drives asyncio on top of Qt's loop, keeping the
GUI, the socket and every background task on one thread, with no cross-thread
marshalling to get wrong.

Verified before being built on: a scratch harness ran a real `asyncio.sleep`
and a full socket round trip on the Qt loop.

### B6. `app_logs` dropped `pid` — **DONE** (`end_time` still unused, by design)

**Fixed** by adding a `pid` column, which the client was already sending and
which is the only way to tell two runs of the same executable apart.

`end_time` remains deliberately unused: these are periodic samples, not
sessions, so duration is derived as (latest sample − `start_time`) at query
time. Populating it properly needs session tracking, which belongs with the
Phase 4 monitors.

### B7. README contradicted the Qt binding in use — **DONE**

The Deployment section now says `pip install PySide6 qasync` and uses
`python -m admin.main`.

### B12. Transport encryption — **DONE** (this was A4 and C3)

TLS on the Engine's listener and both client types. Brought forward rather than
left in Future Enhancements: authentication stops impersonation but does
nothing for confidentiality, so without this every script, screen capture and
lockout schedule stayed readable to anyone on the LAN. It also turned out to be
small — all transport funnels through three call sites, so the framing,
protocol and handlers were untouched.

Decisions worth keeping:

- **Self-signed and pinned, not a CA.** One server, and every client gets an
  install package anyway. Trusting exactly the Engine's certificate is strictly
  narrower than trusting a CA that could sign others. A small internal CA is
  the upgrade path if rotation becomes routine.
- **Identity is a fixed name, not an address.** The certificate is issued for
  `labmonitor-engine` and clients pass that as `server_hostname` while dialling
  whatever IP the Engine has. So hostname verification stays **on** — the usual
  reason to disable it is a server that moves, and this removes that reason.
  A DHCP Engine can change address without reissuing anything.
- **Presence-based, not opt-in.** Once certificates exist TLS is on, so a
  deployment cannot end up plaintext through a forgotten flag. `ENGINE_TLS=0`
  disables it deliberately, and startup always logs which mode is active.
- **Fails loudly.** A bad certificate stops the Engine starting; a client that
  cannot build a context refuses to connect rather than downgrading. Silent
  downgrade is exactly how a system ends up unencrypted while everyone believes
  otherwise.

Tested against real handshakes rather than mocks, and the tests assert the
*failures* as much as the successes — a context with verification quietly
disabled behaves identically to a correct one until someone is attacked. An
impostor certificate, a hostname mismatch, an unpinned client and a plaintext
client are all verified to be refused, both at the context level and through
the agent's own connect path.

**Still true**: the private key is a secret to protect, and a compromised
Engine certificate means redistributing to every machine. That is the same
operational shape as the Phase 7 master secret, so it folds into the same
install step rather than adding a new one.

### B13. Message flow was implicit, and unobservable when it broke — **DONE**

Every telemetry handler ended in the same two steps — store it, then push it to
the admins — but that pattern was only ever written out longhand inside each
handler. Nothing stated the contract, so the only way to learn where an
`APP_DATA` went was to read its function body, and when an admin stopped seeing
a client's data there was no way to distinguish "never arrived" from "arrived,
stored, and the relay failed".

**Fixed** by splitting mechanism from policy. `engine/routing.py` runs a flow —
role check, persist, handler, relay — and logs every hop under one `trace_id`.
`_ROUTES` in `engine/command_handler.py` declares, in one table, which flow each
message type is on and which roles may send it.

Decisions worth keeping:

- **A table, not a framework.** Stages are not registrable, there is no
  middleware chain, and flows do not compose. Three fixed steps in a fixed order
  cover every message this protocol has, and a debugger stepping through
  `dispatch` lands in real code rather than in an abstraction. The goal was
  making failures explicable; indirection works against that.
- **Roles moved into the table.** The old code special-cased `ADMIN_COMMAND`
  outside the handler dict purely so its sender could be checked. Now every
  route carries `senders`, which closed two gaps nobody had noticed: a client
  could request reports and the client roster, and an admin could send
  `APP_DATA` that would be stored as though a client had reported it.
- **A failed persist still relays.** Losing a sample to a storage fault should
  not also blank the operator's live view.
- **Trace ids are distinct from command ids.** A `command_id` names a script
  execution; a trace names one message's passage. Telemetry has no `command_id`,
  which is exactly why an unrelayed `APP_DATA` was previously untraceable. An
  inbound trace is honoured so a client that stamps its own messages gets one id
  spanning both components — and length-bounded on arrival, since it is
  peer-supplied text that ends up in every log line.

### B14. Relay failures were silently discarded — **DONE** (found during B13)

Not previously logged. `_relay_to_admins` ignored the return value of every
send, so an admin whose socket had gone away simply stopped receiving telemetry
with nothing anywhere recording it. The Engine reported success either way.

**Fixed** — `routing.relay` counts failures, logs them against the trace id with
the peer ids that missed out, and returns the delivered count. Partial delivery
is explicitly tested: one dead admin must not stop the others being served.

### B15. A command for an offline client vanished — **DONE**

`send_command_to_client` marked the row `undeliverable` and gave up. For a
policy change that is wrong: a machine switched off during an exam setup came
back with none of the restrictions that had been applied to the room.

**Fixed** with a durable outbox, subject to one distinction that does the real
work here — **only commands whose replay is still correct are queued.**
`DURABLE_COMMANDS` (`SET_WEBSITE_POLICY`, `SET_APP_BLACKLIST`,
`SET_TIME_RESTRICTION`) declare state the client should converge to, so
delivering one late is right. A `SCREEN_CAPTURE` or `SHOW_DIALOG` replayed
twenty minutes after the operator asked for it is not a recovered command, it is
a surprise; those still fail as before.

- **No outbox table.** A queued command is a `command_log` row whose status says
  it has not gone out, so the queue and the audit trail cannot disagree and
  retention prunes both at once.
- **Newer supersedes older, per type.** Replaying three successive blacklist
  updates achieves nothing the last one does not. This also bounds the queue to
  one row per durable type, which is why there is no separate size cap.
- **`SET_PAUSE` is deliberately excluded.** The client already persists pause
  state across a reboot, so replaying it would re-freeze a machine whose pause
  had legitimately lapsed — turning the admin safety net inside out.
- **Marked dispatched only after the write succeeds**, so a client that drops
  mid-flush keeps the rest queued rather than losing them to an optimistic
  status update.
- **A durable broadcast also reaches known-but-offline clients.** "Apply this
  policy to the lab" should mean the whole lab, not the machines that happened
  to be switched on.

Staleness is bounded by `ENGINE_OUTBOX_TTL`, default 24 hours.

### B16. Time restrictions were unreachable from the Admin GUI — **DONE** (this was C11)

The whole lockout-schedule feature had no operator-facing control. Every other
layer was finished — the Engine routed `SET_TIME_RESTRICTION`, and the client
enforced it with a tamper-protected schedule, countdown overlay, two watchdogs,
reboot recovery and the 2-hour cap — but no editor, slot or panel ever sent one.
It fell between phases: Phase 3 deferred the editor to Phase 4 on the reasoning
that an editor with no enforcement behind it is UI without behaviour, and Phase
4 built the enforcement without coming back.

**Fixed** with a "Time restriction" section in `PolicyPanel.qml` plus
`setTimeRestriction` / `clearTimeRestriction` on the backend.

Decisions worth keeping:

- **One-off windows, not recurring rules.** The client stores a single
  start/end pair and knows nothing about weekly recurrence, so the editor sends
  what the client can actually honour. A recurring schedule would be a client
  feature first and a UI feature second; inventing the wire format here would
  have produced an editor whose settings silently did nothing.
- **Duration plus a delay, not two datetimes.** QML has no good datetime entry,
  and the delay is what the exam case actually needs — set the lockout up
  beforehand and let the client's own watchdog raise the overlay when the
  window opens, with no further contact from the GUI.
- **The cap is warned about, not enforced here.** The client shortens anything
  over `MAX_BLOCK_HOURS` and reports the end it stored. Clamping in the GUI too
  would mean two places to keep in step, so the editor warns and lets the
  client be authoritative — and `MAX_BLOCK_HOURS` moved to `common.constants`
  so the warning quotes the same number the client enforces, via a
  `maxBlockHours` property rather than a literal in QML.
- **Blocking the whole room asks first.** Locking one machine is recoverable by
  walking to it; locking the lab is not.
- **Clearing a block does not touch a pause.** Same precedence the client
  applies — dropping one must not release a machine the other still holds.

Also removed a stale line in that panel telling the operator enforcement was a
Phase 4 stub that replies "not implemented". It had been untrue since Phase 4.

### B17. Each system now runs and reports on its own — **DONE**

Prompted by moving packaging last: proving the code works on its target machine
comes first, and each unit needed to be startable and *observable* without the
other two. All three were configurable only through environment variables, with
no way to ask a component what it saw.

**Fixed** with a `cli.py` per package, `python -m engine|client|admin` as the
CLI entry points, and `labmonitor.py` dispatching to all three plus the helpers.

- **Why not argparse inside the existing `main.py` files.** Every config value
  is a module-level `Final` read from `os.environ` **at import time**, and
  `main.py` imports those constants at module level, so a flag cannot be applied
  by setting an attribute afterwards — consumers have already bound the value.
  `tests/conftest.py` documents the same trap from the other direction. The
  order that works is parse → write to `os.environ` → *then* import, which is
  why the parsers sit in their own modules and import `main` inside `run()`.
  A consequence worth keeping: the three `main.py` files were not touched, and
  `python -m engine.main` still works exactly as before.
- **Every flag maps onto an existing environment variable** rather than
  introducing a second configuration mechanism. The variable still works alone.
- **`engine/cli.py` imports only argparse, os and sys**, so a Linux Engine
  install still pulls nothing.
- **The launcher imports each component lazily**, inside the branch that needs
  it — a top-level import would drag PySide6 into `labmonitor.py engine`.

The diagnostics are the point of the exercise: `engine --check` (config, TLS
posture, prepares the database, does not bind the port), `client --once` (one
real collection cycle, no Engine, no sockets), `client --check` (config, local
state, which bundled pieces are absent) and `admin --check-qml` (loads every QML
file offscreen, renders nothing).

`--check-qml` calls `os._exit` once it has reported. Ordinary interpreter
shutdown frees the `Backend` while QML still holds bindings to it, producing
null-model errors that look like panel faults but are an artefact of shutting
down — leaving that noise in would make the check untrustworthy for the thing it
exists to detect.

### B18. `STREAM_LIMIT` never exercised — **DONE** (this was C7)

Both ends open with a 16MB limit because asyncio caps a line at 64KiB, but
nothing had ever sent a message near either bound, so neither the working case
nor the failure mode had been observed.

**Both halves are now covered**, because the risk was never just "does a big
message work" — it was that an oversized one surfaces as an unrelated-looking
stream error with nothing in it naming the cause.

- **Product fix**: `capture_screen` already knew the encoded size and never
  checked it. It now refuses a capture over `STREAM_LIMIT` minus a new
  `STREAM_OVERHEAD_ALLOWANCE` (64KB of envelope room), with a message naming the
  size and suggesting a lower quality — rather than handing the framing
  something that costs the agent its whole connection.
- **Tests**: a 4MB payload round-tripping client → Engine → admin through the
  real framing, an oversized line proving the Engine fails closed rather than
  leaving the peer hanging, and the client-side refusal.

Sizing against the limit *minus* an allowance matters: a payload that exactly
fits produces a line that does not, once the envelope is added.

### B19. `docs/` was empty — **DONE** (this was C8)

`docs/protocol.md`, `docs/installation.md` and `docs/user_manual.md` are
written. `installation.md` states plainly that packaging does not exist and
names the three interpreter fallbacks, so nobody mistakes a from-source setup
for a deployment.

### B20. The app blacklist was unreachable from the GUI — **DONE** (this was C12)

The same defect as B16, one panel over: the "Applications" group box called
`terminateProcess`, a one-shot kill, and nothing sent `SET_APP_BLACKLIST`.

**Fixed** with a `setAppBlacklist` slot shaped like `setWebsitePolicy`, and a
list field in the policy panel.

- **The one-shot kill stayed**, moved into its own "Terminate one process now"
  box. Killing a process once and maintaining a standing list are different
  actions and both are wanted; the old panel conflated them under one title.
- **An empty list is a real instruction** — it clears the blacklist — so the
  Apply button is not disabled on empty input the way the website editor's is.
- Payload key is `process_names`, matching what `client/policy.set_app_blacklist`
  reads. A test asserts the exact payload, since a mismatch here would fail
  silently at the far end.

### B21. Client local state was per-machine, not per-client — **DONE** (this was C13)

`--id` changed the identity a client registered under, but `STATE_DIR` was
`%ProgramData%\SystemMonitoring` with no client id in it. Several agents on one
box shared one lockout schedule, one pause file and one cached blacklist,
overwriting each other — which made Phase 6's "10+ clients" item impossible to
simulate for anything that *enforces*.

**Fixed**: `STATE_DIR` is now `STATE_ROOT / state_component(CLIENT_ID)`.

Three things this turned up that were not obvious going in:

- **`CLIENT_ID` reaches the path unvalidated.** It comes from the environment,
  so joining it raw would let `../../Windows` escape the state root entirely.
  It is sanitised to one safe path component.
- **Sanitising alone reintroduces the bug it fixes.** It is lossy: `lab1/pc-01`
  and `lab1_pc-01` both reduce to the same name, silently reuniting two
  machines' state. A short SHA-256 suffix of the *original* id restores
  distinctness and is stable across runs.
- **The watchdog would have failed open** — the serious one. It runs from a
  Scheduled Task as SYSTEM, which inherits nothing from the agent, so it would
  have re-derived a *different* client id, resolved a different directory,
  found no schedule, and released a machine that should still be blocked. In
  the one component whose entire job is to fail closed. `client/watchdog.py`
  now takes `--id`, applied to the environment before `client.config` is
  imported, and `install_service.py` bakes the id into both the service and the
  task command lines rather than leaving either to re-derive it. The same gap
  existed for the service command and is closed the same way.

ACLs moved from the per-client directory to `STATE_ROOT`, with the
object- and container-inherit flags, so a client directory created later is
protected the moment it appears instead of depending on the installer having
been run for that client.

**Not fixed, and not fixable this way**: two agents on one machine both entering
a block window still launch competing fullscreen overlays on the same physical
display. Separate state does not buy a separate screen. So one box can now
simulate many clients for telemetry, policy and reporting — but enforcement
still needs real separate machines.

### B22. Stale references left by the rename and the phase renumber — **DONE**

Swept deliberately rather than found by accident, after two changes that touch
text everywhere: `admin_gui` → `admin`, and the phase renumber that moved auth
to 7 and packaging to 8. Recorded because most of these were invisible to the
test suite — nothing asserts on a comment or a placeholder string.

- **`.gitignore` still ignored `admin_gui/runtime/`.** The rename swept `.py`,
  `.qml`, `.md` and `.toml`; it did not sweep dotfiles. A bundled runtime in
  `admin/runtime/` would have been committed.
- **A stale string the operator could see.** `MonitoringPanel.qml` told them
  "The client's process monitor is a Phase 4 stub" when the panel was empty. It
  has not been a stub since Phase 4 closed — the same class of mistake as the
  policy panel's "not implemented" note removed in B16. Now says the client
  sends a batch every 30 seconds.
- **~12 comments still said "Phase 6" for authentication and "Phase 4
  packaging step".** Corrected across `engine/auth.py`, `client/auth.py`,
  `admin/connection.py`, `common/tls.py`, `client/config.py`,
  `client/lockout.py` and the tests.
- **`tests/test_integration.py` still described itself as Phase 1 scaffold
  smoke tests** that expect "not implemented" replies. It now carries TLS,
  outbox and stream-limit coverage. One comment inside it claimed a reply was
  the old stub when the client genuinely runs the command and reports that no
  such process exists.
- **Issue references in code pointed at numbers that had moved** (C7, C13)
  after those items were resolved into section B.

The general lesson, worth keeping: a rename or a renumber is a code change the
tests cover and a *prose* change nothing covers. Grep for the old token in every
file type, not just the ones the compiler reads.

### B23. `scripts/` was not an installed package — **DONE**

`pyproject.toml` listed `common`, `engine`, `client`, `client.monitors` and
`admin`, but not `scripts` — despite `python -m scripts.generate_cert` being
the documented way to produce the Engine's TLS certificate, and
`labmonitor.py certs` importing it.

It worked in every test because pytest runs from the repo root, which puts
`scripts/` on `sys.path` regardless. It would have failed the moment anyone ran
the documented command from anywhere else. Added to the package list.

### B24. Nothing stopped two agents running under one client id — **DONE**

B21 gave each client id its own `STATE_DIR`, which stopped agents under
*different* ids from overwriting each other. It did nothing about two agents
under the **same** id, and there was no single-instance guard anywhere in
`client/`. The realistic trigger is not exotic: the service is running and
someone also runs `python -m client` by hand, both defaulting to the same
`hostname-platform` id.

What happened then:

- Both resolved the same `STATE_DIR` and raced on the same lockout schedule and
  pause file. Writes are atomic (`mkstemp` + `os.replace`), so the result was
  last-writer-wins rather than a corrupt file — but two writers on a
  fail-closed schedule is exactly where ambiguity is least affordable.
- **The Engine could not catch it.** `connection_manager.register()` sees a
  second connection for a known peer and cannot distinguish a duplicate process
  from a reconnect after a network blip, so it logs
  `"replacing previous connection"` and overwrites the writer. The first agent
  keeps running, believing it is connected, sending into a dead socket. So the
  check has to be local and has to happen before the connect loop.

**Fixed**: `client/single_instance.py` takes an exclusive lock on one byte of
`agent.lock` inside `STATE_DIR`, held for the life of the process, acquired in
`client/main.py` before anything else.

Four things that shaped it:

- **Placed before `lockout.check_on_startup()`, not after.** That call
  relaunches the overlay if a block is still active, so a duplicate that
  discovered itself later would have thrown a competing fullscreen window onto
  the same screen on its way out — causing the D8 collision the guard exists to
  prevent.
- **Rejected: a heartbeat timestamp with a freshness window.** The obvious
  design — the running agent refreshes a file, a starting agent treats a stale
  one as "the previous is dead" — is a race rather than a lock (two agents
  starting together both read stale and both proceed), and worse, it fails open
  on crash-restart: an agent killed at T and restarted by service recovery at
  T+2s reads a two-second-old file, concludes an agent is alive, and exits. A
  crash keeping the agent down, in the component whose job is to fail closed.
  An OS lock never asks "is the previous one dead", because the kernel already
  knows — it is dropped on a clean exit, a `taskkill /f` and a bugcheck alike.
- **Fails open on anything that is not a positive detection.** The lock being
  held and the state directory being unwritable both surface as `OSError`
  (errno 13 on Windows), so the two are told apart by *which call raised* —
  `os.open` outside the try, the lock inside it. An unopenable lock logs and
  starts anyway: refusing would leave the machine with no agent enforcing
  anything, which is worse than the duplicate being guarded against.
- **Keyed on the client id, not the machine.** A machine-wide singleton would
  have undone B21's whole purpose. Because the lock lives in the already
  per-id, already ACL'd `STATE_DIR`, that property comes for free.

A byte-range file lock was preferred over a named mutex for one concrete
reason: `Local\` mutexes are per-session, so they would miss the
service-in-session-0 plus hand-run-in-the-user's-session case — the exact
scenario that motivated this — and `Global\` requires `SeCreateGlobalPrivilege`,
which a service holds and an interactive user does not. File locks are
properties of the handle and are not session-scoped.

Verified on Windows beyond the unit tests: a second agent under the same id
exits 1 with the resolved lock path in the message, a second agent under a
different id runs unaffected, and an agent restarted seconds after the first
was hard-killed acquires normally. Covered by seven tests in `tests/test_client.py`,
including the kill-the-holder case, which is the crash-restart guarantee.

### B25. `overlay_running()` was blind across processes — **DONE** (this was C12)

`client/lockout.py` answered "is an overlay up?" from `_overlay`, a module-level
`Popen` handle — per process, while two processes launch overlays for the same
client id by design: the agent, and the Scheduled Task watchdog that exists as
an independent check for when the agent hangs. A fresh process started with
`_overlay = None`, so it reported False regardless of what was on screen and
launched another one.

**Measured before the fix**, two processes resolving one `CLIENT_ID` and running
the shipped `enforce_once()` with only the launched argv swapped for a sleeper:

```
[agent]    overlay_running() before = False   after = True   launched pid 19796
[watchdog] overlay_running() before = False   after = True   launched pid 21028
```

Worse than a duplicate: a watchdog pass is a one-shot process that exits
immediately, orphaning its overlay, and every later pass started blind — so the
release branch never stopped it. For a pause, whose overlay carries the pause's
*internal* expiry as its end time, dropping the pause left the machine held with
no countdown and nothing able to clear it.

**Fixed**: the overlay holds a lock on `overlay.lock` in `STATE_DIR` for its own
lifetime, so asking the lock answers for every launcher at once. Same mechanism
as B24, which is why this was cheap — the guard was generalised to named locks
rather than rewritten.

**Measured after**, same probe, with the sleeper taking the lock as the real
overlay now does:

```
[agent]    overlay_running() before = False  launched a process = True   owner 3836
[watchdog] overlay_running() before = True   launched a process = False  owner 3836
```

Four things this turned up that were not obvious going in:

- **The overlay had to hold the lock, not its launcher.** That is what makes it
  answer "is a lockout on screen?" rather than "did *I* put one there?", and it
  means an orphan whose launcher died is still visible to everyone.
- **`stop_overlay` needed a cross-process path too.** Detecting an overlay you
  cannot stop is only half a fix, so the holder records its pid beside the lock
  and a launcher without a handle signals that. The lock stays the authority on
  *whether* something is running; the pid is advisory and only says *what* to
  signal.
- **That path could kill the wrong process.** The first test run terminated the
  suite itself with SIGTERM: any process holding the lock would have signalled
  its own pid. `_stop_overlay_by_pid` now refuses to signal itself and releases
  instead. Found by the tests, not by review.
- **Mode transitions across processes are deliberately not handled.**
  `_overlay_mode` is per-process too, so a watchdog seeing the agent's overlay
  cannot tell whether its mode already matches. It leaves it alone rather than
  restarting blind: a screen blocked in the wrong mode (a pause panel where a
  countdown belongs) is a far smaller failure than one that flaps or doubles.
  The launcher that owns an overlay still handles its own transitions. **What
  would change this**: recording the mode beside the pid, once C11 has settled
  whether this launch path survives at all.

Also passes `--id` to the overlay explicitly rather than relying on environment
inheritance, for the reason `install_service.py` bakes it into both command
lines: the overlay resolves its own `STATE_DIR`, and a service or Scheduled Task
cannot be assumed to pass anything down (B21).

Covered by eight tests, including the self-signal guard and the cross-process
detection.

### B26. `dialog_app --help` exited 3 — **DONE** (this was C14)

`main()` wrapped `parse_args` in `except SystemExit: return EXIT_BAD_ARGS`,
which is right for a bad argument but also caught the `SystemExit(0)` argparse
raises for `--help`. Cosmetic — the help text still printed — but for a program
whose *answer is its exit code* it meant the code could not distinguish "asked
for help" from "passed nonsense".

**Fixed**: `return EXIT_BAD_ARGS if exc.code else EXIT_OK`. Found while checking
that every command named in `commands.md` resolves.

### B11. Script import policy — **DONE** (this was A5)

Answered: predefined scripts are standard library and `subprocess` only, no
third-party packages. That closes the packaging question — the embeddable
distribution is sufficient — and the constraint is now enforced rather than
trusted, because a rule nobody checks is a rule that gets broken by accident.

**Imports are read with `ast`, not a regex.** That was considered and rejected:
a pattern match cannot tell `import os` from the same words inside a docstring,
and it mishandles `import os, sys` and parenthesised multi-line `from` imports.
The parser is already needed for the syntax check, so it costs nothing and
cannot be fooled — including by an import deferred inside a function body,
which is the obvious way to sneak one past a line-oriented check.

**The Windows question needed two mechanisms, not one:**

- A **denylist** of the ~15 POSIX-only stdlib modules (`fcntl`, `pwd`, `grp`,
  `termios`, `pty`, `resource`, `curses`, …). These are the dangerous ones:
  they compile cleanly anywhere and fail only at runtime on the client. The
  list exists so the operator gets "`fcntl` is Unix-only, use `msvcrt.locking`"
  rather than a bare "not found".
- `importlib.util.find_spec` run **inside the bundled interpreter**, which is
  authoritative: it reflects the client's real module set, including anything
  the embeddable distribution omits. `find_spec` resolves without importing —
  importing would execute the module's top-level code, which a validation step
  must never do.

**Known limit, worth stating plainly**: this is static analysis of import
statements. It cannot catch runtime-only platform assumptions — `os.fork()`,
`signal.SIGKILL`, POSIX path shapes — which are valid Python that simply fails
on Windows. It narrows the failure surface rather than eliminating it. If that
turns out to matter in practice, the next step is running each script once
against a real client during authoring, not more static rules.

Surfaced in the GUI via a **Check** button as well as on send, listing accepted
imports alongside rejected ones.

### B9. Scripts could run forever — **DONE**

The README's Script Execution Model was built around "some scripts run
indefinitely". A5's answer makes that premise wrong rather than the design
wrong: predefined scripts are extensions for small routine tasks, so an
unbounded run is a bug, not a use case.

Execution is now capped at **5 minutes by default, 15 maximum**. The ceiling
matters as much as the default — an admin who could set it to infinity would
have no cap at all. A script stopped at the limit reports `status: "timeout"`,
distinct from `"error"`, so an operator can tell "too slow" from "crashed"
without reading the output.

Two things worth keeping in mind:

- **The non-blocking model still stands.** A 5-minute script would stall the
  agent just as surely as an infinite one, so `COMMAND_ACCEPTED`, output
  streaming and `TERMINATE_SCRIPT` are all still needed. The cap is an
  addition, not a simplification — nothing built for the old premise was wasted.
- **A killed script gets no cleanup.** On Windows both `terminate()` and
  `kill()` map to `TerminateProcess`, so a run stopped at the limit cannot
  tidy up after itself; one killed mid-write leaves a partial file. Scripts
  under this mechanism must be safely interruptible. Documented in the README
  rather than left to be discovered.

### B10. Indeterminate pause — **DONE** (new feature)

An admin can hold one machine's screen or the whole room's, with no stated end
time, and drop it when ready. To the student it is simply "paused" — no
countdown, because there is no deadline to show.

The one-hour internal bound is a fail-safe against **the admin**, not the user:
if the operator closes the GUI or the network dies mid-pause, the lab must not
stay frozen. It is deliberately never displayed on the client, since showing it
would turn a safety net into a promise. The Admin GUI warns at five minutes
remaining, with an Extend button, so a long hold stays an explicit choice.

Design points that were not obvious going in:

- **Pause and a scheduled block can both be active.** The pause wins, being the
  live action; dropping it while a scheduled window is still open reverts to
  the countdown rather than releasing the machine. Covered by tests both ways.
- **The overlay is restarted, not reconfigured, when the mode changes** — a
  pause must not leave a scheduled countdown running underneath it.
- **The Admin GUI tracks expiry from what clients report in their heartbeats**,
  not from what it asked for. So a pause set from another console is tracked
  too, and a restarted GUI recovers the state instead of losing it.
- Pause state is tamper-protected and **fails closed** like the lockout
  schedule, and persists across a reboot — but expires on its own regardless,
  so a stale file cannot strand a machine.

### B8. A registration error left the socket open — **DONE** (found during this work)

Not previously logged. `perform_registration` was called outside
`handle_client`'s `try` block, so any exception escaped and left the peer
waiting forever on a reply that never came.

Found the hard way: a one-line `NameError` (a missing `ROLE_ADMIN` import)
turned into the whole test suite hanging rather than one test failing.

**Fixed** — that path now fails closed, logging and closing the socket.

---

## C — Still open: scheduled work

Things that are *not finished*. Each has a phase. Contrast with
[section D](#d--accepted-limitations), which is work deliberately not
being done — the split exists so a considered decision is never mistaken
for a gap nobody noticed.

### C1. Authentication is a stub that accepts anything — *critical*

*(Note: traffic is now encrypted, but encryption without authentication only
means an attacker's connection is private too. This is still the blocker.)*

`engine/auth.verify_challenge_response` returns `True` unconditionally, and
both the client and the admin answer with a fixed placeholder string. The
handshake's *motions* are real and exercised; its *verification* is not.

This is the intended Phase 7 sequencing, not an accident — but the current
build authenticates nobody. Anyone on the LAN can register as any client, or as
an admin, and issue commands.

**Run it only on an isolated or trusted network until Phase 7.**

### C2. Bundled Python packaging — *unblocked, deferred to Phase 8*

**Now scheduled last, deliberately.** Packaging code that has never been proven
on its target machine is the wrong order of work, and this has no design risk
left in it — so it gains least from being early and blocks nothing. Phase 5 now
exists to prove each system by hand first.

The cost of that ordering, stated plainly: Phase 5 exercises the *fallback*
paths listed below, not the shipped ones, so its results do not fully transfer.
Phase 8 carries a re-verification of the same ground.

**No longer waiting on a decision.** A5 is answered (B11): scripts are stdlib
and `subprocess` only, so the **embeddable distribution** is sufficient for the
script-execution runtime, and the import policy now enforces that.

What remains is the build work itself, not a choice:

Three fallbacks are live because the bundle does not exist yet, each logging a
warning: `admin/validation.py` and `client/executor.py` both fall back to
the running interpreter, and `client/lockout.py` runs the overlay as a module
instead of an executable. All three are development conveniences, not shippable.

**The helper windows are now QML, which narrows this rather than widening it.**
They were briefly tkinter; that was a bad call, introducing a second UI toolkit
into a project already committed to Qt 6 + QML, and one that fights the
frameless translucent design the README describes.

The two concerns stay independent, which is what keeps A5 answerable:

- **Script-execution runtime** — a plain interpreter running admin-authored
  scripts. Embeddable is still viable *if* your scripts are stdlib-only. This
  is what A5 actually decides.
- **Helper windows** — frozen with PyInstaller, carrying their own Qt. Not
  affected by the A5 answer either way, because an embeddable distribution has
  no pip and so could never have carried PySide6.

Build both helpers as **one** binary with a mode flag, so the Qt payload is
paid for once rather than twice.

### C10. Task Manager hardening is unverified on a managed machine — *narrowed*

Both helper windows have now been run for real. The dialog rendered, counted
down and returned exit code 2 (timed out) as designed; the overlay covered the
primary display for its full window, self-closed and exited 0. Neither produced
a QML error.

What remains unverified is the Task Manager policy. On this development machine
the `DisableTaskMgr` write fails with access denied — group policy owns that
key — so the overlay degrades to a plain fullscreen window and logs one line.
That degradation is the intended behaviour (losing the hardening must never
stop the lockout showing), but it means the enable-and-restore path has never
actually run.

Worth confirming on a real lab machine, where the agent runs as a service under
SYSTEM and should be able to write it. Check both directions: that Task Manager
is blocked during a block window, and that it works again afterwards.

Also still unverified: whether the 500ms topmost re-assert genuinely wins
against a determined Alt-Tab. Observable only by trying it.

```powershell
python -m client.dialog_app --message "Test warning" --timeout 15 --allow-cancel
python -m client.overlay_app --until 2026-08-06T15:00:00Z   # a near-future time
```

*(C3, transport being unencrypted, is resolved — see B12.)*

### C4. Handshake mechanics are untested until auth is switched on

`DEV_BYPASS_AUTH` skips the handshake entirely, deliberately, so bypassed
traffic is unmistakable in a packet capture.

Partly mitigated since Phase 1: the default path *does* run the full
challenge/response round trip with a stub verifier, and both client and admin
registration are covered by integration tests. What remains untested is
behaviour with real key material and a verifier that can actually reject.
Budget testing time for the first enablement.

### C6. Client RAM footprint (<50MB) unverified

The README's own non-functional requirement, which it flags as predating the
bundled runtime and the helper executables. Those are spawned on demand rather
than resident, so idle footprint may still be close to the estimate — but it
has never been measured. Measure in Phase 6 rather than restating the number.

### C11. Enforcement may never reach the user's screen under the service install — *unverified; gates deployment, not the defence*

Surfaced while checking whether two overlays could collide in production. The
collision cannot happen with one agent per machine (B24), but chasing where the
overlay actually *renders* raised a larger question that has never been asked.

Two code facts, both confirmed by reading:

- `install_service.py:115` creates the service with `sc create` and no `obj=`,
  which defaults to **LocalSystem**.
- `install_service.py:143` registers the watchdog task with `/RU SYSTEM` and no
  `/IT`, so it runs non-interactively.

Both therefore run in **session 0**, which has been isolated from the interactive
desktop since Windows Vista. `subprocess.Popen` places its child in the parent's
session. If that holds here, then under the packaged install:

- the lockout overlay renders in session 0, where the logged-in student cannot
  see it, while `enforce_once()` returns cleanly, the watchdog returns 0, Task
  Scheduler records a clean run and the log says "Block window active; ensuring
  the overlay is up";
- `overlay_app.py:87` writes `DisableTaskMgr` to `HKEY_CURRENT_USER`, which
  under SYSTEM is SYSTEM's hive, not the student's — so the hardening in C10
  would not reach them either.

That is a fail-open in the component whose entire job is to fail closed, and one
that reports success at every level.

**Not a regression.** Every run to date has been by hand from an interactive
prompt, where the overlay inherits your session and works. It is an assumption
that has never been tested, which is precisely what Phase 5 exists to catch.

**Detection is in, ahead of the fix.** `client/session.py` reports the process's
Windows session via `ProcessIdToSessionId` (stdlib `ctypes`, no dependency), and
`start_overlay` logs a warning before launching if it is running in session 0.
`python -m client --check` prints the session too. This does not fix anything —
it turns the silent half of the failure into a visible one, so T5.5 reads
"session 0, may be invisible" in the log instead of an unqualified "overlay
started". Correct whichever way the measurement goes, which is why it was worth
doing before it.

**Why this entry is not marked verified**: creating a service and a Scheduled
Task needs elevation, so this could not be settled from a normal session. The
reasoning is from documented Windows behaviour, not measurement. **Do not act on
it until it is measured** — `testing.md` T5.5–T5.7 are the tests.

**What it does and does not block.** At the current scope — a defence
demonstrated on VMs — it blocks nothing: run the agent by hand in the VM's
logged-in session, as every test to date has, and the overlay behaves normally
because session 0 never enters into it. It blocks a real *install*, where the
agent runs as a service. Worth measuring before Phase 6 all the same, since it
is cheap once a VM exists and it is the kind of question a panel may ask.

**Where it comes from, and what it is not.** Running as **SYSTEM** is what lands
in session 0 — not starting automatically. A Scheduled Task triggered at logon as
the *logged-on user* also starts by itself and lives in that user's session. The
two decisions are `sc create` with no `obj=` (defaults to LocalSystem) and
`schtasks /RU SYSTEM` with no `/IT`.

Underneath is a genuine conflict of requirements, not an oversight. The agent
must survive logoff, start before anyone logs in, and resist being closed by the
person being monitored — all of which say SYSTEM service. It must also put a
window in front of one specific logged-in person, which says that person's
session. Session 0 isolation exists precisely to stop the first from doing the
second.

**The affected surface is narrow**, which bounds the fix:

| | Session 0 acceptable? |
|---|---|
| Process, network and USB collection | yes — no UI |
| Command execution and scripts | yes |
| Hosts-file website policy | yes, and better — it needs the privilege |
| Schedule, state, watchdog logic | yes — files, not windows |
| **Overlay** | no — needs the user's session |
| **Warning dialog** | no — needs the user's session |
| **`DisableTaskMgr`** (written to `HKEY_CURRENT_USER`) | no — needs the user's hive |

So the answer is not "do not run as a service". It is "when this service needs to
reach a human, cross into their session deliberately".

**Two ways to fix it, if it needs fixing.** The session-1 program already exists
— `overlay_app.py` is a standalone executable that only draws a window. The
question is who starts it and when.

- **A — a persistent per-user helper**, auto-started at logon in the user's
  session, told what to do by the service over IPC. The standard pattern for
  products with a lot of per-user UI.
- **B — the service starts the existing helper in session 1 on demand**:
  `WTSGetActiveConsoleSessionId`, `WTSQueryUserToken`, `DuplicateTokenEx`,
  `CreateEnvironmentBlock`, then `CreateProcessAsUser` with
  `lpDesktop="winsta0\default"`. Argv stays the channel.

**B is the better fit here**, for two reasons that are specific to this system
rather than general:

- **A puts a killable process in the adversary's own session.** The helper runs
  as the monitored user, with their privileges, and before a block starts Task
  Manager is available. Kill it and no overlay ever appears. The service can
  notice, but restarting it in their session needs `CreateProcessAsUser` anyway
  — so A does not avoid the token code, it adds a component in front of it.
- **A needs an authenticated IPC channel.** A pipe the service uses to say "show
  the overlay" is a pipe someone could use to say "close the overlay". That is
  securable with a DACL, but it introduces a trust boundary into the component
  whose whole job is resisting the local user — the same category of work as C1.

B also fixes the `HKEY_CURRENT_USER` half for free: a process launched with the
user's token loads that user's hive. And it keeps helpers spawned on demand
rather than resident, which the README states as a design property.

Size: roughly one function and two call sites, ~60–80 lines. `pywin32==312` is
already declared in `requirements-client.txt` — though note it is currently
**declared but unused**: nothing imports it, and every Windows-specific path in
the client goes through `ctypes` or `winreg` instead. Decide after measuring,
not before.

### C15. Cross-session launch is implemented but its success path is untested

`client/session.spawn_in_active_session` launches the overlay into the
interactive session from a service — `WTSGetActiveConsoleSessionId`,
`WTSQueryUserToken`, `DuplicateTokenEx`, `CreateEnvironmentBlock`, then
`CreateProcessAsUserW` on `winsta0\default`. `client/lockout.start_overlay`
uses it when, and only when, the process is in session 0.

**Built ahead of the measurement, deliberately**, so that if C11 turns out to be
real the fix is already in place rather than being written under time pressure.
The cost of being wrong is bounded by two properties:

- **It cannot fire outside session 0.** `start_overlay` calls it only when
  `in_services_session()` is true, so the path used in development, in the
  demonstration and in every test is the unchanged `subprocess.Popen`. A test
  pins that.
- **Every failure returns None and falls through** to the ordinary spawn, which
  is exactly the behaviour before this existed. A fault here can never be the
  reason a lockout does not launch.

**What is actually proven**, against the real APIs rather than mocks:

- The library and prototype wiring, up to the privileged call. On an ordinary
  account `WTSQueryUserToken` returns WinError 1314, *"A required privilege is
  not held by the client"* — reaching that means the DLL, the argument types and
  the session lookup are all correct.
- `pid_is_running` against a live pid and a dead one.
- The fallback, the no-crossing-outside-session-0 rule, pid tracking in place of
  a `Popen`, and stopping a crossed overlay.

**What is not proven**: the success path. It needs a service in session 0, which
is T5.5–T5.7.

Two bugs were caught by smoke-testing this locally, which is worth recording
because both would have surfaced only in the VM and both look like permission
problems:

- `WTSGetActiveConsoleSessionId` is exported by **kernel32**, not wtsapi32,
  despite the WTS prefix. Loading it from wtsapi32 raises `AttributeError`.
- Without an explicit `restype`, ctypes assumes `int`, so the 64-bit `HANDLE`
  from `OpenProcess` came back truncated. Every prototype is now declared.

**If T5.5 shows the overlay is visible from a service anyway**, this is dead
code and should be deleted along with the `in_services_session()` branch in
`start_overlay` — not left in on the grounds that it might be useful. Removing
it is a smaller change than adding it was.

### C16. Two HWND arguments are passed without prototypes — *latent, low risk*

Found while auditing the codebase after C15's truncation bug, to see whether the
same class existed elsewhere. Mostly it does not: `IsUserAnAdmin`,
`GetLogicalDrives`, `GetDriveTypeW` and `GetTickCount` all return 32-bit values,
where ctypes' `c_int` default is harmless, and none of them return a handle.

Two places pass an `HWND` as a plain Python int with no `argtypes` declared:

- `client/monitors/process_monitor.py` — `IsWindowVisible`,
  `GetWindowTextLengthW`, `GetWindowTextW` inside `_enumerate_windows`.
- `client/ui_host.py:126` — `SetWindowPos` in `force_topmost`.

ctypes converts an undeclared argument to `c_int`, so a window handle above 2^32
would be truncated. **Empirically fine today**: HWND values on 64-bit Windows are
small handle-table indices, which is why window-title collection returns 212
processes with titles and why the overlay's topmost re-assert works.

**Not fixed yet, deliberately.** Both sites are in code that has been verified
working by hand, and the fix would be made immediately before a test run rather
than after one. Declare `argtypes`/`restype` on those four calls, then re-run
`python -m client --once` and check the window-title count has not changed, and
run the overlay to confirm it still comes forward.

Prevented from recurring in the new code by
`test_every_win32_prototype_is_declared`, which asserts every call used for the
cross-session launch has real types rather than the defaults.

**Why not switch to cffi**: the truncation was a missing declaration, not a
ctypes defect. cffi only improves on this in API mode, where a C compiler checks
the declarations at build time — which would pull a toolchain into Phase 8
packaging for one module, while every other Windows call in the client already
goes through ctypes. ABI mode would be a wash.

### C17. The Admin GUI looks like a prototype, not an operator tool

**Raised 2026-08-12.** Layout dimensions read as distorted, and the whole
window looks like scaffolding rather than an interface someone would run a lab
from. This is a real defect for a project defended by demonstration: the Admin
is the only component an audience sees for any length of time.

Distinct from every other open item here in that it is **presentation quality,
not correctness**. The Admin works — it registers, heartbeats, dispatches
commands, receives telemetry, and its QML loads clean under `--check-qml`.

**Two ways to fix it, and they are not close in cost.**

- **Fix the QML.** Sizing, spacing, alignment and a coherent visual hierarchy
  inside `admin/ui/`. Bounded, touches no architecture, and can be done
  incrementally between Phase 5 test runs.
- **Replace Qt with DearPyGui**, which was floated as an option. Costs are
  concrete rather than theoretical, and worth stating before anyone commits:
  - **qasync goes.** The Admin is single-threaded by design — asyncio runs on
    top of Qt's event loop, so the GUI, the Engine socket and every background
    task share one thread with no cross-thread marshalling anywhere. DearPyGui
    owns its own render loop, so that integration has to be rebuilt, and the
    README's rule that threads exist only for work that cannot signal readiness
    comes back into question.
  - **Two toolkits.** The client's dialog and overlay are QML specifically to
    match the Administrator. Moving the Admin alone leaves PySide6 in the client
    and DearPyGui in the Admin — the exact split CLAUDE.md forbids.
  - **Phase 8 packaging** gains a second GUI stack to freeze and test.
  - The overlay in particular is a full-screen composited window that re-asserts
    topmost every 500 ms and disables Task Manager; it is not a candidate for
    porting, so PySide6 stays in the project either way.

**Recommendation: fix the QML.** The complaint is about spacing, proportion and
polish, and none of that is a Qt limitation — it is unfinished layout work. A
toolkit swap would trade a bounded styling problem for an architectural one,
weeks before a defence.

**What would change this**: wanting immediate-mode plotting or dense real-time
dashboards that QML genuinely struggles with. Nothing in the current admin
surface is that.

#### The fleet-view proposal, and one change to it

Proposed 2026-08-12: a page showing a rectangle per connected client; selecting
one re-orients the dashboard to that client; with nothing selected the dashboard
shows everything across all clients.

**The shape is right and the data model already supports it.** The Engine fans
telemetry out to every admin (D5), so the Admin already receives every client's
data — this is a presentation change, not a protocol or storage one. It also
matches how someone actually thinks about a lab: *what machines do I have*, then
*what is machine 3 doing*.

**Make the tiles carry state, or they are a worse list.** Each should answer, at
a glance: connected or not, seconds since last heartbeat, whether a lockout or
pause is on screen right now, whether a script is running. All of that is state
the Engine already holds. A tile showing only a hostname is decoration.

That also happens to be the strongest thing in the demo — a tile visibly
changing state the moment a lockout is applied is far more convincing than a log
line, and it is worth designing the page around that moment.

**The one change: don't make selection a hidden global mode.** A separate page
plus a remembered selection means an operator can be looking at a dashboard and
not realise it is filtered — and the failure that follows is dispatching a
command believing the scope is one thing when it is another.

Prefer a **persistent left rail** listing clients, dashboard to the right.
Selection is then always visible as a highlighted row, "all clients" is just the
unselected state, and there is no mode to lose track of. It is also less work
than a separate page and a selection model that has to survive navigation.

**Keep view scope and command scope separate.** Selecting a client should narrow
what you *see*. It should not silently become the target of what you *send* —
command targeting stays an explicit choice at dispatch. The Engine already
treats it that way: every dispatch gets its own `command_id` even inside a
broadcast.

**Scale honestly.** Phase 6 talks about 10+ clients with a ceiling of 50. A grid
of tiles reads well to roughly 30 and badly beyond it; a rail scales further
because it is a list. Neither matters for the defence, where D8 limits the
realistic demo to one enforcing client plus others reporting telemetry — so
build for the demo and let the ceiling be a table later if it ever arrives.

#### Sequencing: after the system is proven, before authentication

Decided 2026-08-12, and it is the right order for a project defended by
demonstration:

1. **Prove Engine ↔ Admin ↔ Client end to end first.** That is Phase 5, and none
   of this UI work starts until it passes. Restyling a system that has not been
   shown to work is how you end up debugging both at once.
2. **Then this.** Ahead of authentication (C1) deliberately: C1 gates a
   *deployment*, and the Internal switch already contains it structurally for
   the defence, while the Admin is the one component an audience looks at for
   any length of time. The item that changes what the defence looks like
   outranks the item that changes what a deployment would need.

---

## D — Accepted limitations

**Deliberate decisions not to build something, recorded so they are not
mistaken for oversights.** Nothing here is scheduled. Each entry says what was
decided, why, and — most usefully — *what would change the answer*, so a future
reader can tell whether the reasoning still holds rather than re-deriving it.

Where an item was previously logged as an open issue, its old number is kept.

### D1. Storage stays relational; SQLite now, PostgreSQL if it grows

A document database was considered and rejected. The data is the wrong shape
for it: application samples, network counters and USB events are narrow,
fixed-field and uniform — the textbook relational/time-series case — and the
queries that matter are the ones document stores handle worst.
`get_weekly_network_summary` differences cumulative counters with
`LAG(...) OVER (PARTITION BY day ORDER BY timestamp)`; the equivalent is either
a window-function feature not every document store has, or pulling rows into
Python and looping.

Three costs specific to this project:

- The Engine is **standard-library only by design**, and `sqlite3` is in the
  standard library. Any document store adds a service to install, supervise,
  back up and secure on the Engine box, plus a driver — a new deployment
  surface, not a code change.
- Writes are **synchronous on the event loop by measurement** (5–8ms, ~3.5%
  duty cycle). A network hop to a database server invalidates that measurement
  and the design resting on it.
- At ~230k rows/day/client, per-document field-name overhead makes a document
  store *larger* than fixed rows, and the batched retention prune (B3) would be
  rewritten from scratch.

The one honest argument for documents is schema variability, and there is
exactly one variable field — `command_data` — already stored as JSON in a TEXT
column and queryable with SQLite's JSON1 if it ever needs to be.

**What would change this**: sustained write volume that the benchmark shows the
event loop can no longer absorb, or genuinely heterogeneous telemetry. The
answer then is the documented PostgreSQL path (all SQL is in `engine/database.py`,
so it stays a rewrite of one module) or rollup tables aggregating `app_logs`
into daily summaries — not a document model.

### D2. No per-client tables or collections

Partitioning storage per client was considered. `client_id` plus the existing
composite indexes already give that access path, and per-client partitioning
would break every fleet-wide aggregate — which is most of what the reports do.

**What would change this**: nothing at this scale. At a scale where it might,
partitioning is a PostgreSQL feature rather than a schema redesign.

### D3. No client → Engine → same-client flow

There is no flow where a client's own telemetry comes back to it as an action.
The obvious candidate — terminating a blacklisted application — is already
enforced **locally** by the agent on its collection cycle, which is strictly
better: local polling beats a 30-second round trip, and it keeps working when
the Engine is unreachable.

**What would change this**: a rule the client genuinely cannot decide alone.
Three plausible ones, none currently required — a network quota (the client
only has counters cumulative since boot and cannot compute real 24h usage,
`get_network_summary` can), a cross-client rule ("no more than N machines
running X"), or a history-based rule ("third attempt this week"). Build the
flow when one of those is actually wanted, not before; D4 explains why the
routing table makes that cheap.

### D4. The Engine stays stateless per message

The Engine does not orchestrate multi-hop sequences. Script execution looks
like admin → client → admin → client, but the admin drives the second hop; the
Engine routes each message independently and remembers nothing between them.

That is why adding a command type is one row in `_ROUTES`. Making the Engine
own such sequences means per-command state machines in it, which is a large
change with real value only if flows must be *enforced* rather than driven by
the operator.

**What would change this**: a requirement that a sequence complete without an
admin present — an automatic escalation, or a multi-step remediation that has
to finish even if the console closes.

### D5. Every admin receives every client's telemetry (was C5)

Live dashboard updates are push-based: `APP_DATA`, `NETWORK_DATA` and
`USB_EVENT` are forwarded to all connected admins, which then buffer per client
and display the selected one.

At the 50-client ceiling that is roughly 4,000 application rows every 30
seconds pushed to each admin, whether or not anyone is looking at them. Fine on
a LAN at project scale, and the admin bounds its own buffers
(`MAX_LIVE_SAMPLES`), but it does not scale gracefully.

The fix, if it ever matters, is a subscription: the admin tells the Engine
which client it is watching, and only that client's telemetry is relayed. That
is now a change to one route's `relay_to` in `_ROUTES` plus a subscription
registry, rather than an edit to three handlers (B13).

Unchanged in scale, but no longer unobservable: `routing.relay` reports what it
delivered and to whom it failed, so the cost of this fan-out is at least
measurable before anyone decides whether it needs fixing.

### D6. Whitelist filtering is approximated, not expressed (was C9)

Website filtering rewrites the hosts file. That works cleanly for blacklist
mode, which is the documented default. Whitelist mode is a poorer fit: a hosts
file has no "deny everything except" entry, so what actually gets written is
the set of domains the Engine listed as *not* permitted.

For the exam-session use case the README describes, that means the Engine has
to send a meaningful blocklist rather than just the allowed domain. A local
proxy would express whitelist properly and filter by URL path, at the cost of
shipping and supervising another service on every lab machine.

Also inherent to the hosts-file approach: it matches whole domains only, and a
browser using DNS-over-HTTPS bypasses it entirely.

### D7. Time restrictions are one-off windows, not recurring rules

The schedule editor (B16) sends a single start/end pair, because that is what
the client stores. It has no notion of weekly recurrence.

This was the deciding constraint: inventing a recurring wire format the client
cannot honour would produce an editor whose settings silently did nothing.
Recurrence is a client feature first — `client/lockout.py` would need to hold a
rule set and evaluate it — and a UI feature second.

**What would change this**: wanting "every weekday 09:00–10:00" without an
operator setting it each morning. Start in `client/lockout.py`, not the GUI.

### D8. One machine cannot simulate many *enforcing* clients

State is now per client (B21), so several agents on one box no longer overwrite
each other's lockout schedule, pause file or blacklist. What separate state does
not buy is a separate **screen**.

Two agents on one machine both entering a block window each launch a fullscreen
overlay on the same physical display. They fight: both re-assert topmost every
500ms, and whichever wins is arbitrary. The same applies to the warning dialog.

This is about agents under *different* ids, which is the supported simulation
case. Two agents under the **same** id are now refused outright (B24), and that
guard is deliberately keyed on the client id rather than the machine so it does
not take the table below away.

So the honest boundary for Phase 6's "10+ clients, ceiling 50":

| Simulatable on one box | Needs real separate machines |
|---|---|
| Heartbeats, registration, capacity caps | Lockout overlays |
| `APP_DATA`, `NETWORK_DATA`, `USB_EVENT` | Pause and resume |
| Reports and aggregation | Task Manager hardening (also C10) |
| The command audit trail and outbox | Anything a student would *see* |
| Policy dispatch and the hosts file* | |

\* One hosts file per machine, so several agents writing website policy will
also collide — the managed-block markers mean the last writer wins rather than
the file being corrupted, but it is still one shared resource.

**What would change this**: nothing worth building. Per-client virtual desktops
or a headless enforcement mode would be substantial work whose only consumer is
a test harness, and it would mean the thing under test is no longer the thing
that ships. Use real machines, or VMs, for the enforcement half.

### D9. The client VM runs stock Windows, not trimmed media

`scripts/build_client_image.ps1` produces a debloated Win11 24H2 ISO, and the
client VM was meant to be installed from it. It was tried on **2026-08-12** and
abandoned the same night.

**How it fails.** Windows installs cleanly, OOBE runs, a desktop appears — and
then the machine reboots into "choose country or region" and does so forever.
Completion is recorded under `HKLM\SYSTEM\Setup\Status\ChildCompletion`, and
something the trim removes stops that write. Alongside it, both Windows Hello
enrolment screens fail outright: `OOBEMSAHELLO` on the Microsoft-account path,
`OOBELOCALHELLO` on the local-account path, each needing a manual Skip.

**The unattend file is not the culprit.** On the second OOBE pass, entering
`lab` is refused with "type a different user name" — the account
`autounattend.xml` asked for exists already. The trim is what breaks.

**Why not repaired.** Two reasons. The justification for trimming was disk
(`testing.md` 0.1e), and disk stopped being the constraint — `K:` has ~625 GB
free, where the plan was written when ~70 GB was tight. And an image needing
registry surgery to complete its own installation is a poor foundation for a
phase that exists to establish trust in what the machine does: every later
oddity would carry "is this our bug or the debloat?", which is precisely the
question 0.1e's gate table was invented to answer and could no longer answer
credibly.

**What it costs.** Stock idles ~1 GB higher (~2.0–2.5 GB against ~1.2–1.5 GB),
which Dynamic Memory reclaims, and Defender comes back — a live false-positive
risk for the overlay's Task Manager policy and for Phase 8's PyInstaller exes.
Exclusions handle that, and a machine with Defender running is closer to the
one the agent actually ships to.

**What would change this**: needing several client VMs on a genuinely small
disk. The fix then is OOBE completion inside the script — start at the Appx
keep-list, not the service list — not a registry workaround downstream.
