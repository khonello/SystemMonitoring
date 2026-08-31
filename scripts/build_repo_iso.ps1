<#
.SYNOPSIS
    Cut LabRepo.iso from the working copy, and swap it into a VM's DVD drive.

.DESCRIPTION
    The repository reaches both guests on a disc, because the lab switch has no
    route out and the guests have no shares, no ssh and no USB pass-through
    (LAB-SETUP.md step 4). That makes the disc a build artefact -- and a build
    artefact that goes stale in silence, since the guest reports "no such file"
    for a script sitting in your editor on the host.

    WHY THIS IS A SCRIPT AND NOT A PARAGRAPH. The sequence is five commands, and
    on 2026-08-13 it was performed by hand four times in one evening and went
    wrong twice: once because the ISO was overwritten while a running VM held it
    (the copy fails outright), and once because Set-VMDvdDrive silently left the
    drive EMPTY -- Get-VMDvdDrive reported a path in the same breath as
    DvdMediaType: None, so the guest was handed the previous disc and the
    "fixed" script it was supposed to be testing was never on it.

    So this does the whole thing and CHECKS ITS OWN WORK: it stages, refuses to
    build without certs/, cuts the image, mounts the finished ISO on the host to
    confirm the scripts are physically on it, ejects the disc from every VM
    holding it, waits for the file to actually come free, copies, and puts the
    disc back in every drive it took it out of -- verifying the media took, and
    retrying, rather than leaving a stale disc or an empty drive behind.

    THE OPERATOR SHOULD NOT BE TRACKING ANY OF THIS. Earlier versions ejected
    only from the VMs named in -AttachTo, which quietly assumed you remembered
    which machines had the disc, and copied the instant it had ejected, which
    raced Hyper-V's asynchronous release. Both bit on 2026-08-15: a run naming
    LabEngine alone failed at the copy because LabClient still held the image,
    and the eject that had already happened left LabEngine with an empty drive.
    Note that a running VM holds the host file whether or not the guest has
    mounted it -- a Windows guest never mounts anything and pins it just the
    same -- so "the guest says it is not mounted" proves nothing either way.

    WHAT IT CANNOT DO. It cannot unmount the disc inside a running guest. Linux
    holds the medium while it is mounted, so `umount /mnt` in the guest comes
    first; the script detects the resulting lock and says so rather than
    producing a confusing IO error.

.PARAMETER RepoPath
    The working copy to image. Defaults to this script's parent directory.

.PARAMETER IsoPath
    Where to write the image. Defaults to LabRepo.iso beside an existing
    LabMonitor folder, else the fixed drive with the most free space -- no
    drive letter is hardcoded anywhere, because the lab is rebuilt on a
    presentation machine with a different disk layout.

.PARAMETER AttachTo
    Extra VM names to swap the finished disc into.

    Rarely needed. Any VM already holding this image is ejected before the copy
    and re-attached after it, whether or not it is named here -- so the usual
    call is no arguments at all. Name a VM only to put the disc into a machine
    that does not have it yet.

.PARAMETER DryRun
    Print every action without taking it.

.EXAMPLE
    .\scripts\build_repo_iso.ps1                     # the usual call: cut it,
                                                     # swap it into whichever
                                                     # VMs already hold it
    .\scripts\build_repo_iso.ps1 -AttachTo LabClient # ... and into one that
                                                     # does not yet

.NOTES
    Run ELEVATED whenever a VM has the disc: Hyper-V refuses to enumerate
    machines otherwise, and the script degrades to a build-and-copy that will
    fail against a locked file. Unelevated is fine when both VMs are off.

    oscdimg from the Windows ADK (Deployment Tools feature) is needed always.

    In the guest afterwards:  mount -o ro /dev/sr0 /mnt
    In the guest beforehand:  umount /mnt
#>

[CmdletBinding()]
param(
    [string]   $RepoPath = (Split-Path -Parent $PSScriptRoot),
    [string]   $IsoPath,
    [string[]] $AttachTo = @(),
    [switch]   $DryRun
)

