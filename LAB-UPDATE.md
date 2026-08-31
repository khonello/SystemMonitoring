# Changed the code — now get it into the lab

The loop you actually spend time in. `LAB-SETUP.md` builds the lab once and
explains why each of these steps exists; this page is just the sequence and the
five things that bite. When the two disagree, `LAB-SETUP.md` is the reasoning
and this is the summary — fix both.

Three machines, and the code has to reach two of them:

| | Runs | Repo lives at | Needs the update? |
|---|---|---|---|
| **Host** | Admin console | your working copy | already has it |
| **LabEngine** | Engine | `/opt/SystemMonitoring` | **yes, always** |
| **LabClient** | Client agent | `C:\SystemMonitoring` | only if `client/` or `common/` changed |

---

## The loop

### 1. Host — cut the disc

**Elevated PowerShell**, no arguments:

```powershell
cd <your working copy>
.\scripts\build_repo_iso.ps1
```

It finds every VM holding the image, ejects, waits for the file to come free,
copies, puts the disc back in every drive it took it from, and re-checks after
eight seconds. Wait for `still attached after settling`.

Do **not** pass `-AttachTo` — it is only for putting the disc into a machine
that does not have it yet. Naming a subset is how this goes wrong.

Elevated matters: unelevated, Hyper-V refuses to enumerate VMs, the sweep is
skipped with a warning, and the copy fails against whatever holds the file.
Unelevated is fine only when both VMs are off.

### 2. LabEngine — refresh and restart

At the console, logged in as `lab`:

```sh
su -
mount -o ro /dev/sr0 /mnt
REFRESH=1 sh /mnt/scripts/lab_engine_setup.sh
exit
cd /opt/SystemMonitoring && ENGINE_LOG_LEVEL=DEBUG python3 -m engine
```

`REFRESH=1` is what makes this an *update* — without it the script sees an
existing tree and leaves it alone. It replaces the tree rather than merging, so
a file deleted upstream stops existing here too, and it keeps `monitoring.db`.

The script ends by running `python3 -m engine --check` **as `lab`**, which is
the check that counts. Expect TLS with `certs/engine-cert.pem`, authentication
not bypassed, and `Database ready.`

`exit` back to `lab` before starting the Engine. Running it as root leaves
root-owned files that `lab` then cannot write, and the Engine dies on its first
write with `attempt to write a readonly database`.

### 3. LabClient — copy and restart the agent

In the guest, as an **administrator** (the agent needs it to write the hosts
file for website filtering):

```powershell
Copy-Item D:\* C:\SystemMonitoring -Recurse -Force
Get-ChildItem C:\SystemMonitoring -Recurse -File | ForEach-Object { $_.IsReadOnly = $false }
cd C:\SystemMonitoring
.\environ\Scripts\python.exe -m client --check
.\environ\Scripts\python.exe -m client --engine 192.168.100.2
```

The venv is `environ` on this build, not `.venv`, and it is not on the disc, so
the copy leaves it alone. The `IsReadOnly` sweep matters: files off a CD keep
that attribute and the agent writes inside its own tree.

### 4. LabEngine — release the disc

```sh
umount /mnt
```

Before the next re-cut, not after. Linux holds the medium while it is mounted
and the host cannot take it back.

### 5. Host — the console

```powershell
.\.venv\Scripts\python.exe -m admin
```

Connect to `192.168.100.2:5000`, select the machine. You are looking for the
roster entry going `LIVE`, the stat tiles moving, and the Engine's log showing
`heartbeat from … (idle=…)` every fifteen seconds.

---

## The faster loop, if you have ssh

If *SSH server* was ticked at tasksel, the Engine can be updated with no disc,
no eject and nothing typed in the guest:

```powershell
ssh lab@192.168.100.2 "echo ok"        # check first - it is optional at install
scp -r engine common certs lab@192.168.100.2:/opt/SystemMonitoring/
```

If that first line fails, you do not have it. Installing `openssh-server` needs
the internet, which the isolated switch does not have — either turn on NAT
(`LAB-NETWORK.md`) or move the VM to the Default Switch for the install and back
afterwards. Not worth it mid-session; use the disc.

The disc exists for a machine with no network, no account and no tooling, which
is true while you are building and false once the lab is up. Re-cutting discs
repeatedly in one session is the signal to switch.

---

## The five that bite

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot write …LabRepo.iso — being used by another process`, and the guest says nothing is mounted | A running VM holds the host file **whether or not the guest mounted it**. A Windows guest never mounts anything and pins it just the same | Run the build elevated with no arguments so it sweeps every holder. Failing that, shut both VMs off |
| A guest's DVD drive is empty after a failed build | An eject succeeded, then the copy threw. The script restores drives it emptied, but only within the same run | `Get-VMDvdDrive -VMName <vm> \| Set-VMDvdDrive -Path <lab-drive>:\LabRepo.iso` |
| The Engine still behaves like the old code | `REFRESH=1` was omitted, so the script found a tree and left it | Re-run with `REFRESH=1` |
| `attempt to write a readonly database` | The Engine was started as root, or the tree is root-owned | `chown -R lab:lab /opt/SystemMonitoring` as root, then run the Engine as `lab` |
| A script is "not found" in the guest, or behaves like an older version | The disc is a snapshot and goes stale in silence | Re-cut. The build hashes `lab_engine_setup.sh` on the disc against your working copy for exactly this |

More symptoms, with the reasoning: `LAB-SETUP.md` § *Pitfalls*.

---

## The scripts

| Script | Where | What it does here |
|---|---|---|
| `scripts/build_repo_iso.ps1` | host, elevated | Cuts the disc and swaps it into every VM holding it |
| `scripts/lab_engine_setup.sh` | LabEngine, as root | `REFRESH=1` to replace the tree; chowns to `lab`; runs `--check` as `lab` |
| `scripts/lab_client_setup.ps1` | LabClient | Full provision. Not needed for a code update — the copy above is enough |
| `scripts/vm_console_shot.ps1` | host | Reads a guest's screen from outside when nothing else can see it |

All take `-DryRun` (`DRY_RUN=1` for the shell one) and are safe to re-run.

Related: **`LAB-SETUP.md`** builds the lab from nothing. **`LAB-NETWORK.md`**
gives the switch a gateway for the website-filtering demonstration.
**`testing.md`** is what you run once the code is in place.
