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
    confirm the scripts are physically on it, and -- when swapping it into a VM
    -- ejects first, verifies the media took, and retries once before failing
    loudly rather than leaving a stale disc attached.

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
    VM names to swap the finished disc into. Omit to build only.

.PARAMETER DryRun
    Print every action without taking it.

.EXAMPLE
    .\scripts\build_repo_iso.ps1                            # build only
    .\scripts\build_repo_iso.ps1 -AttachTo LabEngine        # build and swap in
    .\scripts\build_repo_iso.ps1 -AttachTo LabEngine,LabClient

.NOTES
    Requires an ELEVATED PowerShell for the -AttachTo half, and oscdimg from
    the Windows ADK (Deployment Tools feature) always.

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

$vms = @()
foreach ($name in $AttachTo) {
    $vm = Get-VM -Name $name -ErrorAction SilentlyContinue
    if (-not $vm) { Warn "no such VM: $name -- skipping"; continue }
    $vms += $vm
}

# Eject BEFORE overwriting: a running VM holds the image it has mounted, and
# the copy fails outright with "being used by another process".
foreach ($vm in $vms) {
    $drive = Get-VMDvdDrive -VMName $vm.Name | Select-Object -First 1
    if ($drive -and $drive.Path -eq $IsoPath) {
        Doing "eject $IsoPath from $($vm.Name)"
        if (-not $DryRun) { $drive | Set-VMDvdDrive -Path $null }
    }
}

Doing "copy image to $IsoPath"
if (-not $DryRun) {
    try {
        Copy-Item $tempIso $IsoPath -Force
    } catch [System.IO.IOException] {
        throw "Cannot write $IsoPath -- something still holds it. If a guest has the disc mounted, run 'umount /mnt' inside it first: Linux holds the medium while it is mounted, and the host cannot take it away."
    }
    Ok "placed ($([math]::Round((Get-Item $IsoPath).Length / 1MB, 2)) MB)"
}

foreach ($vm in $vms) {
    Doing "attach to $($vm.Name)"
    if ($DryRun) { continue }

    # Verify the MEDIA, not the path. Ejecting and re-attaching in quick
    # succession can fail transiently, and the failure mode observed on
    # 2026-08-13 was a reported path with DvdMediaType: None behind it.
    $attached = $false
    foreach ($attempt in 1, 2) {
        try {
            Get-VMDvdDrive -VMName $vm.Name | Set-VMDvdDrive -Path $IsoPath
        } catch {
            Warn "attach attempt $attempt failed: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds 2
        $drive = Get-VMDvdDrive -VMName $vm.Name | Select-Object -First 1
        if ($drive.DvdMediaType -eq 'ISO' -and $drive.Path -eq $IsoPath) { $attached = $true; break }
        Warn "drive reports DvdMediaType '$($drive.DvdMediaType)' -- retrying"
    }
    if (-not $attached) {
        throw "Could not attach $IsoPath to $($vm.Name). The guest would silently be reading the previous disc."
    }
    Ok "$($vm.Name): DvdMediaType ISO"
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
