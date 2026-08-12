<#
.SYNOPSIS
    Builds a stripped Windows 11 24H2 install ISO for the Phase 5 client VM.

.DESCRIPTION
    testing.md section 0.1e. DISM against an offline image plus offline registry
    edits -- the same mechanism as tiny11builder, but the list is ours and every
    entry is justifiable against a Phase 5 test.

    THE MODEL IS A KEEP-LIST, NOT A REMOVE-LIST.
    Every provisioned Appx package is removed unless it appears in $KeepAppx or
    $ProtectedAppx. Adding an app back is a deliberate edit; forgetting to strip
    one is not possible. What is kept, and only what is kept:

      - Notepad, Snipping Tool, Windows Terminal        (asked for)
      - VCLibs / UI.Xaml / .NET Native / WindowsAppRuntime frameworks
        (the three above will not launch without them)
      - $ProtectedAppx -- the shell itself. Start menu, File Explorer, OOBE,
        the credential and print dialogs. Not preferences; the machine does not
        boot to a usable desktop without them.

    ALSO REMOVED OUTRIGHT
      - Microsoft Edge, EdgeUpdate, EdgeCore and WebView2. Nothing here is a
        WebView2 host -- the Admin and both client helper windows are Qt/QML.
      - OneDrive, including the per-user setup stub.
      - Defender's UI and every Defender service, plus the policy switch.
        (The binaries stay: they are a protected component and pulling them
        offline breaks servicing. Services at Start=4 is functionally off and
        is reversible with Start=2 if a test ever wants a realistic machine.)
      - Recall and the Copilot components, by feature removal and policy.
      - Windows Update's automatic behaviour and its services.
      - 20+ services that exist for hardware or scenarios a lab VM does not have.

    WHAT IS DELIBERATELY LEFT ALONE, because a Phase 5 test needs it
      - Task Scheduler (Schedule). client/install_service.py registers the
        lockout watchdog with schtasks. This is under test, not incidental.
      - gpsvc, MMC and gpedit.msc. T4.5 reproduces C10 with them.
      - vmic* (Hyper-V integration). Lockout schedules are HMAC-protected,
        time-based and fail closed -- a drifting guest clock would present
        exactly as a bug in client/lockout.py.
      - UxSms / Themes / DWM. The lockout overlay is a full-screen composited
        QML window; without the compositor there is nothing to test.
      - TermService and UmRdpService. Hyper-V Enhanced Session needs them, and
        that is how the repo gets copied into the VM (section 0.1d step 3).
      - WinSxS and the servicing stack. This is the whole difference from
        tiny11 Core, and PySide6 needs a VC++ redistributable to be installable.
      - Winmgmt (WMI), EventLog, mpssvc, Dnscache, Dhcp, LanmanWorkstation.

    Optional features are disabled but their payload is kept unless
    -RemoveFeaturePayload is passed. Payload removal is where "still
    serviceable" genuinely starts to erode, and features are not the size
    driver here -- Appx, Edge and the final recompress are. The switch exists
    if you want the last GB.

    Run with -DryRun first. It prints the KEEP/REMOVE decision for every
    package found in the image and changes nothing.

.PARAMETER SourceIso
    Path to the untouched Win11_24H2_English_x64.iso.

.PARAMETER Scratch
    Working directory. Needs ~25 GB free. Deleted and recreated on each run.

.PARAMETER OutputIso
    Path of the ISO to write.

.PARAMETER Edition
    Edition to keep. Pro is the default, for gpedit.msc (T4.5 / C10).

.PARAMETER AdminUser / AdminPassword
    Local account created by the injected autounattend.xml, which also skips
    the Microsoft-account requirement 24H2 pushes through OOBE.

.PARAMETER OscdimgPath
    Full path to oscdimg.exe, for an ADK installed somewhere other than its
    default location. Without it the script probes the ADK default and PATH.

.PARAMETER KeepWinget
    Keep App Installer (winget). Off by default -- Python is installed from its
    own .exe (section 0.1d step 2), so nothing here needs it.

.PARAMETER RemoveFeaturePayload
    Also delete disabled features' payload from the component store.

.PARAMETER DryRun
    Mount, classify, print, unmount without committing. Changes nothing.

.PARAMETER SkipCompress
    Skip the final /Export-Image recompress. Faster, larger ISO.

.EXAMPLE
    Set-ExecutionPolicy Bypass -Scope Process
    .\scripts\build_client_image.ps1 -SourceIso D:\Win11_24H2_English_x64.iso -DryRun
    .\scripts\build_client_image.ps1 -SourceIso D:\Win11_24H2_English_x64.iso

