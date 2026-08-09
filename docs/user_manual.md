# Operator Manual

For the person running the Administrator console. It assumes the Engine is
already serving and at least one lab machine has the agent installed — see
[installation.md](installation.md) for that.

```powershell
python -m admin --engine 10.0.0.5
```

## Before you start

**This tool watches people.** It records every running application and window
title, logs USB insertions, captures screens on demand, and can lock someone out
of the machine they are working at. Most institutions require ethics review or
IT sign-off before it points at computers real students use. Confirm you have
that.

Every command you send is written to an audit trail with your `ADMIN_ID`
against it, before it is dispatched. That is deliberate and not something you
can turn off.

## The window

A connection bar across the top, the client roster down the left, and three tabs
on the right: **Monitoring**, **Reports** and **Policy**. A **Commands** panel
sits below them.

Enter the Engine address and press **Connect**. The status line under the bar is
where every result and refusal appears — watch it, because most feedback lands
there rather than in a dialog.

### The roster

Every machine the Engine has ever seen, not just the ones online now. A client
that disconnects stays in the list marked disconnected rather than vanishing.

**Almost everything acts on the selected client.** If a button seems dead, check
you have selected one — the status line will say "Select a client first".

## Monitoring

Live data, pushed as it arrives, in three tabs.

- **Applications** — process name, PID, window title, CPU and memory, refreshed
  every 30 seconds.
- **Network** — bytes and packets sent and received, plus active connections,
  every 60 seconds. The client sends counters cumulative since it booted; the
  Engine differences them, so what you see in Reports is real usage.
- **USB Events** — insertions and removals. Drives already plugged in when the
  agent starts are not reported as insertions.

Buffers are kept **per client**, so switching selection and switching back loses
nothing that arrived meanwhile. Each is capped, so a long session does not grow
without bound.

## Commands

### Running a script

Python or PowerShell only, and **standard library plus `subprocess` only** — no
third-party packages.

Press **Check** before **Run script**. Check reports what the policy makes of
the script — syntax, and every import it accepts as well as every one it rejects
— without sending anything. Run script validates again and refuses to send if it
fails, so a broken script never reaches a lab machine.

Two things to know about the limit:

- Scripts are capped at **5 minutes**, 15 at the absolute most. This is an
  extension mechanism for small routine tasks, not a job runner.
- **A script stopped at the cap gets no chance to clean up.** On Windows there
  is no graceful kill, so a run interrupted mid-write leaves a partial file.
  Write scripts that are safe to interrupt.

Output streams into the panel as it is produced. A finished run reports
`timeout` distinctly from `error`, so "too slow" reads differently from
"crashed".

The import check is static analysis of import statements. It cannot catch
runtime-only platform assumptions — `os.fork()`, POSIX path shapes — which are
valid Python that simply fails on Windows.

### Screenshot

Captures the primary display of the selected client. Lower the quality if a
capture is refused for size.

### Terminate

**Terminate** kills one named process once. This is not the same as the standing
blacklist in Policy — see below.

## Reports

Five queries, run by the Engine on your behalf. The console never touches the
database directly.

| Report | Shows |
|---|---|
| Network 24h | Total sent and received over the last day |
| Network weekly | Per-day totals for the last 7 days |
| App usage | Per-application totals over 24h, busiest first |
| USB events | Recent insertions and removals |
| Command history | Recent dispatched commands and their outcomes |

Command history is the place to confirm something actually landed. Statuses:
`dispatched`, `running`, a final status from the client, `undeliverable` (the
client was offline and the command was not worth keeping), `queued` (offline,
but held for its return), `superseded` (a newer command of the same type
replaced it) or `expired` (queued too long).

Monitoring data older than the retention period — 30 days by default — is
deleted, so reports do not reach back indefinitely.

## Policy

### Website filtering

Choose **blacklist** (these domains are blocked, everything else loads — the
right default) or **whitelist** (only these load). The mode is always explicit;
it is never inferred.

Whitelist is for locked-down sessions like exams, and expect pages to break
unless you also list their CDN, font and SSO domains. Two limits worth knowing:
filtering rewrites the hosts file, so it matches **whole domains only**, and a
browser using DNS-over-HTTPS bypasses it entirely.

Entries go one per line. Both the bare and `www.` forms are blocked
automatically — blocking one alone does not bite.

### Applications

Two controls that look similar and are not:

- **Apply blacklist** sets the standing list, re-enforced on every collection
  cycle. Applying an empty list clears it.
- **Terminate now** kills one process once, and is in the Commands panel too.

Blocking a launch means terminating the process shortly after it starts —
there is no pre-launch hook without a kernel driver, so expect a brief window
where the application is visible.

Applications are **blacklist-only by design**. Whitelisting them cannot reliably
enumerate the OS and helper processes legitimate work depends on, so anything
unlisted is allowed. This asymmetry with website filtering is intentional.

### Time restriction

A **scheduled block**: the machine is locked for a set duration and the student
sees a countdown to the end of it.

Set a duration in minutes and, optionally, a delay before it starts — that delay
is how you set an exam lockout up in advance. The client stores the window
immediately and raises the overlay itself when the window opens, with no further
contact from the console.

A single block is capped at **2 hours**. If you ask for longer the console warns
you and the client shortens it. That cap is a safety timeout against the overlay
hanging, not a policy about session length; re-apply for a longer session.

**Block all clients** asks for confirmation. Locking one machine is recoverable
by walking to it; locking the room is not.

**Clear** lifts a block early. It does not touch a pause — if one is active the
machine stays held.

## Pause versus a scheduled block

Two different ways to hold a screen, and they are not interchangeable.

|  | Scheduled block | Pause |
|---|---|---|
| Has a stated end | Yes | No |
| Student sees | A countdown | "Paused", no countdown |
| Set from | Policy tab | Commands panel |
| Internally capped at | 2 hours | 1 hour |

A **pause** is you holding the screen live, with no stated end, dropped with
**Resume** when you are ready. It is capped at an hour internally, but that
number is never shown to the student — it is a safety net in case you close the
console or the network dies, not a promise about when they get their machine
back. The console warns you five minutes before it lapses, with an **Extend**
button, so a long hold stays a deliberate choice.

A pause **takes precedence** over a scheduled block. Dropping the pause while a
scheduled window is still open reverts to the countdown rather than releasing
the machine.

Pause state is tracked from what clients report in their heartbeats, not from
what this console asked for — so a pause set from another console shows up here,
and restarting the console recovers the state rather than losing it.

## When something does not appear to work

1. **Check the status line.** Most refusals are reported there, not in a dialog.
2. **Check a client is selected.** The commonest cause by far.
3. **Check the client is connected.** A durable policy command sent to an
   offline machine is queued and applied when it returns — Reports → command
   history shows `queued` rather than a failure.
4. **Check Reports → command history.** It distinguishes "never dispatched" from
   "dispatched and the client reported an error".

Enforcement is local to each client, which means a lockout or a policy keeps
working when the network drops — and equally, that clearing one needs the client
reachable again. Blocks lapse on their own regardless.
