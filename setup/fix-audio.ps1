#Requires -Version 5.1
<#
.SYNOPSIS
    Force Windows to re-enumerate audio endpoints. Use when VB-Cable is
    installed (driver present in pnputil /enum-drivers) but doesn't show
    up in WASAPI / MME (and therefore not in Teams).

.DESCRIPTION
    Stops + restarts AudioEndpointBuilder + Audiosrv, optionally rescans
    for PnP changes, then prints what PortAudio sees.

    Must be run elevated (Audiosrv requires admin to stop/start).
#>
[CmdletBinding()]
param(
    [switch]$Rescan
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

. (Join-Path $PSScriptRoot '_lib\logroot.ps1')
$null = Start-LogTranscript -ScriptName 'fix-audio-console'

# Self-elevate if needed
$current   = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($current)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[INFO] not elevated - relaunching as Administrator..." -ForegroundColor Yellow
    $args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$PSCommandPath)
    if ($Rescan) { $args += '-Rescan' }
    Start-Process -Verb RunAs powershell.exe -ArgumentList $args
    exit 0
}

Write-Host ""
Write-Host "Teams Simulator - Audio service restart" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta

function Step($m) { Write-Host "[STEP] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK] $m"   -ForegroundColor Green }
function Warn($m) { Write-Host "[WARN] $m"   -ForegroundColor Yellow }

Step 'Stopping Audiosrv (this also stops dependent services)'
try {
    Stop-Service Audiosrv -Force -ErrorAction Stop
    Ok 'Audiosrv stopped'
} catch {
    Warn "could not stop Audiosrv: $_"
}

Step 'Stopping AudioEndpointBuilder'
try {
    Stop-Service AudioEndpointBuilder -Force -ErrorAction Stop
    Ok 'AudioEndpointBuilder stopped'
} catch {
    Warn "could not stop AudioEndpointBuilder: $_"
}

if ($Rescan) {
    Step 'Triggering PnP rescan via pnputil /scan-devices'
    & pnputil.exe /scan-devices 2>&1 | ForEach-Object { "  $_" }
    Ok 'rescan complete'
}

Start-Sleep -Seconds 2

Step 'Starting AudioEndpointBuilder'
Start-Service AudioEndpointBuilder
Ok 'AudioEndpointBuilder started'

Step 'Starting Audiosrv'
Start-Service Audiosrv
Ok 'Audiosrv started'

Start-Sleep -Seconds 3

Step 'Querying PortAudio device list'
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPy   = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPy) {
    $tmpPy = Join-Path $env:TEMP "ts_fixaudio_$([Guid]::NewGuid().ToString('N')).py"
    @'
import sounddevice as sd
hostapis = sd.query_hostapis()
hits = []
for i, d in enumerate(sd.query_devices()):
    api = hostapis[d["hostapi"]]["name"]
    line = "  [%2d] in=%2d out=%2d  %-20s  %s" % (
        i, d["max_input_channels"], d["max_output_channels"], api, d["name"]
    )
    if "vb-audio" in d["name"].lower() or "cable" in d["name"].lower():
        hits.append(line)
if hits:
    print("VB-Audio / CABLE devices visible to PortAudio:")
    for h in hits:
        print(h)
else:
    print("  (no VB-Audio / CABLE device found - the driver is not enumerated)")
'@ | Set-Content -LiteralPath $tmpPy -Encoding UTF8
    & $venvPy $tmpPy
    Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue
} else {
    Warn '.venv missing - run setup\install.ps1 first'
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Audio services restarted." -ForegroundColor Green
Write-Host ""
Write-Host " If VB-Cable now shows up above, you are good - launch the" -ForegroundColor Green
Write-Host " 'Teams Simulator' icon and start streaming." -ForegroundColor Green
Write-Host ""
Write-Host " If it still does NOT show up:" -ForegroundColor Yellow
Write-Host "   1. Try with rescan:  .\setup\fix-audio.ps1 -Rescan" -ForegroundColor Gray
Write-Host "   2. Reboot the VM and re-run this script." -ForegroundColor Gray
Write-Host "   3. Open Device Manager, find 'VB-Audio Virtual Cable'" -ForegroundColor Gray
Write-Host "      under 'Sound, video and game controllers',"        -ForegroundColor Gray
Write-Host "      right-click -> Disable, then Enable."              -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Press Enter to close this window..." -ForegroundColor Cyan
try { [void](Read-Host) } catch { Start-Sleep -Seconds 30 }