.NOTES
    Elevated Windows PowerShell 5.1, on the host. 30-60 minutes.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourceIso,
    [string]$Scratch = "$env:SystemDrive\labimage",
    [string]$OutputIso = "$PWD\win11-labclient.iso",
    [string]$Edition = 'Windows 11 Pro',
    [string]$AdminUser = 'lab',
    [string]$AdminPassword = 'lab',
    [string]$OscdimgPath,
    [switch]$KeepWinget,
    [switch]$RemoveFeaturePayload,
    [switch]$DryRun,
    [switch]$SkipCompress
)

$ErrorActionPreference = 'Stop'

# --------------------------------------------------------------------------
# The keep-list. Prefix matches against PackageName; no version numbers.
# --------------------------------------------------------------------------

# Asked for, plus the frameworks they load against.
$KeepAppx = @(
    'Microsoft.WindowsNotepad'              # Notepad
    'Microsoft.ScreenSketch'                # Snipping Tool
    'Microsoft.WindowsTerminal'             # Terminal
    'Microsoft.VCLibs.'                     # framework: all three of the above
    'Microsoft.UI.Xaml.'                    # framework: Terminal, Snipping Tool
    'Microsoft.NET.Native.'                 # framework
    'Microsoft.WindowsAppRuntime.'          # framework: Notepad (WinAppSDK)
)
if ($KeepWinget) { $KeepAppx += 'Microsoft.DesktopAppInstaller' }

# The shell. Not a preference list -- remove these and the image boots to a
# desktop that cannot open a Start menu, a folder, or a credential prompt.
# CloudExperienceHost and the OOBENetwork* pair run Setup itself.
#
# On 24H2 none of these actually appear in /Get-ProvisionedAppxPackages -- they
# live in \Windows\SystemApps and Remove-ProvisionedAppxPackage cannot reach
# them, so the shell is safe by construction and this list never fires. Kept as
# a guard rail: it costs nothing, and what Microsoft chooses to provision has
# changed before. A dry run printing no PROTECTED lines is expected, not a bug.
$ProtectedAppx = @(
    'MicrosoftWindows.Client.CBS'
    'MicrosoftWindows.Client.Core'
    'MicrosoftWindows.Client.FileExp'       # File Explorer, 24H2
    'MicrosoftWindows.Client.Photon'
    'Microsoft.Windows.ShellExperienceHost'
    'Microsoft.Windows.StartMenuExperienceHost'
    'Microsoft.Windows.Search'              # Start menu search host
    'Microsoft.Windows.CloudExperienceHost'
    'Microsoft.Windows.OOBENetworkCaptivePortal'
    'Microsoft.Windows.OOBENetworkConnectionFlow'
    'Microsoft.AAD.BrokerPlugin'
    'Microsoft.AccountsControl'
    'Microsoft.CredDialogHost'
    'Microsoft.LockApp'
    'Microsoft.Win32WebViewHost'
    'Microsoft.Windows.Apprep.ChxApp'
    'Microsoft.Windows.AssignedAccessLockApp'
    'Microsoft.Windows.CapturePicker'
    'Microsoft.Windows.PinningConfirmationDialog'
    'Microsoft.Windows.PrintQueueActionCenter'
    'Windows.PrintDialog'
    'Windows.CBSPreview'
    'Microsoft.UI.Xaml'
    'Microsoft.WindowsAppRuntime'
)

# Capabilities. Removed by prefix; anything not listed is untouched.
$RemoveCapabilities = @(
    'Browser.InternetExplorer'
    'MathRecognizer'
    'Microsoft.Windows.PowerShell.ISE'
    'App.StepsRecorder'
    'App.Support.QuickAssist'
    'Media.WindowsMediaPlayer'
    'Hello.Face'
    'Language.Handwriting'
    'Language.OCR'
    'Language.Speech'
    'Language.TextToSpeech'
    'Print.Fax.Scan'
    'OneCoreUAP.OneSync'
    'Microsoft.Windows.WordPad'
    'Microsoft.Windows.MSPaint'
    'Microsoft.Windows.Paint'
    'XPS.Viewer'
)
# Language.Basic and Print.Management.Console are NOT here on purpose: the
# first is load-bearing, the second is how a printer policy would be inspected.

