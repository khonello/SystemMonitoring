<#
.SYNOPSIS
    Creates the Phase 5 lab: Hyper-V storage on K:, the LabMonitor switch, and
    both VMs with the settings that are painful to fix after creation.

.DESCRIPTION
    testing.md sections 0.1, 0.1d and 0.1f. This does the mechanical half of
    Part 0 -- everything up to "insert media and install an OS". It does not
    install Windows or Debian; those are interactive and stay manual.

    WHY A SCRIPT AND NOT THE WIZARD.
    Three settings cannot be changed after a VM is created, or can only be
    changed by recreating it, and all three fail with messages that do not name
    the cause:

      - Generation 2. A Gen 1 VM has no Security page at all, so no TPM, so
        Windows 11 Setup refuses with "This PC can't run Windows 11".
      - TPM enabled. A Gen 2 VM has a virtual TPM but it is OFF by default and
        the creation wizard never offers it. Same generic Setup refusal.
      - Secure Boot template. Gen 2 defaults to "MicrosoftWindows", which will
        not boot Debian -- it fails without saying why. The Engine VM needs
        "MicrosoftUEFICertificateAuthority".

    Everything here is idempotent: existing switches, VMs and IP addresses are
    reported and left alone rather than recreated. Safe to re-run after fixing
    one thing.

    WHAT THIS DELIBERATELY DOES NOT DO.
      - Dynamic Memory on the client VM. testing.md 0.1 installs Windows with a
        static 4 GB and switches afterwards, because Windows Setup misbehaves
        under a moving allocation. The script prints the reminder and the exact
        numbers at the end.
      - The LabMonitor adapter on either VM. Both are created on Default Switch
        for provisioning internet and move to LabMonitor afterwards
        (testing.md 0.1d step 8, 0.1f step 6).
      - Anything to the guests. No OS, no Python, no repository.

    NOTHING HERE IS TIED TO ONE MACHINE. This lab is built on a dev box and
    rebuilt on the presentation machine, which has a different disk layout, so
    the drive is discovered rather than assumed and the media is found by
    pattern rather than by path. Every parameter can still be passed explicitly.

.PARAMETER ClientIso
    Windows 11 media. Found automatically if omitted: Win11*.iso on the lab
    drive, in its \ISO or \Disc folders, or in Downloads.

    Use STOCK retail media. The trimmed image from build_client_image.ps1 was
    tried and abandoned -- it installs, but OOBE never records completion, so
    the machine loops back to "choose country or region" forever, and both
    Windows Hello enrolment screens fail (OOBEMSAHELLO, OOBELOCALHELLO). The
    autounattend account is created correctly, which is how you can tell the
    trim rather than the unattend is what broke. testing.md 0.1e, issues.md D9.

.PARAMETER EngineIso
    Debian netinst, found automatically if omitted. **Debian 12 or 13 only** --
    11 ships Python 3.9.2, below this project's floor of 3.10, and is refused
    here rather than three hours later. If no netinst is found the Engine VM is
    skipped with a notice and the rest still runs; re-run once it downloads.

.PARAMETER LabRoot
    Where VMs and VHDXs live. Discovered if omitted: the fixed drive with the
    most free space and at least 90 GB, preferring a non-system drive. Hyper-V's
    own default is on the system drive and is a common way to run a machine out
    of room.

.PARAMETER DryRun
    Print every action without taking it. Run this first.

.EXAMPLE
    .\scripts\setup_lab_vms.ps1 -DryRun
    .\scripts\setup_lab_vms.ps1
    .\scripts\setup_lab_vms.ps1 -LabRoot 'D:\LabMonitor'

.NOTES
    Requires an ELEVATED PowerShell. Hyper-V cmdlets fail with a bare
    "You do not have the required permission" otherwise.
#>

