#Requires -Version 5.1
<#
.SYNOPSIS
    One-stop deep diagnostic that the user can paste back to support.

.DESCRIPTION
    Checks every plausible reason VB-Cable + OBS Virtual Camera might
    not show up in Teams, writes the report to setup\_logs\diagnose-*.txt
    AND copies the whole report to the clipboard.

    No admin required to RUN, but admin gives more accurate driver info.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'  # NEVER throw - we want every check to run
$ProgressPreference    = 'SilentlyContinue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir   = Join-Path $PSScriptRoot '_logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogFile  = Join-Path $LogDir ("diagnose-{0}.txt" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

# Use a shared StringBuilder so we can both print AND save AND copy.
$sb = [System.Text.StringBuilder]::new()
function Out-Both {
    param([Parameter(ValueFromPipeline = $true)]$Msg)
    process {
        $line = if ($null -eq $Msg) { '' } else { ($Msg | Out-String).TrimEnd() }
        Write-Host $line
        [void]$sb.AppendLine($line)
    }
}
function Section($title) { Out-Both ""; Out-Both ("=== {0} ===" -f $title) }

Out-Both "Teams Simulator - Diagnostics"
Out-Both "==============================="
Out-Both ("date          : {0}" -f (Get-Date -Format 'u'))
Out-Both ("user          : {0}\{1}" -f $env:USERDOMAIN, $env:USERNAME)
Out-Both ("computer      : {0}" -f $env:COMPUTERNAME)
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
if ($os) {
    Out-Both ("os            : {0} (build {1})" -f $os.Caption, $os.BuildNumber)
}
$elev = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Out-Both ("elevated      : {0}" -f $elev)
Out-Both ("repo          : {0}" -f $RepoRoot)

# ---------------------------------------------------------------------------
Section 'HVCI / Memory Integrity  (this commonly blocks VB-Cable on Win11)'
# ---------------------------------------------------------------------------
$dg = Get-CimInstance -ClassName Win32_DeviceGuard -Namespace 'root\Microsoft\Windows\DeviceGuard' -ErrorAction SilentlyContinue
if (-not $dg) {
    Out-Both "  (Win32_DeviceGuard not available - probably non-Pro SKU; OK)"
} else {
    Out-Both ("  VBS status            : {0}   (0=off, 1=configured, 2=running)" -f $dg.VirtualizationBasedSecurityStatus)
    Out-Both ("  SecurityServicesRunning: {0}   (1=Cred Guard, 2=HVCI/Memory Integrity)" -f ($dg.SecurityServicesRunning -join ','))
    if ($dg.SecurityServicesRunning -contains 2) {
        Out-Both ""
        Out-Both "  >>>>>> WARNING: Memory Integrity is ON <<<<<<"
        Out-Both "  This is the #1 reason VB-Cable does not load on Windows 11 VMs."
        Out-Both "  Fix:  Settings -> Privacy & security -> Windows Security ->"
        Out-Both "        Device security -> Core isolation details ->"
        Out-Both "        Memory integrity = OFF  -> reboot."
    }
}

# ---------------------------------------------------------------------------
Section 'VB-Cable - files on disk'
# ---------------------------------------------------------------------------
$paths = @(
    "$env:SystemRoot\System32\drivers\vbaudio_cable64_win10.sys",
    "$env:SystemRoot\System32\drivers\vbaudio_cable_win10.sys",
    "$env:SystemRoot\System32\drivers\vbaudio_cable64.sys",
    "$env:ProgramFiles\VB\CABLE\VBCABLE_ControlPanel.exe",
    "${env:ProgramFiles(x86)}\VB\CABLE\VBCABLE_ControlPanel.exe"
)
foreach ($p in $paths) {
    if (Test-Path -LiteralPath $p) {
        $info = Get-Item -LiteralPath $p
        Out-Both ("  [OK]   {0}  ({1} bytes, {2})" -f $p, $info.Length, $info.LastWriteTime)
    } else {
        Out-Both ("  [MISS] {0}" -f $p)
    }
}

# ---------------------------------------------------------------------------
Section 'VB-Cable - registered as signed driver'
# ---------------------------------------------------------------------------
$drv = Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
    Where-Object {
        $_.DeviceName   -like '*CABLE*'  -or
        $_.DeviceName   -like '*VB-Audio*' -or
        $_.Manufacturer -like '*VB-Audio*'
    }
if (-not $drv) {
    Out-Both "  (no matching driver registered - VB-Cable did not install or got rolled back)"
} else {
    $drv | Select-Object DeviceName, Manufacturer, DriverVersion, DriverDate, IsSigned |
        Format-Table -AutoSize | Out-String | Out-Both
}

# ---------------------------------------------------------------------------
Section 'VB-Cable - PnP devices'
# ---------------------------------------------------------------------------
$pnp = Get-PnpDevice -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FriendlyName -like '*CABLE*' -or
        $_.FriendlyName -like '*VB-Audio*'
    }
