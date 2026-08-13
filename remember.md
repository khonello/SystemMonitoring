# Things to remember

One page of the things that are easy to forget and annoying to rediscover.
Details live in the linked docs; this is the list you reread after a week away.

## Before you run anything

**`python -m client`, not `python client/main.py`.** The path forms silently
ignore every flag — config is read into `Final` constants at import time, so
`cli.py` has to set the environment *before* importing the component. Same for
`engine` and `admin`. → [commands.md](commands.md)

**`--check` first, always.** Each unit answers "did I resolve what you think I
did" without touching the network: `engine --check`, `client --check`,
`admin --check-qml`. Most integration bugs are configuration bugs.

## Worth getting right

**Never put the Engine on a network you do not control.** Authentication is a
stub that accepts anyone (`issues.md` C1): whoever reaches port 5000 can register
as an **admin** and issue commands. TLS does not help — encryption without
authentication only means the attacker's session is private too. The Internal
switch handles this by construction, having no route anywhere; under topology A
it is a rule you have to keep. → [testing.md](testing.md) section 0.1c

**Give the overlay a machine you are not using.** It covers the screen, disables
Task Manager and re-asserts topmost every 500ms until its `--until` time. It
closes itself and restores the policy on exit, and blocks are capped at 2 hours —
so the cost of getting this wrong is a screen you cannot use for a while, not a
machine to repair.

**Snapshot the VM before `install_service`.** It registers a boot-start service
and a Scheduled Task running every 5 minutes as SYSTEM. `--uninstall` removes
both, but reverting a snapshot is faster and lets you rerun the test as many
times as you like.

**`w32tm /resync` after every snapshot revert.** Lockout schedules are time-based
and HMAC-protected. A stale VM clock makes block windows look expired or not yet
started, which reads exactly like an enforcement bug.

## The Hyper-V VMs

Full build in [testing.md](testing.md) sections 0.1 and 0.1d. Worth knowing without
looking them up:

**The vTPM is off by default and Setup will not tell you.** Generation 2 VMs have
a virtual TPM, but the creation wizard never offers it, and Windows 11 stops with
a generic *"This PC can't run Windows 11"* naming no requirement.

Hyper-V Manager → select the VM → shut it down (the box is greyed out while it
runs) → *Settings…* → **Hardware → Security** → *Encryption Support* → tick
**Enable Trusted Platform Module**. Check *Secure Boot* on the same page is on
with template *Microsoft Windows*.

No **Security** node means the VM is **Generation 1** — no UEFI, no Secure Boot,
no vTPM, and Windows 11 will not install. Generation cannot be changed after
creation, so delete it and make a new Gen 2 VM.

**The setup is two VMs on an Internal switch**, Admin on the host: no port
proxy, no NAT addresses that move on reboot, and no route from the Engine to any
real network — which is what keeps an Engine that authenticates nobody safe by
construction rather than by rule. **Internal, not Private**: Private excludes the
host, and the Admin lives there. Fits 16 GB with the Admin on the host; a third
VM for the Admin does not. Topology A (Engine in WSL, port proxy) is the fallback
for a machine short on disk. See [testing.md](testing.md) section 0.1.

**Two adapters per VM during provisioning, one after.** Give each VM the
Internal switch *and* a Default Switch adapter so OOBE and `pip` have internet,
then remove the Default Switch one. **Do not leave a VM on no network at all** —
the Internal switch is how the client reaches the Engine, and Part 5 needs it.
(Disconnecting it *is* how T5.3 simulates network loss, temporarily.) Adapters
are changeable any time at **VM → Settings → Network Adapter**.

**Static IPs on the Internal switch** — it has no DHCP. Host `192.168.100.1`,
Engine `.2`, Client `.3`, `/24`, no gateway. Nothing moves when the host reboots,
unlike topology A's two NAT ranges.

**`scripts/vm_console_shot.ps1 -VMName <vm>` reads a running guest's screen from
the host** — Hyper-V's WMI thumbnail API, no agent and nothing typed into the
guest. It is the only way to see a VM sitting at a boot menu or an installer,
and it makes the screen quotable instead of described.

## The Engine guest (Debian), in five lines

Full walk-through in [LAB-SETUP.md](LAB-SETUP.md) steps 7–8. The ones that cost
hours on 2026-08-13:

