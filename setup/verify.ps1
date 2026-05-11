#Requires -Version 5.1
<#
.SYNOPSIS
    Verify that the Teams Simulator is correctly installed on this VM.
.DESCRIPTION
    Reports OK / FAIL for each prerequisite:
      * Python on PATH
      * Project venv exists
      * Required Python packages importable
      * VB-Audio Virtual Cable devices visible
      * OBS Virtual Camera DirectShow filter usable
    Exits with code 0 if everything is fine, 1 otherwise.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup\verify.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPy   = Join-Path $RepoRoot '.venv\Scripts\python.exe'

$ok   = 0
$fail = 0

function Check([string]$label, [scriptblock]$probe) {
    Write-Host -NoNewline ("  {0,-42}" -f $label)
    try {
        & $probe
        Write-Host '  [OK]' -ForegroundColor Green
        $script:ok++
    } catch {
        Write-Host '  [FAIL]' -ForegroundColor Red
        Write-Host ("      $_") -ForegroundColor DarkRed
        $script:fail++
    }
}

Write-Host ""
Write-Host "Teams Simulator Verification" -ForegroundColor Magenta
Write-Host "============================" -ForegroundColor Magenta

Check "Python launcher available" {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "python not on PATH" }
}

Check "ffmpeg available (for MP3 decoding)" {
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        throw "ffmpeg not on PATH (only WAV/FLAC will work without it)"
    }
}

Check "Project venv at $VenvPy" {
    if (-not (Test-Path $VenvPy)) { throw "venv missing - run setup\install.ps1 first" }
}

if (Test-Path $VenvPy) {
    Check "Python deps importable" {
        & $VenvPy -c "import sounddevice, soundfile, numpy, scipy, cv2, pyvirtualcam, pydub" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "import failed (exit $LASTEXITCODE)" }
    }

    Check "teams_simulator package importable" {
        & $VenvPy -c "import teams_simulator; print(teams_simulator.__version__)" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "package not installed; run pip install -e . in venv" }
    }

    Check "VB-Cable 'CABLE Input' device visible" {
        & $VenvPy -c "from teams_simulator.devices import find_cable_input; find_cable_input()" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "VB-Cable missing; rerun setup\install.ps1 and reboot" }
    }

    Check "VB-Cable 'CABLE Output' device visible" {
        & $VenvPy -c "from teams_simulator.devices import find_cable_output; assert find_cable_output() is not None, 'missing'" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Teams will not see a microphone; reinstall VB-Cable" }
    }

    Check "OBS Virtual Camera DirectShow filter usable" {
        & $VenvPy -c "from teams_simulator.devices import check_obs_virtual_camera; check_obs_virtual_camera()" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "OBS Virtual Camera not registered; install OBS Studio and start it once" }
    }
}

Write-Host ""
if ($fail -eq 0) {
    Write-Host "All checks passed ($ok / $($ok + $fail))." -ForegroundColor Green
    Write-Host ""
    Write-Host "Next: in Teams pick 'CABLE Output' as mic and 'OBS Virtual Camera' as camera, then" -ForegroundColor Gray
    Write-Host "  .\.venv\Scripts\python.exe -m teams_simulator" -ForegroundColor Gray
    exit 0
} else {
    Write-Host "Verification failed: $fail failure(s), $ok passed." -ForegroundColor Red
    Write-Host "Re-run setup\install.ps1 (as Administrator) to fix." -ForegroundColor Yellow
    exit 1
}