# Kept even though a 24H2 dry run reports them absent: 'Recall' arrives through
# Windows Update on Copilot+ hardware rather than in RTM media, and IE is now
# the Browser.InternetExplorer *capability* above. Both cost one 'absent' line
# and cover us if the media changes.
#
# MSRDC-Infrastructure is deliberately NOT here. It is Remote Desktop
# infrastructure, and Hyper-V Enhanced Session -- which section 0.1d relies on
# to copy the repo into the VM -- is RDP over VMBus. The saving is a few MB and
# the risk lands on a dependency this script explicitly protects elsewhere.
$DisableFeatures = @(
    'Recall'
    'Internet-Explorer-Optional-amd64'
    'WindowsMediaPlayer'
    'MicrosoftWindowsPowerShellV2'
    'MicrosoftWindowsPowerShellV2Root'
    'Printing-XPSServices-Features'
    'WorkFolders-Client'
    'SmbDirect'
)

# Start=4. Grouped by what they are for, so the list stays reviewable.
$DisableServices = @(
    # Telemetry and error reporting
    'DiagTrack', 'dmwappushservice', 'WerSvc', 'PcaSvc', 'wisvc'
    # Disk/RAM churn with nothing to churn over
    'SysMain', 'WSearch'
    # Windows Update
    'wuauserv', 'UsoSvc', 'WaaSMedicSvc', 'DoSvc'
    # Defender
    'WinDefend', 'WdNisSvc', 'Sense', 'SecurityHealthService', 'wscsvc'
    # Xbox
    'XblAuthManager', 'XblGameSave', 'XboxNetApiSvc', 'XboxGipSvc'
    # Hardware this VM does not have
    'Spooler', 'Fax', 'lfsvc', 'WbioSrvc', 'SensorService', 'SensrSvc'
    'ScDeviceEnum', 'SCardSvr', 'TabletInputService'
    # Consumer surfaces
    'MapsBroker', 'RetailDemo', 'WalletService', 'WpcMonSvc', 'SharedAccess'
)

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

function Write-Step { param([string]$Message) Write-Host "`n==> $Message" -ForegroundColor Cyan }

function Invoke-Dism {
    <#
        dism.exe does not throw on failure; this does.

        [object[]] plus the flatten below so that both call styles work:
        loose tokens (Invoke-Dism /Foo /Bar) and a splatted array
        (Invoke-Dism @args). With [string[]], a lone array argument is
        stringified into one space-joined token and dism rejects it with a
        confusing "option is unknown".
    #>
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Arguments)
    $flat = @($Arguments | ForEach-Object { $_ } | ForEach-Object { [string]$_ })
    & dism.exe @flat | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "dism failed ($LASTEXITCODE): dism $($flat -join ' ')" }
}

function Get-DismField {
    <# Pulls one repeated field out of dism's key : value output. #>
    param([string[]]$Output, [string]$Field)
    $Output |
        Where-Object { $_ -match "^\s*$Field\s*:\s*(.+?)\s*$" } |
        ForEach-Object { ($_ -split ':\s*', 2)[1].Trim() }
}

function Test-Prefix {
    param([string]$Value, [string[]]$Prefixes)
    foreach ($p in $Prefixes) { if ($Value -like "$p*") { return $true } }
    return $false
}

function Invoke-Reg {
    <#
        No stderr redirection. In PowerShell 5.1 redirecting a native command's
        stderr wraps each line in a NativeCommandError, which $ErrorActionPreference
        = 'Stop' then turns into a terminating error -- so `2>$null` did not
        silence reg.exe, it promoted its complaints into fatal ones and made
        -Optional impossible. Exit code is the only signal used here.
    #>
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$Arguments)
    $flat = @($Arguments | ForEach-Object { $_ } | ForEach-Object { [string]$_ })
    # Routed through cmd so 2>&1 merges the streams *before* PowerShell sees
    # them. reg.exe writes "ERROR: Access is denied." to stderr, so capturing
    # stdout alone produced failures with an empty reason.
    $quoted = ($flat | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
    $out = & cmd.exe /c "reg $quoted 2>&1"
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = ($out -join ' ').Trim() }
}

function Import-OfflineHive {
    <#
        Loads a hive and proves it. reg load's exit code was previously
        discarded, so a failed load looked like a puzzling "Access is denied"
        several calls later, when the adds landed on a key that was not there.
    #>
    param([string]$KeyName, [string]$HivePath)
    if (-not (Test-Path $HivePath)) { throw "Hive not found: $HivePath" }
    $r = Invoke-Reg load $KeyName $HivePath
    if ($r.Code -ne 0) { throw "reg load $KeyName failed ($($r.Code)): $($r.Output)" }
    $probe = Invoke-Reg query $KeyName
    if ($probe.Code -ne 0) { throw "$KeyName loaded but is not queryable: $($probe.Output)" }
    Write-Host "  loaded    $KeyName"
}