$ErrorActionPreference = 'Stop'

function Step  { param($m) Write-Host "`n$m" -ForegroundColor Cyan }
function Ok    { param($m) Write-Host "  [ok]   $m" -ForegroundColor Green }
function Doing { param($m) if ($DryRun) { Write-Host "  [dry]  $m" -ForegroundColor Magenta }
                 else     { Write-Host "  [do]   $m" } }
function Warn  { param($m) Write-Host "  [warn] $m" -ForegroundColor Yellow }

function Get-IsoHolders {
    <#
        Every VM with this image in a DVD drive, whether or not it was named on
        the command line.

        The eject sweep used to cover only -AttachTo, which quietly assumed the
        operator remembered which machines had the disc. They do not, and they
        should not have to: on 2026-08-15 a run naming LabEngine alone failed at
        the copy because LabClient was still running with the same image
        attached, and the error said "something still holds it" without saying
        what.

        A running VM holds the host file whether or not the guest has mounted
        it -- a Windows guest never mounts anything and pins it just the same --
        so "the Engine says it is not mounted" is no evidence either way.
    #>
    param([string] $Path)

    try {
        $all = Get-VM -ErrorAction Stop
    } catch {
        # Hyper-V needs elevation. A build-only run does not, and must not start
        # requiring it just because this sweep was added.
        #
        # $null, not @(): "swept and found nothing" and "could not sweep" lead to
        # opposite advice, and reporting the second as the first is how an error
        # message sends someone looking in the wrong place.
        Warn 'cannot enumerate VMs (Hyper-V needs an elevated session) -- skipping the eject sweep'
        return $null
    }

    $holders = @()
    foreach ($vm in $all) {
        foreach ($d in (Get-VMDvdDrive -VMName $vm.Name -ErrorAction SilentlyContinue)) {
            if ($d.Path -eq $Path) { $holders += $vm.Name; break }
        }
    }
    return $holders
}

function Wait-Unlocked {
    <#
        Wait until the file can actually be opened for writing.

        Hyper-V releases a DVD handle asynchronously, so ejecting and copying in
        the same breath is a race -- the script already allows eight seconds for
        the same asynchrony at the attach end, and allowed none here.
    #>
    param([string] $Path, [int] $TimeoutSeconds = 20)

    if (-not (Test-Path $Path)) { return $true }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ($true) {
        try {
            $fs = [IO.File]::Open($Path, 'Open', 'ReadWrite', 'None')
            $fs.Close()
            return $true
        } catch {
            if ((Get-Date) -ge $deadline) { return $false }
            Start-Sleep -Milliseconds 500
        }
    }
}

# --- where things are --------------------------------------------------------

Step '1. Inputs'

if (-not (Test-Path (Join-Path $RepoPath 'pyproject.toml'))) {
    throw "No pyproject.toml under '$RepoPath'. Point -RepoPath at the working copy."
}
Ok "repository $RepoPath"

$oscdimg = "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
if (-not (Test-Path $oscdimg)) {
    throw "oscdimg.exe not found. Install the Windows ADK with the 'Deployment Tools' feature. Looked in: $oscdimg"
}
Ok 'oscdimg present'

# certs/ is gitignored and therefore travels only by copying. A disc without it
# leaves that guest on plaintext while the others use TLS, and the Engine's
# refusal of the client never names the cause (testing.md 0.4).
$certDir = Join-Path $RepoPath 'certs'
foreach ($f in 'engine-cert.pem', 'engine-key.pem') {
    if (-not (Test-Path (Join-Path $certDir $f))) {
        throw "certs/$f is missing. Run 'python -m scripts.generate_cert' once on the host, or this disc puts a guest on plaintext."
    }
}
Ok 'certs/ complete (cert and key)'

