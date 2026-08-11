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