# Policy writes that the image refuses, collected rather than thrown. Some keys
# in a stock image are TrustedInstaller-owned with Administrators read-only
# (SOFTWARE\Policies\Microsoft\Dsh is the one 24H2 hits), and taking ownership
# offline needs SeTakeOwnershipPrivilege that PowerShell does not hold. One
# refused policy is not worth failing a build over -- but it must never pass
# unnoticed, so every failure is listed again at the end.
$script:RegFailures = @()

function Set-OfflineReg {
    param([string]$Key, [string]$Name, [string]$Type, [string]$Value, [switch]$Optional)
    $r = Invoke-Reg add $Key /v $Name /t $Type /d $Value /f
    if ($r.Code -ne 0) {
        if ($Optional) { return }   # expected-absent, e.g. a service not in this image
        $detail = "$Key\$Name -- $($r.Output)"
        $script:RegFailures += $detail
        Write-Warning "  refused: $detail"
    }
}

function Test-OfflineRegistryAccess {
    <#
        Proves the offline hives load and accept a write, then unloads them and
        leaves nothing behind. Costs seconds.

        It exists because of the ordering lesson: the registry step used to run
        last, so "Access is denied" on the first reg add discarded ~20 minutes
        of completed Appx and capability work. The registry is the cheapest step
        and the likeliest to fail on permissions, so it gets proven first.
    #>
    param([string]$MountDir)
    Write-Step 'Checking the offline registry loads and is writable'
    Import-OfflineHive 'HKLM\zProbe' "$MountDir\Windows\System32\config\SOFTWARE"
    try {
        $r = Invoke-Reg add 'HKLM\zProbe\LabMonitorProbe' /v Probe /t REG_DWORD /d 1 /f
        if ($r.Code -ne 0) {
            throw @"
The offline hive loaded but will not accept a write: $($r.Output)

This is a permissions problem on the mounted image, not a bad key path. Check
that this prompt is elevated and that no other process (an antivirus scanner, a
previous run's leftover 'reg load') holds the mount.
"@
        }
        Invoke-Reg delete 'HKLM\zProbe\LabMonitorProbe' /f | Out-Null
        Write-Host '  loadable and writable'
    }
    finally {
        [GC]::Collect(); [GC]::WaitForPendingFinalizers()
        Invoke-Reg unload 'HKLM\zProbe' | Out-Null
    }
}

function Get-OscdimgPath {
    <#
        Deliberately does not download anything. A build tool fetched at
        runtime is the one thing worth being fussy about.

        -OscdimgPath first, because the ADK does not have to live on C: -- a
        host short of space installs it elsewhere and the default probe misses.
    #>
    if ($OscdimgPath) {
        if (Test-Path $OscdimgPath) { return (Resolve-Path $OscdimgPath).Path }
        throw "-OscdimgPath does not exist: $OscdimgPath"
    }
    foreach ($c in @(
            "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
            "${env:ProgramFiles}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe")) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command oscdimg.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw @'
oscdimg.exe not found. Install the Windows ADK, ticking only "Deployment Tools":
  https://learn.microsoft.com/windows-hardware/get-started/adk-install
'@
}

function New-UnattendXml {
    <#
        Local account, no Microsoft account, no privacy carousel. Nothing here
        relaxes hardware checks -- a Gen 2 VM with vTPM already passes them.
    #>
    param([string]$Path, [string]$User, [string]$Password)
    @"
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64"
               publicKeyToken="31bf3856ad364e35" language="neutral"
               versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>
      <UserAccounts>
        <LocalAccounts>
          <LocalAccount wcm:action="add">
            <Name>$User</Name>
            <Group>Administrators</Group>
            <Password><Value>$Password</Value><PlainText>true</PlainText></Password>
          </LocalAccount>
        </LocalAccounts>
      </UserAccounts>
      <AutoLogon>
        <Enabled>true</Enabled>
        <Username>$User</Username>
        <LogonCount>1</LogonCount>
        <Password><Value>$Password</Value><PlainText>true</PlainText></Password>
      </AutoLogon>
    </component>
  </settings>
</unattend>
"@ | Set-Content -Path $Path -Encoding UTF8
}

# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this from an elevated Windows PowerShell 5.1 prompt.'
}
if (-not (Test-Path $SourceIso)) { throw "Source ISO not found: $SourceIso" }

$oscdimg = if ($DryRun) { $null } else { Get-OscdimgPath }
$work    = Join-Path $Scratch 'media'
$mount   = Join-Path $Scratch 'mount'

