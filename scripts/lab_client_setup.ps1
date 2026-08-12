<#
.SYNOPSIS
    Provisions the Phase 5 client VM from the inside: Python sanity checks, the
    venv, the packages, the static address, and the optional trim.

.DESCRIPTION
    Run this INSIDE LabClient, in an elevated PowerShell, after Windows is
    installed and the repository has been copied in. testing.md sections 0.1d
    and 0.5.

    It does nothing on the host. The host half is setup_lab_vms.ps1 (before) and
    lab_host_finalize.ps1 (after).

    WHY THE PYTHON CHECKS COME FIRST AND REFUSE RATHER THAN WARN.
    Two Python mistakes cost an evening on 2026-08-12, and both fail late and
    misleadingly rather than at install time:

      - The MICROSOFT STORE build. It is per-user and sandboxed, so a Windows
        service running as SYSTEM cannot reach it -- and install_service.py
        registers exactly that. Until Phase 8 bundles an interpreter, the
        service falls back to whatever python.exe it was handed. The symptom
        arrives at T5.4 looking nothing like its cause. Its path prefix is also
        ~100 characters before site-packages even starts, which is half of why
        the next item bites.
      - LONG PATH SUPPORT OFF. PySide6's tree is deep enough that pip dies with
        "No such file or directory" on a path nobody can read. The python.org
        installer offers "Disable path length limit" on its final screen; this
        script checks the registry value it sets.

    WHY A VENV, when the VM runs only the client and could use system Python.
    It makes sys.path unambiguous -- pip cannot install into a different
    interpreter than the one running -- which is the failure mode that pushed us
    to the Store build in the first place. The base interpreter still has to be
    all-users, because a venv does not escape its base: SYSTEM still cannot
    reach a sandboxed per-user Python underneath one.

    IDEMPOTENT. An existing venv is reused, an existing address is left alone,
    already-disabled services are skipped. Safe to re-run.

.PARAMETER RepoPath
    Where the repository was copied to. Short paths on purpose.

.PARAMETER PythonExe
    The all-users base interpreter to build the venv from.

.PARAMETER StaticIp
    Address on the LabMonitor switch. Skipped unless -SetNetwork is passed,
    because applying it cuts this VM off from the internet.

.PARAMETER SetNetwork
    Apply the static address. Do this LAST -- after pip has everything, since
    it removes the VM's route to the internet.

.PARAMETER Trim
    Disable services and remove Appx packages that cost RAM and that no Phase 5
    test touches. Off by default: it is a convenience, not a requirement.

.PARAMETER DryRun
    Print every action without taking it.

.EXAMPLE
    .\scripts\lab_client_setup.ps1 -DryRun
    .\scripts\lab_client_setup.ps1 -Trim
    .\scripts\lab_client_setup.ps1 -SetNetwork      # once pip is done

.NOTES
    Requires an ELEVATED PowerShell inside the guest.
#>

[CmdletBinding()]
param(
    [string] $RepoPath   = 'C:\SystemMonitoring',
    [string] $PythonExe  = 'C:\Python312\python.exe',
    [string] $StaticIp   = '192.168.100.3',
    [int]    $Prefix     = 24,
    [string] $HostIp     = '192.168.100.1',
    [switch] $SetNetwork,
    [switch] $Trim,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

function Step  { param($m) Write-Host "`n$m" -ForegroundColor Cyan }
function Ok    { param($m) Write-Host "  [ok]   $m" -ForegroundColor Green }
function Skip  { param($m) Write-Host "  [have] $m" -ForegroundColor DarkGray }
function Warn  { param($m) Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Doing { param($m) if ($DryRun) { Write-Host "  [dry]  $m" -ForegroundColor Magenta } else { Write-Host "  [do]   $m" } }

# --- preconditions ----------------------------------------------------------

Step 'Checking preconditions'

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Not elevated. Right-click PowerShell -> Run as administrator, then re-run.'
}
Ok 'running elevated'

if (-not (Test-Path (Join-Path $RepoPath 'pyproject.toml'))) {
    throw "No pyproject.toml under $RepoPath. Copy the repository in first -- and copy it, do not git clone: certs/ is gitignored (testing.md 0.4)."
}
Ok "repository at $RepoPath"

if (-not (Test-Path (Join-Path $RepoPath 'certs\engine-cert.pem'))) {
    throw "certs\engine-cert.pem is missing. This machine was cloned rather than copied. TLS is presence-based, so it would run plaintext while the Engine runs TLS, and the Engine's refusal does not name the cause (testing.md 0.4)."
}
Ok 'certs/ present'

# Files copied off the LabRepo ISO keep the read-only attribute, and
# `pip install -e .` fails on them in a way that does not mention read-only.
$ro = Get-ChildItem $RepoPath -Recurse -File -ErrorAction SilentlyContinue | Where-Object IsReadOnly
if ($ro) {
    Doing "clear read-only on $($ro.Count) files (copied from the ISO)"
    if (-not $DryRun) { $ro | ForEach-Object { $_.IsReadOnly = $false } }
} else {
    Skip 'no read-only files'
}

# --- python ------------------------------------------------------------------

Step '1. Python'

if (-not (Test-Path $PythonExe)) {
    throw @"
$PythonExe not found.

Install Python 3.10+ from python.org -- NOT the Microsoft Store build. Choose
Customize installation, then:
  [x] Add python.exe to PATH
  [x] Install Python for all users     <- SYSTEM needs this for T5.4
  location: C:\Python312
  final screen: click "Disable path length limit"
"@
}

$ver = & $PythonExe -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]'3.10') {
    throw "Python $ver is below the project floor of 3.10 (pyproject.toml requires-python)."
}
Ok "base interpreter $PythonExe is $ver"

