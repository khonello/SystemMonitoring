<#
.SYNOPSIS
    Host-side finishing pass for a Phase 5 VM: Dynamic Memory, checkpoint
    policy, the LabMonitor replug, and the "baseline" checkpoint.

.DESCRIPTION
    Run this on the HOST, elevated, once a guest OS is installed and provisioned
    inside the VM. testing.md sections 0.1 and 0.5.

    The three scripts and their order:

      1. setup_lab_vms.ps1     host     before anything -- storage, switch,
                                        host address and firewall, both VMs
      2. lab_client_setup.ps1  guest    inside LabClient, after Windows
         lab_engine_setup.sh   guest    inside LabEngine, after Debian
      3. lab_host_finalize.ps1 host     this one, per VM, at the end

    WHY DYNAMIC MEMORY IS APPLIED HERE AND NOT AT CREATION.
    Windows Setup misbehaves under a moving allocation, so the client VM is
    created with a static 4 GB and converted afterwards. Startup 2 GB / minimum
    1 GB / maximum 3 GB, with the buffer dropped from its 20% default, is what
    makes the whole lab fit in 8 GB (testing.md 0.1) -- Hyper-V hands back what
    the guest is not touching, which is a bigger win than anything inside the
    guest.

    The Engine VM is left on static memory: Dynamic Memory needs the guest
    balloon driver and buys nothing at 512 MB.

.PARAMETER VMName
    Which VM to finish. Memory settings are chosen from the name.

.PARAMETER SkipCheckpoint
    Do everything except the "baseline" checkpoint.

.PARAMETER DryRun
    Print every action without taking it.

.EXAMPLE
    .\scripts\lab_host_finalize.ps1 -VMName LabClient -DryRun
    .\scripts\lab_host_finalize.ps1 -VMName LabClient
    .\scripts\lab_host_finalize.ps1 -VMName LabEngine

.NOTES
    Requires an ELEVATED PowerShell. The VM must be OFF: memory mode and
    adapter changes are refused or unreliable on a running VM.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $VMName,
    [string] $SwitchName     = 'LabMonitor',
    [string] $CheckpointName = 'baseline',
    [switch] $SkipCheckpoint,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

function Step  { param($m) Write-Host "`n$m" -ForegroundColor Cyan }
function Ok    { param($m) Write-Host "  [ok]   $m" -ForegroundColor Green }
function Skip  { param($m) Write-Host "  [have] $m" -ForegroundColor DarkGray }
function Warn  { param($m) Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Doing { param($m) if ($DryRun) { Write-Host "  [dry]  $m" -ForegroundColor Magenta } else { Write-Host "  [do]   $m" } }

Step 'Checking preconditions'

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Not elevated. Right-click PowerShell -> Run as administrator, then re-run.'
}
Ok 'running elevated'

$vm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
if (-not $vm) { throw "No VM named '$VMName'. Run setup_lab_vms.ps1 first." }

if ($vm.State -ne 'Off') {
    throw "'$VMName' is $($vm.State). Shut it down from inside the guest first -- memory mode cannot be changed while it runs, and a checkpoint of a running VM also captures its memory, which is not what a baseline wants."
}
Ok "'$VMName' is Off"

# --- memory -----------------------------------------------------------------

Step '1. Memory'

if ($VMName -eq 'LabEngine') {
    Skip 'Engine VM stays on static 512 MB -- Dynamic Memory needs the balloon driver and buys nothing at this size'
} else {
    if ($vm.DynamicMemoryEnabled -and $vm.MemoryStartup -eq 2GB) {
        Skip 'Dynamic Memory already 2 GB / 1 GB / 3 GB'
    } else {
        Doing 'Dynamic Memory: startup 2 GB, minimum 1 GB, maximum 3 GB, buffer 10%'
        if (-not $DryRun) {
            Set-VM -Name $VMName -DynamicMemory `
                   -MemoryStartupBytes 2GB -MemoryMinimumBytes 1GB -MemoryMaximumBytes 3GB
            Set-VMMemory -VMName $VMName -Buffer 10
        }
    }
}

# --- checkpoint policy ------------------------------------------------------

Step '2. Checkpoint policy'

if (-not $vm.AutomaticCheckpointsEnabled) {
    Skip 'automatic checkpoints already off'
} else {
    # Left on, Hyper-V snapshots the VM on first start and puts it on a
    # differencing disk, which collides with the deliberate baseline and
    # pre-service checkpoints Phase 5 reverts to.
    Doing 'disable automatic checkpoints'
    if (-not $DryRun) { Set-VM -Name $VMName -AutomaticCheckpointsEnabled $false }
}

$stray = Get-VMSnapshot -VMName $VMName -ErrorAction SilentlyContinue |
         Where-Object Name -like 'Automatic Checkpoint*'
if ($stray) {
    # Merged back properly. NEVER delete the .avhdx by hand -- that breaks the
    # disk chain and costs the VM.
    Doing "remove $($stray.Count) automatic checkpoint(s)"
    if (-not $DryRun) { $stray | Remove-VMSnapshot }
}

# --- network ----------------------------------------------------------------

Step "3. Adapter on '$SwitchName'"

$nic = Get-VMNetworkAdapter -VMName $VMName | Select-Object -First 1
if ($nic.SwitchName -eq $SwitchName) {
    Skip "already on '$SwitchName'"
} else {
    Doing "replug from '$($nic.SwitchName)' to '$SwitchName'"
    if (-not $DryRun) { Connect-VMNetworkAdapter -VMName $VMName -SwitchName $SwitchName }
    Warn 'the guest needs its static address set from the inside -- lab_client_setup.ps1 -SetNetwork, or /etc/network/interfaces on the Engine VM'
}

# --- checkpoint -------------------------------------------------------------

Step "4. Checkpoint '$CheckpointName'"

if ($SkipCheckpoint) {
    Skip 'skipped by -SkipCheckpoint'
} elseif (Get-VMSnapshot -VMName $VMName -Name $CheckpointName -ErrorAction SilentlyContinue) {
    Skip "'$CheckpointName' already exists -- delete it first if you want a newer one"
} else {
    Doing "checkpoint '$CheckpointName'"
    if (-not $DryRun) { Checkpoint-VM -Name $VMName -SnapshotName $CheckpointName }
}

Step 'Done.'

@"
  Take a second checkpoint named "pre-service" immediately before T5.4's
  install_service, and revert to it after each attempt. That is the whole
  reason these VMs are worth their setup time.

    Checkpoint-VM -Name $VMName -SnapshotName "pre-service"
    Restore-VMSnapshot -VMName $VMName -Name "pre-service" -Confirm:`$false

  After ANY revert, resync the guest clock before touching anything
  time-based. Lockout windows are HMAC-protected and time-based, so a stale
  clock presents exactly as a bug in client/lockout.py:

    w32tm /resync        (in the guest)
"@ | Write-Host

if ($DryRun) { Write-Host "`nDRY RUN -- nothing was changed.`n" -ForegroundColor Magenta }