# A dry run only reads the image, so it does not pay for the media copy or the
# recompress. Charging it the build's 25 GB would make the cheap safety check
# the expensive one.
$requiredGb  = if ($DryRun) { 3 } else { 25 }
$driveLetter = (Split-Path -Qualifier $Scratch).TrimEnd(':')
$free = (Get-PSDrive $driveLetter).Free / 1GB
if ($free -lt $requiredGb) {
    $roomy = Get-PSDrive -PSProvider FileSystem |
        Where-Object { $_.Free / 1GB -ge $requiredGb } |
        ForEach-Object { '{0}: ({1:N0} GB free)' -f $_.Name, ($_.Free / 1GB) }
    $hint = if ($roomy) { "Try -Scratch <drive>:\labimage -OutputIso <drive>:\win11-labclient.iso on " + ($roomy -join ', ') }
            else        { 'No local drive has room; free some space first.' }
    throw ("Need ~{0} GB free on {1}: ; {2:N1} GB available.`n{3}" -f $requiredGb, $driveLetter, $free, $hint)
}

Write-Step "Preparing scratch at $Scratch"
if (Test-Path $Scratch) { Remove-Item $Scratch -Recurse -Force }
New-Item -ItemType Directory -Path $work, $mount -Force | Out-Null

# --------------------------------------------------------------------------
# 1. Get at the install image
# --------------------------------------------------------------------------

$resolvedIso = (Resolve-Path $SourceIso).Path
Write-Step 'Mounting the source ISO'
# Tolerate an ISO left attached by an earlier failed run -- Mount-DiskImage
# throws on one that is already mounted, which would turn one bad run into a
# manual cleanup step before every retry.
if ((Get-DiskImage -ImagePath $resolvedIso).Attached) {
    Write-Host '  already attached; reusing it'
}
else {
    Mount-DiskImage -ImagePath $resolvedIso | Out-Null
}
$isoAttached = $true
$isoRoot = (Get-DiskImage -ImagePath $resolvedIso | Get-Volume).DriveLetter + ':\'
Write-Host "  source media at $isoRoot"

# Set by the branches below; /ReadOnly lets a dry run mount straight off the
# ISO, which is what makes it cheap.
$mountExtraArgs = @()

if ($DryRun) {
    $wim = Join-Path $isoRoot 'sources\install.wim'
    if (-not (Test-Path $wim)) {
        Dismount-DiskImage -ImagePath $resolvedIso | Out-Null
        throw @'
This media carries install.esd, which cannot be mounted directly. A dry run
needs install.wim (retail media). Re-run without -DryRun on a drive with the
full 25 GB and the script will convert it.
'@
    }
    $mountExtraArgs = @('/ReadOnly')
}
else {
    Write-Step 'Copying media'
    & robocopy.exe $isoRoot $work /E /NFL /NDL /NJH /NJS /NP | Out-Null
    $rc = $LASTEXITCODE
    Dismount-DiskImage -ImagePath $resolvedIso | Out-Null
    $isoAttached = $false
    if ($rc -ge 8) { throw "robocopy failed ($rc)" }

    # ISO copies are read-only and DISM will not commit into them.
    & attrib.exe -r "$work\*.*" /s | Out-Null

    # Retail media carries install.wim; Media Creation Tool output carries
    # install.esd, which cannot be mounted read/write.
    $wim = Join-Path $work 'sources\install.wim'
    $esd = Join-Path $work 'sources\install.esd'
    if (-not (Test-Path $wim)) {
        if (-not (Test-Path $esd)) { throw 'Neither sources\install.wim nor install.esd is present.' }
        Write-Step 'Source is install.esd; converting to install.wim'
        Invoke-Dism /Export-Image /SourceImageFile:$esd /SourceIndex:1 /DestinationImageFile:$wim /Compress:max
        Remove-Item $esd -Force
    }
}

# --------------------------------------------------------------------------
# 2. Pick the edition and mount it
# --------------------------------------------------------------------------

Write-Step "Locating edition '$Edition'"
$info = & dism.exe /Get-WimInfo /WimFile:$wim
$index = $null; $currentIndex = $null
foreach ($line in $info) {
    if ($line -match '^\s*Index\s*:\s*(\d+)') { $currentIndex = [int]$Matches[1] }
    if ($line -match '^\s*Name\s*:\s*(.+?)\s*$' -and $Matches[1] -eq $Edition) { $index = $currentIndex; break }
}
if (-not $index) {
    $info | Where-Object { $_ -match 'Index|Name' } | Write-Host
    throw "Edition '$Edition' not found. Pick one of the names above with -Edition."
}
Write-Host "  '$Edition' is index $index"