[CmdletBinding()]
param(
    [string] $ClientIso,
    [string] $EngineIso,
    [string] $LabRoot,
    [string] $ClientName = 'LabClient',
    [string] $EngineName = 'LabEngine',
    [string] $SwitchName = 'LabMonitor',
    [string] $HostIp     = '192.168.100.1',
    [int]    $Prefix     = 24,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

function Say    { param($m) Write-Host "  $m" }
function Step   { param($m) Write-Host "`n$m" -ForegroundColor Cyan }
function Ok     { param($m) Write-Host "  [ok]   $m" -ForegroundColor Green }
function Skip   { param($m) Write-Host "  [have] $m" -ForegroundColor DarkGray }
function Warn   { param($m) Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Doing  { param($m) if ($DryRun) { Write-Host "  [dry]  $m" -ForegroundColor Magenta } else { Write-Host "  [do]   $m" } }

# Nothing below hardcodes a drive letter. This lab is built on one machine and
# rebuilt on another (the presentation machine), and the second one has a
# different disk layout -- so the drive is discovered, not assumed.
function Resolve-LabDrive {
    <# Largest fixed drive with room for both VMs, preferring a non-system one. #>
    $need = 90    # client VHDX can grow to 64 GB, plus media and checkpoints
    $candidates = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType = 3' |
        ForEach-Object {
            [pscustomobject]@{
                Letter   = $_.DeviceID
                FreeGB   = [math]::Round($_.FreeSpace / 1GB, 1)
                IsSystem = ($_.DeviceID -eq $env:SystemDrive)
            }
        } | Where-Object FreeGB -ge $need | Sort-Object IsSystem, @{E='FreeGB';D=$true}

    if (-not $candidates) {
        $all = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType = 3' |
               ForEach-Object { '{0} {1:N1} GB free' -f $_.DeviceID, ($_.FreeSpace/1GB) }
        throw "No fixed drive has $need GB free. Found: $($all -join '; '). Pass -LabRoot explicitly if you know better."
    }
    $candidates[0]
}

function Find-LabIso {
    <# Look for media by pattern, in the obvious places, before giving up. #>
    param([string[]] $Patterns, [string] $LabDriveLetter, [string] $What)

    $searchDirs = @(
        "$LabDriveLetter\",
        (Join-Path $LabDriveLetter '\ISO'),
        (Join-Path $LabDriveLetter '\Disc'),
        (Join-Path $env:USERPROFILE 'Downloads'),
        (Split-Path $PSScriptRoot -Parent)
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

    foreach ($dir in $searchDirs) {
        foreach ($pat in $Patterns) {
            $hit = Get-ChildItem -Path $dir -Filter $pat -File -ErrorAction SilentlyContinue |
                   Sort-Object Length -Descending | Select-Object -First 1
            if ($hit) { return $hit.FullName }
        }
    }
    return $null
}

# --- preconditions ----------------------------------------------------------

Step 'Checking preconditions'

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Not elevated. Right-click PowerShell -> Run as administrator, then re-run.'
}
Ok 'running elevated'

if (-not (Get-Module -ListAvailable -Name Hyper-V)) {
    throw 'The Hyper-V PowerShell module is not present. Enable Hyper-V in Windows Features first, then reboot.'
}
Ok 'Hyper-V module present'

if ($LabRoot) {
    $labDrive = Split-Path -Qualifier $LabRoot
    if (-not (Test-Path "$labDrive\")) { throw "Drive $labDrive does not exist." }
    $free = [math]::Round((Get-PSDrive -Name $labDrive.TrimEnd(':')).Free / 1GB, 1)
} else {
    $chosen  = Resolve-LabDrive
    $labDrive = $chosen.Letter
    $free     = $chosen.FreeGB
    $LabRoot  = Join-Path $labDrive 'LabMonitor'
    Say "no -LabRoot given; chose $labDrive automatically"
}
Ok ("lab root $LabRoot  ({0} has {1:N1} GB free)" -f $labDrive, $free)
if ($free -lt 90) {
    Warn 'Under 90 GB free. The client VHDX alone can grow to 64 GB.'
}
if ($labDrive -eq $env:SystemDrive) {
    Warn "This is the system drive. Fine if the space is genuinely there -- Hyper-V's own default lives here and is often what runs a machine out of room."
}

if (-not $ClientIso) {
    $ClientIso = Find-LabIso -Patterns @('Win11*.iso','*Win11*x64*.iso','*windows*11*.iso') `
                             -LabDriveLetter $labDrive -What 'Windows 11'
}
if (-not $ClientIso -or -not (Test-Path $ClientIso)) {
    throw @"
No Windows 11 media found. Searched $labDrive\, $labDrive\ISO, $labDrive\Disc and Downloads.

Get a retail Win11 24H2 x64 ISO and either drop it on $labDrive\ or pass
-ClientIso. Use STOCK media -- testing.md 0.1e records why the trimmed image
from build_client_image.ps1 is not used.
"@
}
Ok "client media: $ClientIso"

if (-not $EngineIso) {
    $EngineIso = Find-LabIso -Patterns @('debian-1[23]*netinst*.iso','debian*netinst*.iso') `
                             -LabDriveLetter $labDrive -What 'Debian netinst'
}
$haveEngineIso = $EngineIso -and (Test-Path $EngineIso)
if ($haveEngineIso) {
    # Bullseye ships Python 3.9.2, under this project's requires-python = ">=3.10".
    # Debian 11 was downloaded first during the first build-out and thrown away
    # for exactly this, after the ISO was already on disk. Catch it here instead.
    if ((Split-Path $EngineIso -Leaf) -match 'debian-11') {
        throw @"
$EngineIso is Debian 11 (bullseye), which ships Python 3.9.2 -- below this
project's floor of 3.10 (pyproject.toml requires-python).

Download a Debian 12 or 13 netinst instead:
  https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/
Roughly 755 MB for trixie; netinst images have carried non-free firmware by
default since Debian 12, so a file larger than the old ~630 MB is expected.
"@
    }
    Ok "engine media: $EngineIso"
} else {
    Warn "no Debian netinst found -- the Engine VM will be skipped."
    Warn 'Download the Debian netinst (amd64, ~630 MB) from debian.org, then re-run this script.'
}

# --- host storage -----------------------------------------------------------

Step "1. Hyper-V storage -> $LabRoot"

$vmPath  = Join-Path $LabRoot 'VMs'
$vhdPath = Join-Path $LabRoot 'VHDs'

foreach ($p in @($LabRoot, $vmPath, $vhdPath)) {
    if (Test-Path $p) {
        Skip $p
    } else {
        Doing "create $p"
        if (-not $DryRun) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
    }
}

$vmHost = Get-VMHost
if ($vmHost.VirtualMachinePath -eq $vmPath -and $vmHost.VirtualHardDiskPath -eq $vhdPath) {
    Skip 'Hyper-V default paths already point at LabRoot'
} else {
    Say "currently: VM=$($vmHost.VirtualMachinePath)  VHD=$($vmHost.VirtualHardDiskPath)"
    Doing "set VM path -> $vmPath, VHD path -> $vhdPath"
    if (-not $DryRun) {
        Set-VMHost -VirtualMachinePath $vmPath -VirtualHardDiskPath $vhdPath
    }
}

# --- switch -----------------------------------------------------------------

Step "2. Internal switch '$SwitchName'"

$sw = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
if ($sw) {
    Skip "switch exists (type $($sw.SwitchType))"
    if ($sw.SwitchType -ne 'Internal') {
        Warn "existing switch is $($sw.SwitchType), not Internal. Delete it or pass -SwitchName."
    }
} else {
    Doing "create Internal switch '$SwitchName'"
    if (-not $DryRun) { New-VMSwitch -Name $SwitchName -SwitchType Internal | Out-Null }
}

$alias = "vEthernet ($SwitchName)"
if ($DryRun -and -not $sw) {
    Doing "assign $HostIp/$Prefix to '$alias'"
} else {
    $existing = Get-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object { $_.IPAddress -eq $HostIp }
    if ($existing) {
        Skip "$alias already has $HostIp"
    } else {
        Doing "assign $HostIp/$Prefix to '$alias'"
        if (-not $DryRun) {
            # The adapter appears asynchronously after the switch is created.
            $adapter = $null
            for ($i = 0; $i -lt 10 -and -not $adapter; $i++) {
                $adapter = Get-NetAdapter -Name $alias -ErrorAction SilentlyContinue
                if (-not $adapter) { Start-Sleep -Milliseconds 500 }
            }
            if (-not $adapter) { throw "Adapter '$alias' never appeared after creating the switch." }
            New-NetIPAddress -InterfaceAlias $alias -IPAddress $HostIp -PrefixLength $Prefix | Out-Null
        }
    }
}

# Windows classifies a brand-new Internal switch as a PUBLIC network and enables
# no inbound ICMP echo rule, so `ping 192.168.100.1` from a guest times out on a
# switch that is working perfectly. That reads as a broken lab and is not one.
# Nothing real depends on ICMP -- the client dials the Engine over TCP and the
# host only ever makes outbound connections -- but ping is the first thing
# anyone reaches for, so it should tell the truth.
Step "2b. Host firewall on '$alias'"

if ($DryRun -and -not $sw) {
    Doing "set '$alias' to Private and allow inbound ICMPv4 echo"
} else {
    $profileNow = Get-NetConnectionProfile -InterfaceAlias $alias -ErrorAction SilentlyContinue
    if ($profileNow -and $profileNow.NetworkCategory -eq 'Private') {
        Skip "'$alias' already Private"
    } elseif ($profileNow) {
        Doing "set '$alias' from $($profileNow.NetworkCategory) to Private"
        if (-not $DryRun) {
            Set-NetConnectionProfile -InterfaceAlias $alias -NetworkCategory Private
        }
    }

    $ruleName = 'LabMonitor ICMPv4 in'
    if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
        Skip "firewall rule '$ruleName' exists"
    } else {
        Doing "allow inbound ICMPv4 echo on '$alias'"
        if (-not $DryRun) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol ICMPv4 `
                -IcmpType 8 -Action Allow -Profile Any -InterfaceAlias $alias | Out-Null
        }
    }
}

# --- VM builder -------------------------------------------------------------

function New-LabVm {
    param(
        [string] $Name,
        [int64]  $MemoryBytes,
        [int]    $Cpu,
        [int64]  $DiskBytes,
        [string] $Iso,
        [string] $SecureBootTemplate,
        [bool]   $EnableTpm
    )

    if (Get-VM -Name $Name -ErrorAction SilentlyContinue) {
        Skip "VM '$Name' already exists -- leaving it untouched"
        return
    }

    $vhd = Join-Path $vhdPath "$Name.vhdx"
    Doing "create '$Name': Gen 2, $Cpu vCPU, $([math]::Round($MemoryBytes/1GB,2)) GB static, $([math]::Round($DiskBytes/1GB)) GB dynamic VHDX"
    Doing "  media: $Iso"
    Doing "  secure boot template: $SecureBootTemplate"
    if ($EnableTpm) { Doing '  TPM: enabled' }

    if ($DryRun) { return }

    New-VM -Name $Name -Generation 2 -MemoryStartupBytes $MemoryBytes `
           -NewVHDPath $vhd -NewVHDSizeBytes $DiskBytes `
           -SwitchName 'Default Switch' -Path $vmPath | Out-Null

    # Static memory. Dynamic Memory is applied to the client VM only AFTER
    # Windows Setup finishes -- testing.md 0.1.
    Set-VMMemory -VMName $Name -DynamicMemoryEnabled $false
    Set-VMProcessor -VMName $Name -Count $Cpu

    # A saved-state .bin file the size of assigned RAM is held for the whole
    # time the VM runs unless the stop action is ShutDown.
    Set-VM -Name $Name -AutomaticStopAction ShutDown -AutomaticStartAction Nothing
    Set-VM -Name $Name -SmartPagingFilePath $vmPath -SnapshotFileLocation $vmPath

    # Windows 11 Hyper-V takes an automatic checkpoint on first start, which
    # puts the VM on a differencing disk before it has even installed. That
    # collides with the deliberate baseline/pre-service checkpoints Phase 5
    # reverts to. Clear a stray one with Remove-VMSnapshot, never by deleting
    # the .avhdx -- that breaks the disk chain.
    Set-VM -Name $Name -AutomaticCheckpointsEnabled $false

    if ($EnableTpm) {
        # A TPM needs a key protector before it can be enabled.
        Set-VMKeyProtector -VMName $Name -NewLocalKeyProtector
        Enable-VMTPM -VMName $Name
    }

    Set-VMFirmware -VMName $Name -EnableSecureBoot On -SecureBootTemplate $SecureBootTemplate

    Add-VMDvdDrive -VMName $Name -Path $Iso

    # DVD first, hard disk second, and no network entry at all. PXE has no boot
    # server on the Default Switch, so leaving it in the order only means a
    # missed "press any key" prompt costs 30+ seconds instead of a few.
    # testing.md 0.1d explains why that prompt is so easy to miss.
    $dvd = Get-VMDvdDrive -VMName $Name
    $hd  = Get-VMHardDiskDrive -VMName $Name
    Set-VMFirmware -VMName $Name -BootOrder $dvd, $hd

    Ok "'$Name' created"
}

# --- the two VMs ------------------------------------------------------------

Step "3. Client VM '$ClientName'  (testing.md 0.1d)"
New-LabVm -Name $ClientName -MemoryBytes 4GB -Cpu 2 -DiskBytes 64GB `
          -Iso $ClientIso -SecureBootTemplate 'MicrosoftWindows' -EnableTpm $true

Step "4. Engine VM '$EngineName'  (testing.md 0.1f)"
if ($haveEngineIso) {
    New-LabVm -Name $EngineName -MemoryBytes 512MB -Cpu 1 -DiskBytes 8GB `
              -Iso $EngineIso -SecureBootTemplate 'MicrosoftUEFICertificateAuthority' -EnableTpm $false
} else {
    Warn 'skipped -- no Debian ISO. Re-run this script after downloading it.'
}

# --- what is left, which is all interactive ---------------------------------

Step 'Done. What is left, in order:'

@"
  BEFORE YOU START EITHER VM -- the boot prompt is easy to miss
    Windows and Debian media both show a "press any key to boot" prompt for
    about five seconds. VMConnect renders nothing until it attaches, so if you
    start the VM and THEN open its window, the window opens after the prompt
    has already expired and every key you press does nothing. It looks exactly
    like a broken keyboard. The order that works:

      1. Leave the VM off.
      2. Open its console first (double-click it in Hyper-V Manager).
      3. Click inside the black area so the window has focus.
      4. Action -> Start, from inside that window.
      5. Tap the spacebar continuously from the moment you click Start.

    PXE is already out of the boot order, so a missed prompt costs a few
    seconds. testing.md 0.1d has the full account.

  CLIENT VM  ($ClientName)
    1. Start it and install Windows. At the edition prompt choose
       WINDOWS 11 PRO -- T4.5 needs gpedit.msc, which Home does not have.
    2. Stock media carries no autounattend.xml, so make the local account
       by hand at OOBE. The route on Pro:
         "Set up for work or school" -> Sign-in options -> Domain join instead
       Then user lab, password lab. Leave the network up through OOBE;
       24H2 fights offline installs.
    3. Defender is live on stock media. It is a false-positive risk for the
       overlay (it disables Task Manager) and for Phase 8's PyInstaller
       exes. Add exclusions when it first bites; do not disable it blind.
    4. Python 3.10+, tick "Add python.exe to PATH".
    5. Copy the repository in (Enhanced Session drive redirection).
       COPY, DO NOT git clone -- certs/ is gitignored and a clone leaves
       this machine on plaintext while the Engine uses TLS (0.4).
    6. pip install -r requirements.txt -r requirements-client.txt
       pip install -e .
    7. python -m client --check
       -> id resolves, three MISSING bundles, "agent running False"
    8. SHUT DOWN, then switch to Dynamic Memory:
         Set-VM -Name $ClientName -DynamicMemory -MemoryStartupBytes 2GB ``
                -MemoryMinimumBytes 1GB -MemoryMaximumBytes 3GB
         Set-VMMemory -VMName $ClientName -Buffer 10
       Static 4 GB was only for Setup.
    9. Move the adapter to '$SwitchName', static 192.168.100.3/24, no gateway.
   10. Checkpoint "baseline", then "pre-service" before T5.4.
       The 0.1e gate table was for the trimmed image and no longer applies:
       stock Windows needs no proof that it is a sound test bed.

  ENGINE VM  ($EngineName)
    1. Install Debian. DESELECT EVERYTHING in tasksel -- no desktop.
    2. sudo apt install python3
    3. python3 -c "import sqlite3; print(sqlite3.sqlite_version)"
    4. Copy the repository in -- again, COPY, not git clone (certs/, 0.4).
       Nothing to pip install; run from the repo root so common/ resolves.
    5. Static 192.168.100.2/24, no gateway, in /etc/network/interfaces.
    6. python3 -m engine --check
    7. Checkpoint "baseline".

  GATE (testing.md 0.4)
    Test-NetConnection 192.168.100.2 -Port 5000   from the client VM
    -> TcpTestSucceeded : True.  Part 1 does not start until this passes.
"@ | Write-Host

if ($DryRun) {
    Write-Host "`nDRY RUN -- nothing was changed. Re-run without -DryRun.`n" -ForegroundColor Magenta
}
