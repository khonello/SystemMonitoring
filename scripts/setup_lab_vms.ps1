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

.PARAMETER ClientIso
    Trimmed Windows 11 media from scripts/build_client_image.ps1.

.PARAMETER EngineIso
    Debian netinst. If it is not there yet, the Engine VM is skipped with a
    notice and the rest still runs -- re-run once the download finishes.

.PARAMETER LabRoot
    Where VMs and VHDXs live. Must not be C:, which has under 5 GB free.

.PARAMETER DryRun
    Print every action without taking it. Run this first.

.EXAMPLE
    .\scripts\setup_lab_vms.ps1 -DryRun
    .\scripts\setup_lab_vms.ps1

.NOTES
    Requires an ELEVATED PowerShell. Hyper-V cmdlets fail with a bare
    "You do not have the required permission" otherwise.
#>

[CmdletBinding()]
param(
    [string] $ClientIso  = 'K:\Win11-LabClient.iso',
    [string] $EngineIso  = 'K:\debian-netinst.iso',
    [string] $LabRoot    = 'K:\LabMonitor',
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

# --- preconditions ----------------------------------------------------------

Step 'Checking preconditions'

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Not elevated. Right-click PowerShell -> Run as administrator, then re-run.'
}
Ok 'running elevated'

if (-not (Get-Module -ListAvailable -Name Hyper-V)) {
    throw 'The Hyper-V PowerShell module is not present. Enable Hyper-V in Windows Features first.'
}
Ok 'Hyper-V module present'

$labDrive = (Split-Path -Qualifier $LabRoot)
if ($labDrive -eq 'C:') {
    throw "LabRoot is on C:, which has under 5 GB free. Pass -LabRoot on another drive."
}
$free = (Get-PSDrive -Name $labDrive.TrimEnd(':')).Free / 1GB
Ok ("{0} has {1:N1} GB free" -f $labDrive, $free)
if ($free -lt 90) {
    Warn 'Under 90 GB free. The client VHDX alone can grow to 64 GB.'
}

if (-not (Test-Path $ClientIso)) { throw "Client ISO not found: $ClientIso" }
Ok "client media: $ClientIso"

$haveEngineIso = Test-Path $EngineIso
if ($haveEngineIso) {
    Ok "engine media: $EngineIso"
} else {
    Warn "engine media not found at $EngineIso -- the Engine VM will be skipped."
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

    if ($EnableTpm) {
        # A TPM needs a key protector before it can be enabled.
        Set-VMKeyProtector -VMName $Name -NewLocalKeyProtector
        Enable-VMTPM -VMName $Name
    }

    Set-VMFirmware -VMName $Name -EnableSecureBoot On -SecureBootTemplate $SecureBootTemplate

    Add-VMDvdDrive -VMName $Name -Path $Iso
    $dvd = Get-VMDvdDrive -VMName $Name
    Set-VMFirmware -VMName $Name -FirstBootDevice $dvd

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
  CLIENT VM  ($ClientName)
    1. Start it and install Windows. Edition Pro. Leave the network up
       through OOBE -- 24H2 fights offline installs.
    2. Python 3.10+, tick "Add python.exe to PATH".
    3. Copy the repository in (Enhanced Session drive redirection).
       COPY, DO NOT git clone -- certs/ is gitignored and a clone leaves
       this machine on plaintext while the Engine uses TLS (0.4).
    4. pip install -r requirements.txt -r requirements-client.txt
       pip install -e .
    5. python -m client --check
       -> id resolves, three MISSING bundles, "agent running False"
    6. SHUT DOWN, then switch to Dynamic Memory:
         Set-VM -Name $ClientName -DynamicMemory -MemoryStartupBytes 2GB ``
                -MemoryMinimumBytes 1GB -MemoryMaximumBytes 3GB
         Set-VMMemory -VMName $ClientName -Buffer 10
       Static 4 GB was only for Setup.
    7. Move the adapter to '$SwitchName', static 192.168.100.3/24, no gateway.
    8. Checkpoint "baseline", then run the 0.1e gate table, then
       checkpoint "pre-service".

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
