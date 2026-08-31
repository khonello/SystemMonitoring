# The lab switch, and whether to give it a gateway

The lab runs on one Hyper-V **Internal** switch called `LabMonitor`. Internal
means the two VMs can reach each other and the host, and nothing else — there is
no gateway, so there is no internet. That is the right default and it is how
`LAB-SETUP.md` builds the lab.

There is exactly one demonstration it gets in the way of: **website filtering**.
This page is about that, and about putting the lab back afterwards.

| | Internal, no gateway (default) | Internal + NAT (this page) |
|---|---|---|
| VM ↔ VM | yes | yes |
| VM ↔ host | yes | yes |
| VM → internet | no | yes, outbound only |
| internet → VM | no | no |
| Addresses | unchanged | unchanged |
| Reversible | — | one command |

---

## Why the default is no gateway

Registration currently accepts anyone (`issues.md` C1). The Internal switch is
what contains that structurally: an Engine nothing can route to is an Engine
nothing can register with. Keeping the lab off the network is not laziness, it
is the reason an unauthenticated handshake is acceptable for a defence.

NAT does not give that away. It is outbound only — the guests can start
conversations, nothing on the outside can start one with them — so the Engine
stays unreachable from anywhere but the two machines on the switch. What you do
take on is ordinary internet exposure for two lab VMs: the Windows one now
downloads updates, and Defender matters again.

## Why website filtering needs one anyway

Filtering rewrites the guest's hosts file (`client/policy.py`), mapping each
blocked domain — and its `www.` form — to `127.0.0.1`. With no internet, every
site fails to load whether it is blocked or not, so a demonstration proves
nothing: **"blocked" and "there is no network" look identical on screen.** With
NAT, an unblocked site loads and a blocked one does not, which is the whole
point.

Nothing else in the system needs it. Registration, heartbeats, telemetry,
commands, scripts, screen capture, the application blacklist, scheduled blocks
and pauses are all lab-local and work exactly as they do now.

---

## Turning it on

Roughly five commands. The networking is the easy part — see *Two things that
will waste your afternoon* below, which matter more.

### 1. On the host, once — elevated PowerShell

The host already holds `192.168.100.1` on `vEthernet (LabMonitor)`, so it is
already the gateway address the guests need. It just is not forwarding or
translating yet.

```powershell
# Sanity check: this should print 192.168.100.1
Get-NetIPAddress -InterfaceAlias "vEthernet (LabMonitor)" -AddressFamily IPv4 |
    Select-Object IPAddress, PrefixLength

Set-NetIPInterface -InterfaceAlias "vEthernet (LabMonitor)" `
    -AddressFamily IPv4 -Forwarding Enabled

New-NetNat -Name LabMonitorNat -InternalIPInterfaceAddressPrefix 192.168.100.0/24
```

`New-NetNat` needs no reference to the internet-facing adapter: it translates
the lab prefix out over whatever the host's default route happens to be, so it
keeps working when the host moves between Wi-Fi, Ethernet and a phone hotspot.
This is why NAT rather than Internet Connection Sharing — ICS would seize the
interface and renumber it to `192.168.137.1`, taking every static address in the
lab with it.

### 2. On the Windows client — elevated PowerShell in the guest

```powershell
$if = (Get-NetAdapter | Where-Object Status -eq "Up").Name

New-NetRoute -InterfaceAlias $if -DestinationPrefix 0.0.0.0/0 `
    -NextHop 192.168.100.1 -ErrorAction SilentlyContinue

# The host is not a DNS server. Use a public resolver; NAT forwards it.
Set-DnsClientServerAddress -InterfaceAlias $if -ServerAddresses 1.1.1.1, 8.8.8.8

ping -n 2 1.1.1.1
nslookup example.com
```

### 3. On the Debian engine — as root (`su -`, there is no `sudo`)

Only needed if you want `apt` to work; the Engine does not need internet to run.

```bash
ip route add default via 192.168.100.1
echo "nameserver 1.1.1.1" >> /etc/resolv.conf
ping -c2 1.1.1.1
```

To survive a reboot, add `gateway 192.168.100.1` under the `iface` stanza in
`/etc/network/interfaces`. Leaving it out is a reasonable choice: the Engine
reverts to being unreachable from anywhere on its own.

---

## Turning it off

```powershell
# Host, elevated
Remove-NetNat -Name LabMonitorNat -Confirm:$false
Set-NetIPInterface -InterfaceAlias "vEthernet (LabMonitor)" `
    -AddressFamily IPv4 -Forwarding Disabled
```

```powershell
# Windows client, elevated, in the guest
$if = (Get-NetAdapter | Where-Object Status -eq "Up").Name
Remove-NetRoute -InterfaceAlias $if -DestinationPrefix 0.0.0.0/0 -Confirm:$false
Set-DnsClientServerAddress -InterfaceAlias $if -ResetServerAddresses
```

```bash
# Debian engine, as root
ip route del default
```

Nothing else changes. Addresses, the switch, the checkpoints and both `--check`
outputs are untouched either way, so this is safe to switch on for a rehearsal
and off again before taking a checkpoint.

---

## Two things that will waste your afternoon

Both are about the blocking, not the network, and both make a working system
look broken.

**The browser has to actually ask the operating system.** Edge and Chrome
default to DNS-over-HTTPS on many builds, which resolves names over an encrypted
connection to Cloudflare and never consults the hosts file at all. The block is
applied correctly, the file is written correctly, and the site loads anyway.
This is `issues.md` D6's known limitation, not a bug to chase. Turn it off in
the guest before demonstrating:

> Edge → Settings → Privacy, search and services → Security → **Use secure DNS**: off

**The agent must be elevated to write the hosts file.** Run the client agent
from an *administrator* terminal on the guest. Without it the command comes back
`Writing the hosts file needs administrator rights` — an error the console
reports honestly, and one that is easy to misread as a networking problem when
you have just been changing networking.

Also worth knowing, none of them faults:

- Windows caches DNS answers. `ipconfig /flushdns` in the guest between
  applying a policy and testing it, and close the browser tab rather than
  reloading it.
- The agent re-enforces standing policy every collection cycle, so a block lands
  within one cycle rather than instantly.
- Whitelist mode is approximated — a hosts file has no "deny everything except",
  so what is written is the set of domains the Engine listed as *not* permitted
  (`issues.md` D6). Demonstrate blacklist mode; explain whitelist.
- Blocked domains resolve to `127.0.0.1`, so the browser shows its own
  connection-refused page rather than a branded block page.

## If a second NAT conflicts

Windows supports one NAT instance. Hyper-V's built-in *Default Switch* already
does address translation on `172.29.128.0/20`, and on some builds adding a
second is refused or silently inert.

Symptom: `New-NetNat` succeeds but guests still cannot reach `1.1.1.1`, or it
fails outright. Check with `Get-NetNat`, and if something unrelated is listed:

```powershell
Get-NetNat | Remove-NetNat -Confirm:$false
New-NetNat -Name LabMonitorNat -InternalIPInterfaceAddressPrefix 192.168.100.0/24
```

## The no-internet alternative

If you would rather not connect the lab at all, the demonstration can be made
honest without a gateway: serve a page from the host on the lab subnet, give it
a name in the guest's hosts file *outside* the managed block, and then block
that name through the console. Two hostnames, one blocked and one not, both
served by the host — the audience sees one load and one fail, and the lab stays
isolated.

It is more setup for a weaker story, and the managed block is the thing being
demonstrated either way. Prefer NAT unless the isolation matters to you more
than the demonstration does.
