<#
.SYNOPSIS
    Save a PNG of a Hyper-V guest's console, without touching the guest.

.DESCRIPTION
    Diagnostic aid for Part 0. VMConnect shows the guest console but cannot be
    read by anything except a person looking at it, which makes "what is on the
    screen right now?" impossible to answer over a terminal, in a log, or from
    a remote session.

    Hyper-V exposes the framebuffer through WMI --
    Msvm_VirtualSystemManagementService::GetVirtualSystemThumbnailImage -- and
    this wraps that call. It reads the guest's video memory from the host side:
    no agent, no integration services, no network, and nothing typed into the
    guest. It works on a machine sitting at a boot menu or an installer, which
    is exactly when nothing else can see anything.

    WHY THIS IS IN THE REPOSITORY. It earned its place on 2026-08-13: the Debian
    installer had stopped at a screen listing kernel udebs, which reads as
    "expert mode" and is nothing of the sort. The banner naming the real cause
    -- LOW MEMORY MODE, from the VM's 512 MB -- was in the top-left corner, and
    a capture is what made it legible. Guessing would have cost the install.

    The API returns RGB565, two bytes per pixel, top-down. Sizes larger than the
    guest's current mode are refused, so drop to 640x480 if 800x600 fails.

.PARAMETER VMName
    The VM to capture.

.PARAMETER Width
    Capture width in pixels. Must not exceed the guest's current video mode.

.PARAMETER Height
    Capture height in pixels.

.PARAMETER Out
    Where to write the PNG. Defaults to the current directory.

.EXAMPLE
    .\scripts\vm_console_shot.ps1 -VMName LabEngine
    .\scripts\vm_console_shot.ps1 -VMName LabClient -Width 640 -Height 480 -Out C:\temp\c.png

.NOTES
    Requires an ELEVATED PowerShell (the virtualization WMI namespace is
    admin-only) and a RUNNING VM -- a powered-off VM has no framebuffer and the
    call returns a failure code rather than a black image.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $VMName,
    [int]    $Width  = 800,
    [int]    $Height = 600,
    [string] $Out    = "$VMName-console.png"
)

$ErrorActionPreference = 'Stop'
$ns = 'root\virtualization\v2'

$vm = Get-CimInstance -Namespace $ns -ClassName Msvm_ComputerSystem -Filter "ElementName='$VMName'"
if (-not $vm) { throw "No such VM: '$VMName'." }
if ($vm.EnabledState -ne 2) {
    throw "'$VMName' is not running. A powered-off VM has no framebuffer to read."
}

# The REALIZED settings object, not the recorded one: snapshots also surface here.
$settings = Get-CimAssociatedInstance -InputObject $vm -ResultClassName Msvm_VirtualSystemSettingData |
            Where-Object { $_.VirtualSystemType -eq 'Microsoft:Hyper-V:System:Realized' }

$svc = Get-CimInstance -Namespace $ns -ClassName Msvm_VirtualSystemManagementService

$r = Invoke-CimMethod -InputObject $svc -MethodName GetVirtualSystemThumbnailImage -Arguments @{
    TargetSystem = [ciminstance]$settings
    WidthPixels  = [uint16]$Width
    HeightPixels = [uint16]$Height
}
if ($r.ReturnValue -ne 0) {
    throw "GetVirtualSystemThumbnailImage failed ($($r.ReturnValue)). Try a smaller size -- the request cannot exceed the guest's current video mode."
}

Add-Type -AssemblyName System.Drawing
$fmt  = [System.Drawing.Imaging.PixelFormat]::Format16bppRgb565
$bmp  = New-Object System.Drawing.Bitmap($Width, $Height, $fmt)
$rect = New-Object System.Drawing.Rectangle(0, 0, $Width, $Height)
$data = $bmp.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::WriteOnly, $fmt)
try {
    # Copy row by row: the bitmap's stride is padded, the WMI buffer is not.
    $rowBytes = $Width * 2
    for ($y = 0; $y -lt $Height; $y++) {
        [System.Runtime.InteropServices.Marshal]::Copy(
            $r.ImageData, $y * $rowBytes,
            [IntPtr]::Add($data.Scan0, $y * $data.Stride),
            $rowBytes)
    }
} finally {
    $bmp.UnlockBits($data)
}

$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

Write-Host "saved $((Resolve-Path $Out).Path)" -ForegroundColor Green
