#!/bin/sh
# Provisions the Phase 5 Engine VM from the inside.
#
# Run this INSIDE LabEngine, as root, after Debian is installed.
# testing.md sections 0.1f and 0.5.
#
# POSIX sh on purpose: a Debian netinst with everything deselected in tasksel
# has dash as /bin/sh and no bash guarantees worth relying on.
#
# The Engine imports only the standard library, so there is nothing to pip
# install and no venv. `apt install python3` is the entire dependency list.
#
# WHY THE sqlite3 CHECK IS A HARD FAILURE.
# The Engine owns all persistence through SQLite (engine/database.py). It is
# the one stdlib module a minimal or stripped Python build can be missing, and
# everything else the Engine imports is unconditional. Debian carries it; the
# check exists so that a smaller image chosen later cannot fail quietly at the
# first write instead of loudly here.
#
# WHY DEBIAN 12 OR 13 AND NEVER 11.
# Bullseye ships Python 3.9.2, under this project's requires-python = ">=3.10".
# Debian 11 was downloaded first during this build-out and thrown away for it.

set -eu

REPO="${REPO:-/opt/SystemMonitoring}"
# Who will actually RUN the Engine. This script runs as root, so everything it
# creates is owned by root -- and the Engine writes (it owns all persistence).
RUN_AS="${RUN_AS:-lab}"
STATIC_IP="${STATIC_IP:-192.168.100.2}"
NETMASK="${NETMASK:-255.255.255.0}"
HOST_IP="${HOST_IP:-192.168.100.1}"
DRY_RUN="${DRY_RUN:-0}"
# REFRESH=1 copies a newer disc over an existing tree. Without it an
# existing repository is left alone, which is right for provisioning and
# useless for iterating -- and iterating is what actually happens once the
# lab is up and the code is still changing.
REFRESH="${REFRESH:-0}"

say()   { printf '\n%s\n' "$*"; }
ok()    { printf '  [ok]   %s\n' "$*"; }
have()  { printf '  [have] %s\n' "$*"; }
warn()  { printf '  [warn] %s\n' "$*"; }
doing() { if [ "$DRY_RUN" = "1" ]; then printf '  [dry]  %s\n' "$*"; else printf '  [do]   %s\n' "$*"; fi; }
run()   { if [ "$DRY_RUN" = "1" ]; then return 0; fi; "$@"; }

# --- preconditions -----------------------------------------------------------

say 'Checking preconditions'

# Not "re-run with sudo": setting a root password during the install is exactly
# what stops Debian from installing sudo at all, so on this VM there is none.
[ "$(id -u)" -eq 0 ] || { echo 'Not root. Run "su -" first (this VM has no sudo -- Debian only installs it when the root password is left blank), then re-run this script.' >&2; exit 1; }
ok 'running as root'

if [ -r /etc/os-release ]; then
    . /etc/os-release
    ok "guest is ${PRETTY_NAME:-unknown}"
    case "${VERSION_ID:-}" in
        11|11.*) echo 'Debian 11 ships Python 3.9, below this project floor of 3.10. Reinstall from a Debian 12 or 13 netinst.' >&2; exit 1 ;;
    esac
fi

# --- python ------------------------------------------------------------------

say '1. Python'

if command -v python3 >/dev/null 2>&1; then
    have "python3 present: $(python3 -V 2>&1)"
else
    doing 'apt install python3'
    run apt-get update -qq
    run apt-get install -y python3
fi

if [ "$DRY_RUN" != "1" ]; then
    PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    case "$PYVER" in
        3.10|3.11|3.12|3.13|3.14) ok "python3 is $PYVER" ;;
        *) echo "python3 is $PYVER, below the 3.10 floor (pyproject.toml requires-python)." >&2; exit 1 ;;
    esac

    if python3 -c 'import sqlite3; print("  [ok]   sqlite3", sqlite3.sqlite_version)'; then
        :
    else
        echo 'python3 has no sqlite3 module. The Engine cannot persist anything without it. Reinstall from a Debian netinst rather than a stripped image.' >&2
        exit 1
    fi
fi

# --- repository --------------------------------------------------------------

say '2. Repository'

if [ -f "$REPO/pyproject.toml" ] && [ "$REFRESH" != "1" ]; then
    have "repository at $REPO (REFRESH=1 to copy a newer disc over it)"