if ($PythonExe -like '*WindowsApps*' -or $PythonExe -like '*PythonSoftwareFoundation.Python*') {
    throw 'That is the Microsoft Store build. It is per-user and sandboxed, so the T5.4 service running as SYSTEM cannot reach it. Install from python.org, for all users.'
}

$lp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
if ($lp -ne 1) {
    Doing 'enable long paths (PySide6 will not install without it)'
    if (-not $DryRun) {
        Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Type DWord -Value 1
    }
    Warn 'long paths were off -- REBOOT before the pip step, or it will fail again'
} else {
    Ok 'long path support enabled'
}

# A leftover Store stub on PATH shadows a correct install and is the usual cause
# of "packages went to the wrong place".
$stub = (Get-Command python.exe -All -ErrorAction SilentlyContinue |
         Where-Object Source -like '*WindowsApps*')
if ($stub) {
    Warn "a Store python stub is still on PATH: $($stub[0].Source)"
    Warn 'remove that entry from PATH -- this script uses full paths, but you will be bitten interactively'
}

# --- venv and packages -------------------------------------------------------

Step '2. Virtual environment and packages'

$venv    = Join-Path $RepoPath '.venv'
$venvPy  = Join-Path $venv 'Scripts\python.exe'

if (Test-Path $venvPy) {
    Skip "venv exists at $venv"
} else {
    Doing "create venv at $venv"
    if (-not $DryRun) { & $PythonExe -m venv $venv }
}