Write-Step 'Mounting the install image (slow)'
# Splatted, not passed as one array argument: Invoke-Dism's -Arguments is
# ValueFromRemainingArguments, so a lone array binds as a single space-joined
# string and dism receives one unparseable token.
$wimMountArgs = @('/Mount-Wim', "/WimFile:$wim", "/Index:$index", "/MountDir:$mount") + $mountExtraArgs
try {
    Invoke-Dism @wimMountArgs
}
catch {
    if ($isoAttached) { Dismount-DiskImage -ImagePath $resolvedIso | Out-Null }
    throw
}

try {
    if (-not $DryRun) { Test-OfflineRegistryAccess -MountDir $mount }

    # ----------------------------------------------------------------------
    # 3. Appx: remove everything not on the keep-list
    # ----------------------------------------------------------------------

    Write-Step 'Classifying provisioned Appx packages'
    $provisioned = Get-DismField (& dism.exe /Image:$mount /Get-ProvisionedAppxPackages) 'PackageName'
    $toRemove = @()
    foreach ($pkg in $provisioned | Sort-Object) {
        if (Test-Prefix $pkg $KeepAppx) {
            Write-Host "  KEEP      $pkg" -ForegroundColor Green
        }
        elseif (Test-Prefix $pkg $ProtectedAppx) {
            Write-Host "  PROTECTED $pkg" -ForegroundColor DarkGreen
        }
        else {
            Write-Host "  REMOVE    $pkg" -ForegroundColor Yellow
            $toRemove += $pkg
        }
    }
    Write-Host ("  -- {0} of {1} packages will be removed" -f $toRemove.Count, $provisioned.Count)

    if (-not $DryRun) {
        Write-Step 'Removing Appx packages'
        foreach ($pkg in $toRemove) {
            & dism.exe /Image:$mount /Remove-ProvisionedAppxPackage /PackageName:$pkg | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "  could not remove $pkg (continuing)" }
        }
    }

    # ----------------------------------------------------------------------
    # 4. Capabilities and optional features
    # ----------------------------------------------------------------------

    Write-Step 'Classifying capabilities'
    # /Get-Capabilities lists everything *available*, most of it "Not Present"
    # -- i.e. offered for installation, not installed. Removing those fails
    # noisily and pointlessly: on 24H2 that was ~190 warnings, nearly all
    # per-locale Language.*, drowning any real failure. Only Installed ones are
    # candidates.
    $capState = @{}
    $cname = $null
    foreach ($line in (& dism.exe /Image:$mount /Get-Capabilities)) {
        if     ($line -match '^\s*Capability Identity\s*:\s*(.+?)\s*$') { $cname = $Matches[1] }
        elseif ($line -match '^\s*State\s*:\s*(.+?)\s*$' -and $cname)   { $capState[$cname] = $Matches[1]; $cname = $null }
    }
    $caps = @($capState.Keys | Where-Object { $capState[$_] -match 'Installed' })
    Write-Host ("  {0} of {1} capabilities are installed; the rest are Not Present" -f $caps.Count, $capState.Count)
    $capsToRemove = @($caps | Where-Object { Test-Prefix $_ $RemoveCapabilities })
    # Collapsed by family: Language.* alone is ~190 per-locale entries, and an
    # unreadable dry run is a dry run nobody checks.
    foreach ($g in ($capsToRemove | Group-Object { ($_ -split '~')[0] } | Sort-Object Name)) {
        if ($g.Count -gt 1) { Write-Host ("  REMOVE    {0}  ({1} locales/entries)" -f $g.Name, $g.Count) -ForegroundColor Yellow }
        else                { Write-Host "  REMOVE    $($g.Group[0])" -ForegroundColor Yellow }
    }
    Write-Host ("  -- {0} of {1} capabilities will be removed" -f $capsToRemove.Count, $caps.Count)

    # Features are classified in both modes: Recall lives here, not in the Appx
    # list, so a dry run that skipped this could not show whether it went.
    Write-Step 'Classifying optional features'
    $featureState = @{}
    $fname = $null
    foreach ($line in (& dism.exe /Image:$mount /Get-Features)) {
        if     ($line -match '^\s*Feature Name\s*:\s*(.+?)\s*$') { $fname = $Matches[1] }
        elseif ($line -match '^\s*State\s*:\s*(.+?)\s*$' -and $fname) { $featureState[$fname] = $Matches[1]; $fname = $null }
    }
    foreach ($feature in $DisableFeatures) {
        if (-not $featureState.ContainsKey($feature)) {
            Write-Host "  absent    $feature" -ForegroundColor DarkGray
        }
        elseif ($featureState[$feature] -match 'Disabled') {
            Write-Host "  already   $feature (Disabled)" -ForegroundColor DarkGray
        }
        else {
            Write-Host ("  DISABLE   {0} ({1})" -f $feature, $featureState[$feature]) -ForegroundColor Yellow
        }
    }

    if (-not $DryRun) {
        Write-Step 'Removing capabilities'
        foreach ($cap in $capsToRemove) {
            & dism.exe /Image:$mount /Remove-Capability /CapabilityName:$cap | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "  could not remove $cap (continuing)" }
        }

        Write-Step 'Disabling optional features'
        foreach ($feature in $DisableFeatures) {
            $dismArgs = @("/Image:$mount", '/Disable-Feature', "/FeatureName:$feature")
            if ($RemoveFeaturePayload) { $dismArgs += '/Remove' }
            & dism.exe @dismArgs | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "  $feature not present or not removable (continuing)" }
            else { Write-Host "  disabled  $feature" }
        }
    }

    # ----------------------------------------------------------------------
    # 5. Edge and OneDrive, which are not Appx
    # ----------------------------------------------------------------------

    if (-not $DryRun) {
        Write-Step 'Removing Edge, WebView2 and OneDrive'
        $paths = @(
            "$mount\Program Files (x86)\Microsoft\Edge"
            "$mount\Program Files (x86)\Microsoft\EdgeUpdate"
            "$mount\Program Files (x86)\Microsoft\EdgeCore"
            "$mount\Program Files (x86)\Microsoft\EdgeWebView"
            "$mount\Program Files (x86)\Microsoft\Temp"
            "$mount\Windows\System32\OneDriveSetup.exe"
            "$mount\Windows\SysWOW64\OneDriveSetup.exe"
        )
        foreach ($p in $paths) {
            if (Test-Path $p) {
                Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue
                Write-Host "  removed   $(Split-Path $p -Leaf)"
            }
        }
    }

    # ----------------------------------------------------------------------
    # 6. Offline registry
    # ----------------------------------------------------------------------

    if (-not $DryRun) {
        Write-Step 'Applying offline registry policy'
        Import-OfflineHive 'HKLM\zSOFTWARE' "$mount\Windows\System32\config\SOFTWARE"
        Import-OfflineHive 'HKLM\zSYSTEM'   "$mount\Windows\System32\config\SYSTEM"
        Import-OfflineHive 'HKLM\zNTUSER'   "$mount\Users\Default\NTUSER.DAT"
        try {
            # Copilot and Recall. Recall screenshots the desktop on a timer,
            # which is an obviously bad interaction with a lockout overlay.
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\WindowsCopilot' 'TurnOffWindowsCopilot' REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\WindowsAI'      'DisableAIDataAnalysis' REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\WindowsAI'      'AllowRecallEnablement' REG_DWORD 0

            # Consumer content and suggestion surfaces.
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\CloudContent' 'DisableWindowsConsumerFeatures'     REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\CloudContent' 'DisableConsumerAccountStateContent' REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\CloudContent' 'DisableCloudOptimizedContent'       REG_DWORD 1
            # Dsh (Widgets) is TrustedInstaller-owned in a stock 24H2 image and
            # refuses this write. Attempted anyway because it is free, but it is
            # belt-and-braces: the Widgets host package
            # (MicrosoftWindows.Client.WebExperience) is removed outright, and
            # TaskbarDa below takes it off the taskbar for the default user.
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Dsh'                    'AllowNewsAndInterests' REG_DWORD 0
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\Windows Search' 'DisableWebSearch'      REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\Windows Search' 'AllowCortana'          REG_DWORD 0

            # Telemetry and Delivery Optimization generate background traffic
            # that muddies what the agent's own connection is doing.
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\DataCollection'       'AllowTelemetry' REG_DWORD 0
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization' 'DODownloadMode' REG_DWORD 0

            # Windows Update and Store.
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' 'NoAutoUpdate'         REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\WindowsStore'             'RemoveWindowsStore'   REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\WindowsStore'             'AutoDownload'         REG_DWORD 2

            # Defender: off by policy as well as by service.
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows Defender' 'DisableAntiSpyware'   REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows Defender' 'DisableAntiVirus'     REG_DWORD 1
            Set-OfflineReg 'HKLM\zSOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection' 'DisableRealtimeMonitoring' REG_DWORD 1

            # Edge's installer stubs, so nothing reinstalls it.
            Set-OfflineReg 'HKLM\zSOFTWARE\Microsoft\EdgeUpdate' 'DoNotUpdateToEdgeWithChromium' REG_DWORD 1
            Invoke-Reg delete 'HKLM\zSOFTWARE\Microsoft\Windows\CurrentVersion\Run' /v OneDriveSetup /f | Out-Null

            Write-Host '  disabling services'
            foreach ($svc in $DisableServices) {
                Set-OfflineReg "HKLM\zSYSTEM\ControlSet001\Services\$svc" 'Start' REG_DWORD 4 -Optional
            }

            # Quality of life on a machine that exists to be debugged.
            $adv = 'HKLM\zNTUSER\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
            Set-OfflineReg $adv 'HideFileExt'         REG_DWORD 0
            Set-OfflineReg $adv 'LaunchTo'            REG_DWORD 1   # This PC, not Home
            Set-OfflineReg $adv 'ShowTaskViewButton'  REG_DWORD 0
            Set-OfflineReg $adv 'TaskbarDa'           REG_DWORD 0   # widgets
            Set-OfflineReg $adv 'TaskbarMn'           REG_DWORD 0   # chat
        }
        finally {
            # Hives must be unloaded before the image will unmount, and reg
            # keeps handles alive until the GC runs.
            [GC]::Collect(); [GC]::WaitForPendingFinalizers()
            foreach ($h in 'HKLM\zNTUSER', 'HKLM\zSYSTEM', 'HKLM\zSOFTWARE') {
                $u = Invoke-Reg unload $h
                if ($u.Code -ne 0) { Write-Warning "  could not unload $h : $($u.Output)" }
            }
        }

        if ($script:RegFailures.Count -gt 0) {
            Write-Host ''
            Write-Host ("  {0} policy write(s) were refused by the image:" -f $script:RegFailures.Count) -ForegroundColor Yellow
            $script:RegFailures | ForEach-Object { Write-Host "    - $_" -ForegroundColor Yellow }
            Write-Host '  The build continues. Check each one is covered another way before' -ForegroundColor Yellow
            Write-Host '  relying on it -- see testing.md section 0.1e.' -ForegroundColor Yellow
        }
        else {
            Write-Host '  all policy writes applied'
        }
    }
}
catch {
    Write-Warning 'Failed inside the mounted image; discarding so nothing is left mounted.'
    & dism.exe /Unmount-Image /MountDir:$mount /Discard | Out-Null
    if ($isoAttached) { Dismount-DiskImage -ImagePath $resolvedIso | Out-Null }
    throw
}

