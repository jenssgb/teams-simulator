#Requires -Version 5.1
<#
.SYNOPSIS
    Verify that the Teams Simulator is correctly installed on this VM.

.DESCRIPTION
    Reports OK / FAIL for each prerequisite. On the last line prints a
    one-line "READY" banner if Teams will see both devices, otherwise
    explains exactly what is still missing.

    Exits with code 0 if everything is fine, 1 otherwise.

.PARAMETER Verbose
    Print extra information (full device listings, signature data).

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

function Check {
    param([string]$Label, [scriptblock]$Probe)
    Write-Host -NoNewline ("  {0,-46}" -f $Label)
    try {
        $info = & $Probe
        Write-Host '  [OK]' -ForegroundColor Green
        if ($info) { Write-Host ("      $info") -ForegroundColor DarkGray }
        $script:ok++
        return $true
    } catch {
        Write-Host '  [FAIL]' -ForegroundColor Red
        Write-Host ("      $_") -ForegroundColor DarkRed
        $script:fail++
        return $false
    }
}

function Get-LastPythonError {
    # Pull the last meaningful "ErrorType: message" line out of a Python
    # traceback so we don't spam the user with a wall of stack-trace text.
    param([string]$Output)
    if (-not $Output) { return '' }
    $lines = @($Output -split "`r?`n" | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    # Walk from the end - the actual exception line is always at the bottom.
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        $ln = $lines[$i]
        if ($ln -match '([A-Za-z_][A-Za-z0-9_.]*Error):\s*(.+)$') {
            return ("{0}: {1}" -f $matches[1], $matches[2])
        }
    }
    if ($lines.Count -gt 0) { return $lines[-1] }
    return $Output
}

function Find-RealPython {
    # Same idea as install.ps1's Find-PythonExe: ignore the Microsoft
    # Store python alias (0-byte stub in WindowsApps) and surface a
    # path to a real python.exe, or $null.
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $exe = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe)) { return $exe }
    }
    foreach ($c in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        if ($c.Source -match '\\WindowsApps\\python\.exe$') {
            $f = Get-Item -LiteralPath $c.Source -ErrorAction SilentlyContinue
            if (-not $f -or $f.Length -lt 1024) { continue }
        }
        $out = & $c.Source --version 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -and $out -match 'Python\s+3\.') { return $c.Source }
    }
    return $null
}

Write-Host ""
Write-Host "Teams Simulator Verification" -ForegroundColor Magenta
Write-Host "============================" -ForegroundColor Magenta

# -- system tools --
Check "real python on PATH (not the Store alias)" {
    $exe = Find-RealPython
    if (-not $exe) {
        throw "no real python.exe found - the Microsoft Store alias does not count. Run setup\install.ps1 to install."
    }
    return ((& $exe --version 2>&1 | Out-String).Trim() + "  ($exe)")
} | Out-Null

Check "ffmpeg on PATH (MP3 decoding)" {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "ffmpeg missing - WAV/FLAC will work, MP3 will not" }
    return ($cmd.Source)
} | Out-Null

# -- venv + project --
$venvOk = Check "project venv at .venv\Scripts\python.exe" {
    if (-not (Test-Path $VenvPy)) { throw "venv missing - run setup\install.ps1 first" }
    return (& $VenvPy --version 2>&1)
}