# `python -m pip` rather than pip.exe, always: it installs into the interpreter
# that is running, by construction, so pip and python cannot disagree.
Doing 'pip install -r requirements.txt -r requirements-client.txt'
if (-not $DryRun) {
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install -r (Join-Path $RepoPath 'requirements.txt') `
                             -r (Join-Path $RepoPath 'requirements-client.txt')
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed. If it mentions long paths, reboot and re-run.' }
}

Doing 'pip install -e .'
if (-not $DryRun) {
    Push-Location $RepoPath
    try { & $venvPy -m pip install -e . } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'editable install failed -- from common.protocol import ... will not resolve without it' }
}

# --- defender ----------------------------------------------------------------

Step '3. Defender exclusions'

# Defender stays ON: the overlay's Task Manager policy and Phase 8's
# PyInstaller exes are textbook false positives, and a machine with Defender
# disabled is not the machine the agent ships to. Exclusions are the cheap half.
foreach ($p in @($RepoPath, (Join-Path $env:ProgramData 'SystemMonitoring'))) {
    Doing "exclusion: $p"
    if (-not $DryRun) { Add-MpPreference -ExclusionPath $p -ErrorAction SilentlyContinue }
}

# --- optional trim -----------------------------------------------------------

if ($Trim) {
    Step '4. Trim (optional)'

    # Everything here is absent from every Phase 5 test. What is deliberately
    # NOT here, because a test depends on it: Schedule (the watchdog task),
    # gpsvc/MMC (T4.5 and C10), vmic* (guest clock, and lockout windows are
    # time-based and HMAC-protected), UxSms/Themes/DWM (the overlay is a
    # composited QML window), TermService (Enhanced Session), Winmgmt, EventLog.
    $services = 'WSearch','SysMain','DoSvc','wuauserv','UsoSvc','DiagTrack','dmwappushservice'
    foreach ($s in $services) {
        $svc = Get-Service $s -ErrorAction SilentlyContinue
        if (-not $svc) { continue }
        if ($svc.StartType -eq 'Disabled') { Skip "service $s already disabled"; continue }
        Doing "disable service $s"
        if (-not $DryRun) {
            Stop-Service $s -Force -ErrorAction SilentlyContinue
            Set-Service  $s -StartupType Disabled -ErrorAction SilentlyContinue
        }
    }

    $appx = 'MicrosoftWindows.Client.WebExperience','Microsoft.Windows.Copilot',
            'Microsoft.XboxGamingOverlay','Microsoft.XboxGameOverlay','Microsoft.GamingApp',
            'Microsoft.Todos','Microsoft.PowerAutomateDesktop','Microsoft.549981C3F5F10'
    foreach ($a in $appx) {
        $pkg = Get-AppxPackage $a -AllUsers -ErrorAction SilentlyContinue
        if (-not $pkg) { Skip "appx $a absent"; continue }
        Doing "remove appx $a"
        if (-not $DryRun) { $pkg | Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue }
    }

    Doing 'visual effects -> best performance'
    if (-not $DryRun) {
        $vfx = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects'
        if (-not (Test-Path $vfx)) { New-Item $vfx -Force | Out-Null }
        Set-ItemProperty $vfx -Name VisualFXSetting -Value 2
    }
}

# --- self-check --------------------------------------------------------------

Step '5. python -m client --check'

if (-not $DryRun) {
    Push-Location $RepoPath
    try { & $venvPy -m client --check } finally { Pop-Location }
    Write-Host ''
    Write-Host '  Expect: an id resolved, THREE MISSING bundles, and "agent running False".' -ForegroundColor DarkGray
    Write-Host '  The missing bundles are correct here -- packaging is Phase 8.' -ForegroundColor DarkGray
} else {
    Doing "$venvPy -m client --check"
}

# --- network, last -----------------------------------------------------------

Step '6. Static address on the LabMonitor switch'

if (-not $SetNetwork) {
    Warn 'skipped -- pass -SetNetwork when provisioning is finished.'
    Warn 'It removes this VM''s internet, so do everything that needs downloading first.'
} else {
    $ifAlias = (Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object -First 1).Name
    $already = Get-NetIPAddress -InterfaceAlias $ifAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
               Where-Object IPAddress -eq $StaticIp
    if ($already) {
        Skip "$ifAlias already has $StaticIp"
    } else {
        Doing "$ifAlias -> $StaticIp/$Prefix, no gateway"
        if (-not $DryRun) {
            Set-NetIPInterface -InterfaceAlias $ifAlias -Dhcp Disabled
            Remove-NetIPAddress -InterfaceAlias $ifAlias -Confirm:$false -ErrorAction SilentlyContinue
            New-NetIPAddress -InterfaceAlias $ifAlias -IPAddress $StaticIp -PrefixLength $Prefix | Out-Null
        }
    }

    # No -DefaultGateway anywhere above, deliberately: with no default route the
    # guest can reach the host and the Engine VM and nothing else, which is what
    # keeps the stubbed authentication (issues.md C1) off every real network.
    if (-not $DryRun) {
        Write-Host ''
        if (Test-Connection $HostIp -Count 2 -Quiet -ErrorAction SilentlyContinue) {
            Ok "host $HostIp replies"
        } else {
            Warn "no reply from $HostIp -- usually the HOST firewall, not this VM."
            Warn 'On the host: setup_lab_vms.ps1 sets that adapter Private and adds an ICMP rule.'
            Warn 'Nothing real depends on ICMP; the gate is TCP 5000 to the Engine VM.'
        }
    }
}

Step 'Done. What is left:'

@"
  1. Shut this VM down.
  2. On the HOST: .\scripts\lab_host_finalize.ps1 -VMName LabClient
     (Dynamic Memory, automatic checkpoints off, the LabMonitor replug if it
     has not happened, and the "baseline" checkpoint.)
  3. Build the Engine VM -- testing.md 0.1f, then scripts/lab_engine_setup.sh.
  4. Gate T0.1 from here, once the Engine is serving:
       Test-NetConnection 192.168.100.2 -Port 5000
     TcpTestSucceeded : True. Part 1 does not start until it passes.
"@ | Write-Host

if ($DryRun) { Write-Host "`nDRY RUN -- nothing was changed.`n" -ForegroundColor Magenta }