if (-not $IsoPath) {
    $drives = Get-Volume |
              Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' -and $_.FileSystemType -eq 'NTFS' }
    $lab = $drives | Where-Object { Test-Path "$($_.DriveLetter):\LabMonitor" } | Select-Object -First 1
    if (-not $lab) { $lab = $drives | Sort-Object SizeRemaining -Descending | Select-Object -First 1 }
    if (-not $lab) { throw 'No fixed NTFS volume found. Pass -IsoPath explicitly.' }
    $IsoPath = "$($lab.DriveLetter):\LabRepo.iso"
}
Ok "image $IsoPath"

# --- stage -------------------------------------------------------------------

Step '2. Stage'

$stage = Join-Path $env:TEMP 'labrepo'
Doing "purge and refill $stage"
if (-not $DryRun) {
    # Purge rather than merge: robocopy /E leaves deleted files behind, and a
    # disc carrying a file the repository no longer has is its own confusion.
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    # .venv is host-built Windows binaries; __pycache__ is bytecode from the
    # host's interpreter; .pytest_cache is scratch. All three are wrong on a guest.
    #
    # THE FILE EXCLUSIONS ARE NOT COSMETIC. monitoring.db is the DEV BOX's
    # database. Gitignored, so a clone never sees it -- but this disc is
    # deliberately a copy of the working directory, which is the very mechanism
    # that carries certs/ to the guests, and it carries everything else ignored
    # along with it. On 2026-08-13 that put a phantom client, 'lab1-pc-01' at
    # 127.0.0.1 from testing on this laptop, into the lab Engine's roster, where
    # it showed up in the Admin's sidebar as a machine that does not exist.
    robocopy $RepoPath $stage /E `
             /XD .venv __pycache__ .pytest_cache `
             /XF monitoring.db *.db *.db-journal .coverage `
             /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }
    Ok "$((Get-ChildItem $stage -Recurse -File).Count) files staged"
}

# --- build -------------------------------------------------------------------

Step '3. Build'

# Build to TEMP first, always. The destination may be held by a running VM, and
# oscdimg failing halfway would leave a truncated image where a working one was.
#   -m   ignore the default image size limit
#   -u2  write UDF; ISO 9660 alone truncates and upper-cases long names
#   -l   volume label, how the disc is identified inside the guest
# No -h, so hidden files are skipped and .git never reaches the disc -- which
# makes the copy-don't-clone rule structural rather than a thing to remember.
$tempIso = Join-Path $env:TEMP 'LabRepo.iso'
Doing "oscdimg -m -u2 -lLABREPO -> $tempIso"
if (-not $DryRun) {
    if (Test-Path $tempIso) { Remove-Item $tempIso -Force }
    # Start-Process, not the call operator: oscdimg writes its progress meter to
    # STDERR, and Windows PowerShell 5.1 turns any native stderr line into an
    # ErrorRecord -- which under $ErrorActionPreference='Stop' aborts the build
    # on a "0% complete" that is not an error at all.
    $log = Join-Path $env:TEMP 'oscdimg.log'
    $p = Start-Process -FilePath $oscdimg `
                       -ArgumentList '-m', '-u2', '-lLABREPO', "`"$stage`"", "`"$tempIso`"" `
                       -NoNewWindow -Wait -PassThru `
                       -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    if ($p.ExitCode -ne 0) {
        Warn "oscdimg said: $(Get-Content "$log.err" -Raw -ErrorAction SilentlyContinue)"
        throw "oscdimg failed with exit code $($p.ExitCode)"
    }
    Ok "built ($([math]::Round((Get-Item $tempIso).Length / 1MB, 2)) MB)"
}

# --- prove it, BEFORE anything is attached -----------------------------------

Step '4. Verify the image, not the intention'

# ORDER MATTERS, AND IT COST AN HOUR TO LEARN. This check used to run last, on
# the placed image, after both VMs had it attached -- and Mount-DiskImage plus
# Dismount-DiskImage on the host YANKS THE MEDIUM OUT of every guest holding
# it. The guests were left with an empty drive, and the Engine's next `mount`
# said "fsconfig() failed: /dev/sr0: Can't open blockdev" -- a verification step
# that broke the very thing it had just verified (2026-08-13).
#
# So it runs here, against the temporary image, before anything sees it.
if (-not $DryRun) {
    $img = Mount-DiskImage -ImagePath $tempIso -PassThru
    try {
        $letter = ($img | Get-Volume).DriveLetter
        $missing = @()
        foreach ($f in 'scripts\lab_engine_setup.sh', 'scripts\lab_client_setup.ps1',
                       'scripts\lab_host_finalize.ps1', 'scripts\setup_lab_vms.ps1',
                       'certs\engine-cert.pem', 'certs\engine-key.pem', 'pyproject.toml') {
            if (-not (Test-Path "${letter}:\$f")) { $missing += $f }
        }
        if ($missing) { throw "Image is missing: $($missing -join ', ')" }
        Ok 'scripts, certs and pyproject.toml are on the disc'

        # Prove freshness rather than assume it: compare against the working copy.
        $onDisc = (Get-FileHash "${letter}:\scripts\lab_engine_setup.sh").Hash
        $onHost = (Get-FileHash (Join-Path $RepoPath 'scripts\lab_engine_setup.sh')).Hash
        if ($onDisc -ne $onHost) { throw 'lab_engine_setup.sh on the disc does not match the working copy.' }
        Ok 'disc matches the working copy'

        # LINE ENDINGS, because this disc crosses an OS boundary. A shell script
        # with CRLF fails in the guest as `set: Illegal option -`, since dash
        # reads the carriage return as part of the argument -- an error that
        # names neither the file nor the real problem. .gitattributes pins these
        # to LF, but anything that writes a file WITHOUT going through git can
        # reintroduce them: Python's write_text translates \n to \r\n on Windows,
        # which is exactly how it happened on 2026-08-13.
        $crlf = @()
        foreach ($sh in Get-ChildItem "${letter}:\scripts" -Filter *.sh) {
            if ([IO.File]::ReadAllBytes($sh.FullName) -contains 13) { $crlf += $sh.Name }
        }
        if ($crlf) {
            throw "CRLF line endings in: $($crlf -join ', '). The guest will fail with 'set: Illegal option -'. Convert to LF before re-cutting."
        }
        Ok 'shell scripts are LF, as a Linux guest requires'
    } finally {
        Dismount-DiskImage -ImagePath $tempIso | Out-Null
    }
}

# --- eject, place, re-attach -------------------------------------------------

Step '5. Place'

foreach ($name in $AttachTo) {
    if (-not (Get-VM -Name $name -ErrorAction SilentlyContinue)) {
        Warn "no such VM: $name -- skipping"
    }
}

# Eject from EVERY machine holding this image, not only the ones being attached
# to. A VM left out of -AttachTo holds the file just as firmly, and the operator
# has no reason to be tracking which ones those are.
$holders = @()
$swept = $true
if (-not $DryRun) {
    $found = Get-IsoHolders -Path $IsoPath
    if ($null -eq $found) { $swept = $false } else { $holders = @($found) }
}

if ($holders)      { Ok "held by: $($holders -join ', ')" }
elseif ($swept)    { Ok 'no VM is holding this image' }

foreach ($name in $holders) {
    Doing "eject $IsoPath from $name"
    if (-not $DryRun) {
        Get-VMDvdDrive -VMName $name | Where-Object { $_.Path -eq $IsoPath } |
            Set-VMDvdDrive -Path $null
    }
}

# Anything ejected here gets put back below, alongside -AttachTo. Ejecting a
# machine and walking away leaves its drive EMPTY, which is worse than the stale
# disc we came to replace -- and is exactly what a failed copy did on
# 2026-08-15, leaving LabEngine with nothing in the drive.
$attachNames = @($AttachTo) + $holders | Select-Object -Unique | Where-Object { $_ }

Doing "copy image to $IsoPath"
if (-not $DryRun) {
    # Hyper-V lets go asynchronously, so give it a moment rather than racing it.
    if (-not (Wait-Unlocked -Path $IsoPath)) {
        $who = if ($holders) {
                   "Held by: $($holders -join ', ') -- ejecting did not release it."
               } elseif (-not $swept) {
                   'This session could not check which VMs hold it. Re-run ELEVATED so the eject sweep can work, or shut both VMs down.'
               } else {
                   'No VM has it attached, so something else on the host holds it -- check whether the image is mounted on the host.'
               }
        throw "Cannot write $IsoPath -- still locked 20s after the eject sweep. $who If a Linux guest has the disc mounted, run 'umount /mnt' inside it first: Linux holds the medium while it is mounted, and the host cannot take it away."
    }
    try {
        Copy-Item $tempIso $IsoPath -Force
    } catch [System.IO.IOException] {
        throw "Cannot write $IsoPath -- something still holds it. If a guest has the disc mounted, run 'umount /mnt' inside it first: Linux holds the medium while it is mounted, and the host cannot take it away."
    }
    Ok "placed ($([math]::Round((Get-Item $IsoPath).Length / 1MB, 2)) MB)"
}

foreach ($name in $attachNames) {
    Doing "attach to $name"
    if ($DryRun) { continue }

    # Verify the MEDIA, not the path. Ejecting and re-attaching in quick
    # succession can fail transiently, and the failure mode observed on
    # 2026-08-13 was a reported path with DvdMediaType: None behind it.
    $attached = $false
    foreach ($attempt in 1, 2) {
        try {
            Get-VMDvdDrive -VMName $name | Set-VMDvdDrive -Path $IsoPath
        } catch {
            Warn "attach attempt $attempt failed: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 2
        $drive = Get-VMDvdDrive -VMName $name | Select-Object -First 1
        if ($drive.DvdMediaType -eq 'ISO' -and $drive.Path -eq $IsoPath) { $attached = $true; break }
        Warn "drive reports DvdMediaType '$($drive.DvdMediaType)' -- retrying"
    }
    if (-not $attached) {
        throw "Could not attach $IsoPath to $name. The guest would silently be reading the previous disc."
    }
    Ok "${name}: DvdMediaType ISO"
}

# SETTLE CHECK. An attach can verify as ISO and then drop to None seconds later,
# after this script would otherwise have exited -- observed three times on
# 2026-08-13, apparently because Hyper-V notices asynchronously that the backing
# file was replaced. The operator then finds an empty drive with nothing to
# explain it, goes looking in the guest, and finds "Can't open blockdev" or a
# missing D:. Checking once immediately after attaching is not enough; the point
# is to still be here when it happens.
if ($attachNames -and -not $DryRun) {
    Doing 'settle check -- media can drop seconds after a successful attach'
    Start-Sleep -Seconds 8

    foreach ($name in $attachNames) {
        $drive = Get-VMDvdDrive -VMName $name | Select-Object -First 1
        if ($drive.DvdMediaType -eq 'ISO') {
            Ok "${name}: still attached after settling"
            continue
        }

        Warn "$name dropped the media after attaching -- re-attaching"
        Get-VMDvdDrive -VMName $name | Set-VMDvdDrive -Path $IsoPath
        Start-Sleep -Seconds 5

        $drive = Get-VMDvdDrive -VMName $name | Select-Object -First 1
        if ($drive.DvdMediaType -ne 'ISO') {
            throw "$name will not hold the media. Check it by hand: Get-VMDvdDrive -VMName $name"
        }
        Ok "${name}: re-attached and holding"
    }
}

Write-Host @"

Done.
  In the guest, to read it:   mount -o ro /dev/sr0 /mnt
  Before re-cutting it:       umount /mnt          (Linux holds the medium)
"@ -ForegroundColor Green

if ($DryRun) { Write-Host "DRY RUN -- nothing was changed.`n" -ForegroundColor Magenta }

# Explicit, because a caught-and-retried attach failure leaves $? false and
# would otherwise report a successful, verified build as a failure.
exit 0