**512 MB is the runtime size, not the install size.** Debian 13 drops into
low-memory mode below ~1 GB and starts asking which udebs to load. Install at
2 GB; `lab_host_finalize.ps1` cuts it back.

**tasksel: Space toggles, Enter accepts the page.** Enter is right on every
other screen of the install, which is exactly why this one catches people. And
clearing *Debian desktop environment* is not enough — the indented `... GNOME`
is a separate task, ticked by default. A four-digit file count on the next
screen means a desktop is going in: power off and redo.

**There is no `sudo`,** because a root password was set — Debian installs sudo
only when that is left blank. `su -`, with the dash, for root's `PATH`.

**The keyboard layout follows the keyboard, not the country.** `@` above the `2`
key means US, `"` means UK. Wrong answer types `|` as `>`, so pipes become
redirects and the shell runs a different command than the one you wrote.

**A finished dialog often leaves its ghost on the console.** It looks frozen and
is not; `clear`.

## The Admin console

**Selection is a subscription, not just a highlight.** Clicking a machine tells
the Engine to relay only that client's telemetry here *and* asks it to sample
every 3s instead of 30/60. Deselecting releases it. Recording is unaffected by
any of this — the Engine persists every sample regardless of who is watching.

**Colours and spacing live in `admin/qml/Theme.qml`.** One palette, a 4px scale,
30px controls, 4px radius. Don't inline a colour. Primary navigation is in the
header; a choice *within* a page is a `SegmentedControl`, never a second
`TabBar` — that stacking is what made the old layout read as a mistake.

**QML cannot bind to `rowCount()`** — no change signal, so it evaluates once and
never again. Use the models' `count` property.

**`admin --check-qml` after touching any `.qml`.** It loads the whole tree
offscreen under the same style the console uses, and exits 1 on any warning.

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

## Scope

**This is a project defence, demonstrated on VMs.** Not a deployment, not real
lab machines, nobody monitored but you. Two things follow:

- **No institutional approval is in play** (`issues.md` A2). It becomes real the
  moment the monitored person is not you — a voluntary pilot counts. A panel may
  still ask; the honest answer is that the requirement is understood and the
  project already cut keylogging on those grounds.
- **C11 gates a real install, not the demo.** Run the agent by hand in the VM and
  the overlay behaves normally, because session 0 never enters into it.

## Open, and worth not rediscovering

**C11 is unverified** — the agent's service and the watchdog task both run as
SYSTEM in session 0, isolated from the interactive desktop, so the overlay may
render where nobody can see it while every log line reports success. Needs
elevation. `testing.md` T5.5–T5.7 measure it. Gates a real install; see Scope.

**C15: the session-0 fix is written but its success path has never run.** The
overlay is launched into the interactive session when, and only when, the agent
is in session 0; everywhere else the old spawn is used unchanged, and every
failure falls back to it. If T5.5 shows the overlay was visible from a service
all along, delete it rather than keeping it.

**C12 and C14 are fixed** (now B25 and B26). The overlay holds its own lock in
`STATE_DIR`, so every launcher can see it; `dialog_app --help` exits 0.

**Check `issues.md` section D before "fixing" anything that looks missing.**
Eight things there are decisions, not gaps.

## Naming

| | |
|---|---|
| `issues.md` **A/B/C/D** | needs your decision / resolved / open / accepted limitation. The letter is the status, so an item's letter changes when it is fixed (C13 → B21). Numbers are never reused. |
| `testing.md` **T<part>.<n>** | test ID: part number, then sequence. T5.5 is Part 5, test 5. |

## The six docs

| | |
|---|---|
| [README.md](README.md) | design spec. Can lag the code — where they disagree, the code is newer |
| [todo.md](todo.md) | the phase plan |
| [issues.md](issues.md) | what is wrong, undecided or unproven |
| [commands.md](commands.md) | every command and flag. Tracks the code |
| [testing.md](testing.md) | the Phase 5 manual test plan, and the reasoning behind the lab |
| [LAB-SETUP.md](LAB-SETUP.md) | how to build that lab from nothing, on any Windows 11 Pro machine. Ten steps, four scripts, symptom-first pitfalls. This is the one you follow with your hands |