if ($DryRun) {
    Write-Step 'Dry run: discarding the mounted image, nothing was changed'
    Invoke-Dism /Unmount-Image /MountDir:$mount /Discard
    if ($isoAttached) { Dismount-DiskImage -ImagePath $resolvedIso | Out-Null }
    Write-Host "`nDry run complete. Re-run without -DryRun to build." -ForegroundColor Green
    return
}

Write-Step 'Committing and unmounting'
Invoke-Dism /Unmount-Image /MountDir:$mount /Commit

# --------------------------------------------------------------------------
# 7. Recompress and repackage
# --------------------------------------------------------------------------

if (-not $SkipCompress) {
    Write-Step 'Recompressing the image (this is the slow part)'
    $tmp = Join-Path $work 'sources\install2.wim'
    Invoke-Dism /Export-Image /SourceImageFile:$wim /SourceIndex:$index /DestinationImageFile:$tmp /Compress:max
    Remove-Item $wim -Force
    Rename-Item $tmp 'install.wim'
}

Write-Step 'Injecting autounattend.xml'
New-UnattendXml -Path (Join-Path $work 'autounattend.xml') -User $AdminUser -Password $AdminPassword

Write-Step "Writing $OutputIso"
$etfs   = Join-Path $work 'boot\etfsboot.com'
$efisys = Join-Path $work 'efi\microsoft\boot\efisys_noprompt.bin'
if (-not (Test-Path $efisys)) { $efisys = Join-Path $work 'efi\microsoft\boot\efisys.bin' }

& $oscdimg -m -o -u2 -udfver102 -bootdata:"2#p0,e,b$etfs#pEF,e,b$efisys" $work $OutputIso | Out-Host
if ($LASTEXITCODE -ne 0) { throw "oscdimg failed ($LASTEXITCODE)" }

Write-Host ("`nDone. {0} ({1:N2} GB)" -f $OutputIso, ((Get-Item $OutputIso).Length / 1GB)) -ForegroundColor Green
Write-Host @"

Next: testing.md section 0.1e, "Gate the image before trusting a single Phase 5
result". Run those checks before recording anything in the results table, and
keep a stock-Win11 checkpoint as the control.
"@