else
    # LabRepo.iso, built on the host, is the least fiddly route in -- it needs
    # no ssh, no shared folder and no network at all. Attach it on the host:
    #   Set-VMDvdDrive -VMName LabEngine -Path K:\LabRepo.iso
    doing "copy repository from /dev/sr0 to $REPO"
    if [ "$DRY_RUN" != "1" ]; then
        if [ ! -b /dev/sr0 ]; then
            echo "No /dev/sr0. Attach LabRepo.iso to this VM's DVD drive on the host:" >&2
            echo '  Set-VMDvdDrive -VMName LabEngine -Path <lab-drive>:\LabRepo.iso' >&2
            exit 1
        fi
        # REUSE AN EXISTING MOUNT RATHER THAN MAKING A SECOND ONE. You reached
        # this script by mounting the disc yourself -- LAB-SETUP.md step 8 says
        # `mount -o ro /dev/sr0 /mnt`, because there is no other way to run a
        # script that only exists on the disc. An earlier version then did
        # `mkdir -p /mnt/labrepo`, i.e. created a directory INSIDE the
        # read-only medium it had just been pointed at, and died with
        # "Read-only file system" while following our own procedure (2026-08-13).
        SRC=$(awk '$1 == "/dev/sr0" { print $2; exit }' /proc/mounts)
        UNMOUNT_AFTER=0
        if [ -n "$SRC" ]; then
            have "disc already mounted at $SRC"
        else
            # /tmp, never /mnt: /mnt is exactly where a person would have put it.
            SRC=/tmp/labrepo
            mkdir -p "$SRC"
            mount -o ro /dev/sr0 "$SRC"
            UNMOUNT_AFTER=1
        fi

        # REPLACE THE TREE, DO NOT MERGE INTO IT. A `cp -r` over an existing
        # checkout leaves behind every file the disc no longer carries: a module
        # deleted upstream still imports, a renamed script still runs, and the
        # guest ends up running a mixture of two versions that exists nowhere
        # else. Merging is how you get a bug that cannot be reproduced on the
        # machine the code came from.
        #
        # THE DATABASE SURVIVES. The Engine owns all persistence and keeps
        # monitoring.db in this directory, so deleting the tree wholesale would
        # throw away the record as a side effect of a code update -- exactly the
        # kind of silent, unrelated consequence this project keeps refusing
        # elsewhere. It is moved aside and put back. Pass FRESH_DB=1 to start
        # empty instead.
        KEPT=""
        if [ -d "$REPO" ]; then
            case "$REPO" in
                ""|"/"|"/usr"|"/etc"|"/var"|"/home")
                    echo "Refusing to replace '$REPO' -- that is not a repository directory." >&2
                    exit 1 ;;
            esac

            if [ "${FRESH_DB:-0}" != "1" ]; then
                KEPT=$(mktemp -d)
                for db in "$REPO"/*.db; do
                    [ -e "$db" ] || continue
                    doing "preserving $(basename "$db") across the refresh"
                    mv "$db" "$KEPT"/
                done
            else
                warn 'FRESH_DB=1: the existing monitoring database will be deleted'
            fi

            doing "removing the previous tree at $REPO"
            rm -rf "$REPO"
        fi

        mkdir -p "$REPO"
        cp -r "$SRC"/. "$REPO"/

        if [ -n "$KEPT" ]; then
            for db in "$KEPT"/*.db; do
                [ -e "$db" ] || continue
                mv "$db" "$REPO"/
            done
            rmdir "$KEPT" 2>/dev/null || true
        fi

        if [ "$UNMOUNT_AFTER" = "1" ]; then
            umount "$SRC"
            rmdir "$SRC" 2>/dev/null || true
        fi

        # Files off a CD arrive read-only.
        chmod -R u+w "$REPO"
    fi
fi

# OWNERSHIP, NOT JUST MODE. chmod u+w grants write to the OWNER, and everything
# above ran as root, so the owner is root. The Engine runs as an ordinary user
# and writes monitoring.db into this directory -- SQLite needs write on the file
# AND on the directory, for its journal. Without this the Engine registers a
# client and dies with "attempt to write a readonly database" (2026-08-13).
#
# This runs whether or not the copy just happened: an existing tree from an
# earlier run has the same problem, and re-running the script is how it is fixed.
if [ "$DRY_RUN" != "1" ]; then
    if id "$RUN_AS" >/dev/null 2>&1; then
        doing "chown -R $RUN_AS:$RUN_AS $REPO"
        chown -R "$RUN_AS:$RUN_AS" "$REPO"
    else
        warn "no user '$RUN_AS' on this system -- $REPO stays owned by root"
        warn 'the Engine will fail with "attempt to write a readonly database" unless it is run as root'
        warn "re-run with RUN_AS=<user> once that account exists"
    fi
fi

# certs/ is gitignored, so it reaches this machine only by copying rather than
# cloning. TLS is presence-based: without it this VM would serve plaintext and
# refuse the client, logging a refusal that does not name the cause.
if [ "$DRY_RUN" != "1" ]; then
    if [ -f "$REPO/certs/engine-cert.pem" ] && [ -f "$REPO/certs/engine-key.pem" ]; then
        ok 'certs/ present (cert and key)'
    else
        echo "certs/ is missing or incomplete under $REPO. This came from a clone, not a copy. See testing.md 0.4." >&2
        exit 1
    fi
fi

# --- network -----------------------------------------------------------------

say "3. Static address $STATIC_IP"

IFACE=$(ip -o link show 2>/dev/null | awk -F': ' '$2 != "lo" {print $2; exit}')
[ -n "$IFACE" ] || { echo 'No non-loopback interface found.' >&2; exit 1; }
ok "interface $IFACE"

if ip -4 addr show "$IFACE" 2>/dev/null | grep -q "$STATIC_IP"; then
    have "$IFACE already has $STATIC_IP"
else
    doing "write $STATIC_IP into /etc/network/interfaces"
    if [ "$DRY_RUN" != "1" ]; then
        cp /etc/network/interfaces /etc/network/interfaces.bak
        cat >> /etc/network/interfaces <<EOF

# LabMonitor -- Phase 5 isolated switch (testing.md 0.1).
# NO gateway line, deliberately: with no default route this guest reaches the
# host and the client VM and nothing else, which is what keeps the stubbed
# authentication (issues.md C1) off every real network by construction.
auto $IFACE
iface $IFACE inet static
    address $STATIC_IP
    netmask $NETMASK
EOF
        ifdown "$IFACE" 2>/dev/null || true
        ifup "$IFACE" 2>/dev/null || true
    fi
fi

# --- self-check --------------------------------------------------------------

say '4. python3 -m engine --check'

if [ "$DRY_RUN" != "1" ]; then
    # AS THE USER WHO WILL RUN THE ENGINE, not as root. A check run under a
    # different identity than the program is a check that can lie: this one
    # passed as root, printed "Database ready", and the Engine then failed on
    # its first write as `lab` because the tree was root-owned (2026-08-13).
    # Run from the repo root so `common/` resolves -- there is no editable
    # install on this machine and none is needed.
    if id "$RUN_AS" >/dev/null 2>&1; then
        ok "running --check as $RUN_AS, the account that will run the Engine"
        su - "$RUN_AS" -c "cd '$REPO' && python3 -m engine --check"
    else
        warn "no user '$RUN_AS' -- checking as root, which does NOT prove an ordinary user can write"
        ( cd "$REPO" && python3 -m engine --check )
    fi
    printf '\n  Check the transport line says TLS with a certificate path.\n'
    printf '  PLAINTEXT means the certificate is not where the Engine looks.\n'
    printf '  Check the authentication line does NOT say BYPASSED -- that is\n'
    printf '  DEV_BYPASS_AUTH set in this shell.\n'
fi

say 'Done. What is left:'

cat <<EOF
  1. Shut this VM down:  poweroff
  2. On the HOST:  .\\scripts\\lab_host_finalize.ps1 -VMName LabEngine
  3. Start it, and serve:
       cd $REPO && ENGINE_LOG_LEVEL=DEBUG python3 -m engine
     It binds 0.0.0.0, which on this VM means only the isolated switch.
  4. Gate T0.1, from the CLIENT VM:
       Test-NetConnection $STATIC_IP -Port 5000
     TcpTestSucceeded : True. Part 1 does not start until it passes.

  Ping to $HOST_IP failing is not a fault -- the host firewall drops ICMP by
  default on a new Internal switch. setup_lab_vms.ps1 adds a rule for it.
  Nothing real depends on ICMP; the gate above is TCP.
EOF