if (-not $pnp) {
    Out-Both "  (Get-PnpDevice sees nothing - audio service has NOT enumerated the endpoint)"
} else {
    $pnp | Select-Object Status, Class, FriendlyName, InstanceId |
        Format-Table -AutoSize | Out-String | Out-Both
}

# ---------------------------------------------------------------------------
Section 'pnputil /enum-drivers (filtered)'
# ---------------------------------------------------------------------------
$pn = & pnputil.exe /enum-drivers 2>&1 | Out-String
$blocks = $pn -split "`r?`n`r?`n"
$matched = $blocks | Where-Object { $_ -match 'VB-?Audio|CABLE|vbaudio' }
if ($matched) {
    foreach ($b in $matched) { Out-Both $b; Out-Both '' }
} else {
    Out-Both "  (no VB-Audio entry in driver store - install never completed)"
}

# ---------------------------------------------------------------------------
Section 'Windows Audio services'
# ---------------------------------------------------------------------------
Get-Service Audiosrv, AudioEndpointBuilder -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType | Format-Table -AutoSize | Out-String | Out-Both

# ---------------------------------------------------------------------------
Section 'OBS Virtual Camera DirectShow filter'
# ---------------------------------------------------------------------------
$obsClsid = '{A3FCE0F5-3493-419F-958A-ABA1250EC20B}'
foreach ($p in "HKLM:\SOFTWARE\Classes\CLSID\$obsClsid", "HKLM:\SOFTWARE\Classes\WOW6432Node\CLSID\$obsClsid") {
    if (Test-Path $p) { Out-Both ("  [OK]   $p") } else { Out-Both ("  [MISS] $p") }
}

# ---------------------------------------------------------------------------
Section 'PortAudio - what Python actually sees'
# ---------------------------------------------------------------------------
$venvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPy) {
    $tmpPy = Join-Path $env:TEMP "ts_diag_$([Guid]::NewGuid().ToString('N')).py"
    @'
import sounddevice as sd
hostapis = sd.query_hostapis()
for i, d in enumerate(sd.query_devices()):
    api = hostapis[d["hostapi"]]["name"]
    print("  [%2d] in=%2d out=%2d  %-14s  %s" % (
        i, d["max_input_channels"], d["max_output_channels"], api, d["name"]
    ))
'@ | Set-Content -LiteralPath $tmpPy -Encoding UTF8
    $py = & $venvPy $tmpPy 2>&1 | Out-String
    Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue
    Out-Both $py
    $hasCableInput  = $py -match 'CABLE Input'
    $hasCableOutput = $py -match 'CABLE Output'
    Out-Both ("  CABLE Input  visible to PortAudio : {0}" -f $hasCableInput)
    Out-Both ("  CABLE Output visible to PortAudio : {0}" -f $hasCableOutput)
} else {
    Out-Both "  (.venv missing - run setup\install.ps1 first)"
}

# ---------------------------------------------------------------------------
Section 'Last install log (tail 40 lines)'
# ---------------------------------------------------------------------------
$lastLog = Get-ChildItem (Join-Path $LogDir 'install-*.log') -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($lastLog) {
    Out-Both ("  source: " + $lastLog.FullName)
    Get-Content $lastLog.FullName -Tail 40 | Out-Both
} else {
    Out-Both "  (no install log found in $LogDir)"
}

# ---------------------------------------------------------------------------
# Persist + clipboard
# ---------------------------------------------------------------------------
Set-Content -LiteralPath $LogFile -Value ($sb.ToString()) -Encoding UTF8
$copied = $false
try {
    $sb.ToString() | Set-Clipboard
    $copied = $true
} catch { $copied = $false }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host " Diagnostics complete." -ForegroundColor Magenta
if ($copied) {
    Write-Host " Full report has been COPIED TO YOUR CLIPBOARD." -ForegroundColor Green
}
Write-Host (" Saved to: {0}" -f $LogFile) -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "Press Enter to close this window..." -ForegroundColor Cyan
try { [void](Read-Host) } catch { Start-Sleep -Seconds 30 }
