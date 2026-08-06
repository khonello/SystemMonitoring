# Open Issues

Known problems, deferred decisions and unverified claims — things that are
*wrong, undecided or unproven*, as opposed to simply not built yet.

This is not the roadmap. Work that is merely scheduled for a later phase lives
in [todo.md](todo.md); an item only belongs here if it would still be a problem
after its phase is finished, or if it blocks a phase from starting.

**[Section A](#a--needs-your-decision) needs your decision** — those cannot be
resolved by writing code. Sections B and C are engineering work.

Phases 0–4 are complete apart from packaging. Resolved items stay in section B
rather than being deleted, so the reasoning behind each decision survives.

**Currently blocking: nothing.** A5 is fully answered (see B11) and packaging
is unblocked — what remains there is build work, not a decision. Everything
left in section A is policy you can settle at any point before deployment.

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

### A2. Institutional approval for monitoring real machines

The system captures screenshots on demand, logs USB insertions, tracks every
running application and window title, and can lock users out of a machine.
Pointing it at real lab computers used by real students is a different
proposition from demonstrating it on your own hardware.

Most institutions require ethics review or IT sign-off before deploying
something like this, and the README's own "Removed Features" section shows the
project already reasoned about privacy — keylogging was cut on exactly these
grounds. Worth confirming what approval you need **before** Phase 5 testing,
not after.

Nothing in the code depends on this; it gates where you are allowed to run it.

### A3. How the master secret and per-client keys get onto machines

Phase 6 needs `client_key = HMAC(master_secret, client_id)` baked into each
client's install package. The README describes the scheme but not the
operational process: where the master secret is generated, how it is stored so
it is not lost, and how per-machine keys reach 50 lab computers.

This is a deployment process question rather than a coding one, and it shapes
what Phase 6 actually has to build. Related: A6.

### A4. Is TLS in scope for your submission?

Transport is plain JSON over TCP. Even after Phase 6 authentication, anyone who
can observe LAN traffic reads script contents, screenshots and lockout
schedules.

The README lists TLS under Future Enhancements but also says that for anything
beyond a classroom demo it should be a near-term follow-up to auth. Whether
that is in scope depends on how you intend to present and deploy the project.

Default if you do nothing: it stays out of scope, and the limitation is
documented rather than fixed.

*(A5 is answered and has moved to [B11](#b11-script-import-policy--done).)*

### A6. Admins authenticate as if they were clients — is that what you want?

The README says the admin holds *the master secret itself*, while each client
gets a derived key. The implemented handshake does not distinguish them: an
admin registers and answers the nonce challenge exactly like a client.

For Phase 6 that leaves a genuine design question — should an admin prove
possession of the master secret directly, or be issued a derived key like any
other peer? The second is simpler and safer (a compromised admin workstation
does not burn the whole fleet), but it departs from what the README describes.

Not urgent, but decide before Phase 6 rather than during it.

---

## B — Resolved

### B1. Idle admin connections were dropped after 60 seconds — **DONE**

`engine/main.py` applied the heartbeat timeout to every peer, and nothing made
an Admin GUI send traffic, so an operator reading a dashboard was disconnected
after a minute.

**Fixed** by giving the Admin GUI its own heartbeat task on the same 15s
interval a Client Agent uses (`admin_gui/connection.py`, `_heartbeat`). One
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
`python -m admin_gui.main`.

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

## C — Still open

### C1. Authentication is a stub that accepts anything — *critical*

`engine/auth.verify_challenge_response` returns `True` unconditionally, and
both the client and the admin answer with a fixed placeholder string. The
handshake's *motions* are real and exercised; its *verification* is not.

This is the intended Phase 6 sequencing, not an accident — but the current
build authenticates nobody. Anyone on the LAN can register as any client, or as
an admin, and issue commands.

**Run it only on an isolated or trusted network until Phase 6.**

### C2. Bundled Python packaging — *unblocked, still to be built*

**No longer waiting on a decision.** A5 is answered (B11): scripts are stdlib
and `subprocess` only, so the **embeddable distribution** is sufficient for the
script-execution runtime, and the import policy now enforces that.

What remains is the build work itself, not a choice:

Three fallbacks are live because the bundle does not exist yet, each logging a
warning: `admin_gui/validation.py` and `client/executor.py` both fall back to
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

### C9. Whitelist mode cannot be fully expressed in a hosts file — *new, from Phase 4*

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

### C3. Transport is unencrypted

See A4. Recorded separately so it is not lost inside the README's Future
Enhancements list.

### C4. Handshake mechanics are untested until auth is switched on

`DEV_BYPASS_AUTH` skips the handshake entirely, deliberately, so bypassed
traffic is unmistakable in a packet capture.

Partly mitigated since Phase 1: the default path *does* run the full
challenge/response round trip with a stub verifier, and both client and admin
registration are covered by integration tests. What remains untested is
behaviour with real key material and a verifier that can actually reject.
Budget testing time for the first enablement.

### C5. The Engine relays every client's telemetry to every admin — *new, from Phase 3*

Live dashboard updates are push-based: `APP_DATA`, `NETWORK_DATA` and
`USB_EVENT` are forwarded to all connected admins, which then buffer per client
and display the selected one.

At the 50-client ceiling that is roughly 4,000 application rows every 30
seconds pushed to each admin, whether or not anyone is looking at them. Fine on
a LAN at project scale, and the admin bounds its own buffers
(`MAX_LIVE_SAMPLES`), but it does not scale gracefully.

The fix, if it ever matters, is a subscription: the admin tells the Engine
which client it is watching, and only that client's telemetry is relayed.

### C6. Client RAM footprint (<50MB) unverified

The README's own non-functional requirement, which it flags as predating the
bundled runtime and the helper executables. Those are spawned on demand rather
than resident, so idle footprint may still be close to the estimate — but it
has never been measured. Measure in Phase 5 rather than restating the number.

### C7. `STREAM_LIMIT` never exercised by a large payload

Both ends are opened with a 16MB limit because asyncio's `StreamReader` caps a
line at 64KiB by default. Nothing has yet sent a message near either bound.

The first real test is base64 screen capture in Phase 4. A screenshot exceeding
16MB would surface as an unrelated-looking stream error, so exercise this
deliberately with a large capture rather than discovering it in the field.

### C8. `docs/` is empty

The README lists `docs/protocol.md`, `docs/installation.md` and
`docs/user_manual.md`. These are Week 4 deliverables in its own timeline; noted
so the empty directory is not mistaken for an oversight.