if ($venvOk) {
    Check "Python deps importable" {
        $out = & $VenvPy -c "import sounddevice, soundfile, numpy, scipy, cv2, pyvirtualcam, pydub; print('ok')" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "import failed: $out" }
    } | Out-Null

    Check "teams_simulator package importable" {
        $ver = & $VenvPy -c "import teams_simulator; print(teams_simulator.__version__)" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "package not installed; run pip install -e . in venv" }
        return "version $ver"
    } | Out-Null

    Check "bundled avatars present (samples\avatars)" {
        $manifest = Join-Path $RepoRoot 'samples\avatars\avatars.json'
        if (-not (Test-Path $manifest)) { throw "manifest missing - re-clone the repo" }
        $entries = Get-Content $manifest -Raw | ConvertFrom-Json
        if (-not $entries -or $entries.Count -lt 1) { throw "manifest empty" }
        foreach ($e in $entries) {
            $p = Join-Path $RepoRoot $e.file
            if (-not (Test-Path $p)) { throw "avatar file missing: $($e.file)" }
        }
        return ("$($entries.Count) avatars: " + (($entries | ForEach-Object { $_.label }) -join ', '))
    } | Out-Null

    Check "Desktop shortcut 'Teams Simulator' present" {
        $candidates = @(
            (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Teams Simulator.lnk'),
            (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Teams Simulator.lnk')
        )
        $found = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $found) {
            throw "no Desktop shortcut found - re-run setup\install.ps1 -Force to (re)create it."
        }
        return $found
    } | Out-Null

    Check "Launcher 'teams-simulator.cmd' present" {
        $launcher = Join-Path $RepoRoot 'teams-simulator.cmd'
        if (-not (Test-Path $launcher)) { throw "missing launcher: $launcher" }
        return $launcher
    } | Out-Null

    Check "VB-Cable 'CABLE Input' visible (used as audio sink)" {
        $name = & $VenvPy -c "from teams_simulator.devices import find_cable_input; print(find_cable_input())" 2>&1
        if ($LASTEXITCODE -ne 0) {
            $detail = Get-LastPythonError $name
            throw "VB-Cable not visible to PortAudio. $detail  -- VB-Cable installs the driver but Windows only loads it after a reboot. If you already rebooted: re-run setup\install.ps1 -Force."
        }
        return $name
    } | Out-Null

    Check "VB-Cable 'CABLE Output' visible (used as Teams microphone)" {
        $name = & $VenvPy -c "from teams_simulator.devices import find_cable_output; n = find_cable_output(); print(n if n else 'NONE')" 2>&1
        if ($LASTEXITCODE -ne 0 -or $name -eq 'NONE') {
            $detail = Get-LastPythonError $name
            throw "Teams will not see a microphone. $detail  -- reboot, or re-run setup\install.ps1 -Force."
        }
        return $name
    } | Out-Null

    Check "OBS Virtual Camera DirectShow filter usable" {
        $msg = & $VenvPy -c "from teams_simulator.devices import check_obs_virtual_camera; check_obs_virtual_camera(); print('ok')" 2>&1
        if ($LASTEXITCODE -ne 0) {
            $detail = Get-LastPythonError $msg
            throw "OBS Virtual Camera not registered. $detail  -- run: winget install OBSProject.OBSStudio  (and re-run setup\install.ps1)."
        }
    } | Out-Null
}

# -- OBS DLL signature, informational --
$obsDll = 'C:\Program Files\obs-studio\data\obs-plugins\win-dshow\obs-virtualcam-module64.dll'
if (Test-Path $obsDll) {
    Check "OBS Virtual Camera DLL Authenticode signature" {
        $sig = Get-AuthenticodeSignature $obsDll
        if ($sig.Status -ne 'Valid') { throw "signature status: $($sig.Status)" }
        return ($sig.SignerCertificate.Subject -replace ',.*$', '')
    } | Out-Null
}

# -- summary --
Write-Host ""
if ($fail -eq 0) {
    Write-Host "All checks passed ($ok / $($ok + $fail))." -ForegroundColor Green
    Write-Host ""
    Write-Host "READY: in Teams pick" -ForegroundColor Green
    Write-Host "   Microphone -> 'CABLE Output (VB-Audio Virtual Cable)'" -ForegroundColor White
    Write-Host "   Camera     -> 'OBS Virtual Camera'" -ForegroundColor White
    Write-Host "Then:" -ForegroundColor Green
    Write-Host "   .\.venv\Scripts\python.exe -m teams_simulator" -ForegroundColor White
    exit 0
} else {
    Write-Host "Verification failed: $fail failure(s), $ok passed." -ForegroundColor Red
    Write-Host "Re-run setup\install.ps1 (as Administrator) to fix - it is idempotent." -ForegroundColor Yellow
    exit 1
}
