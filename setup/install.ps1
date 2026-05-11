#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Bootstrap script for the Teams Simulator on a fresh Windows 10/11 VM.

.DESCRIPTION
    Installs everything needed to run the simulator end-to-end:
      * Python 3.11+        (via winget if missing)
      * ffmpeg              (via winget; needed for MP3 decoding)
      * VB-Audio Virtual Cable  (silent install; the virtual microphone)
      * OBS Studio          (silent install via winget; provides the
                             DirectShow Virtual Camera filter)
    Then creates a Python venv inside the repo and installs all Python
    dependencies from requirements.txt.

    A reboot may be required after installing VB-Cable; the script tells
    you when. After the reboot, simply re-run this script — it skips
    everything that's already in place.

.PARAMETER SkipReboot
    Skip the reboot prompt at the end (CI/automation use).

.PARAMETER Force
    Reinstall everything even if it's already present.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipReboot,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$DownloadDir = Join-Path $PSScriptRoot '_downloads'
$VenvPath   = Join-Path $RepoRoot '.venv'

$VBCableUrl = 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip'
$VBCableZip = Join-Path $DownloadDir 'VBCABLE_Driver_Pack45.zip'
$VBCableDir = Join-Path $DownloadDir 'VBCABLE_Driver_Pack45'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok  ([string]$msg) { Write-Host "    [OK]  $msg" -ForegroundColor Green }
function Write-Skip([string]$msg) { Write-Host "    [--] $msg" -ForegroundColor DarkGray }
function Write-Warn2([string]$msg) { Write-Host "    [!!]  $msg" -ForegroundColor Yellow }

function Assert-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run as Administrator. Right-click PowerShell -> Run as administrator."
    }
}

function Test-CommandAvailable([string]$name) {
    $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Invoke-Winget([string[]]$args) {
    & winget @args --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
        # -1978335189 = APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE (already installed)
        throw "winget failed with exit code $LASTEXITCODE"
    }
}

function Test-DeviceInstalled([string]$nameLike) {
    $devices = Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -like "*$nameLike*" }
    return ($null -ne $devices -and $devices.Count -gt 0)
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
function Install-Python {
    Write-Step "Checking Python"
    if ((Test-CommandAvailable 'python') -and -not $Force) {
        $ver = & python --version 2>&1
        Write-Ok "Found $ver"
        return
    }
    Write-Step "Installing Python 3.11 via winget"
    if (-not (Test-CommandAvailable 'winget')) {
        throw "winget is not available. Install 'App Installer' from the Microsoft Store and re-run."
    }
    Invoke-Winget @('install','--id','Python.Python.3.11','-e')
    # Refresh PATH for the current session.
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    if (-not (Test-CommandAvailable 'python')) {
        throw "Python install completed but 'python' is still not on PATH. Open a new shell and re-run."
    }
    Write-Ok "Python installed: $(& python --version 2>&1)"
}

function Install-Ffmpeg {
    Write-Step "Checking ffmpeg"
    if ((Test-CommandAvailable 'ffmpeg') -and -not $Force) {
        Write-Ok "ffmpeg already on PATH"
        return
    }
    Write-Step "Installing ffmpeg via winget (Gyan.FFmpeg)"
    Invoke-Winget @('install','--id','Gyan.FFmpeg','-e')
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    Write-Ok "ffmpeg installed"
}

function Install-VBCable {
    Write-Step "Checking VB-Audio Virtual Cable"
    if ((Test-DeviceInstalled 'VB-Audio') -and -not $Force) {
        Write-Ok "VB-Cable driver already present"
        return $false
    }

    New-Item -ItemType Directory -Path $DownloadDir -Force | Out-Null

    if (-not (Test-Path $VBCableZip) -or $Force) {
        Write-Step "Downloading VB-Cable from vb-audio.com"
        Invoke-WebRequest -Uri $VBCableUrl -OutFile $VBCableZip -UseBasicParsing
    }

    if (Test-Path $VBCableDir) { Remove-Item $VBCableDir -Recurse -Force }
    Write-Step "Extracting installer"
    Expand-Archive -Path $VBCableZip -DestinationPath $VBCableDir -Force

    $setupExe = Join-Path $VBCableDir 'VBCABLE_Setup_x64.exe'
    if (-not (Test-Path $setupExe)) {
        throw "Could not find VBCABLE_Setup_x64.exe in extracted archive at $VBCableDir"
    }

    Write-Step "Running VB-Cable installer (silent)"
    # The VB-Cable installer accepts -i for install; '-h' for headless. Some
    # versions only accept '/S' (NSIS). We try both conservatively.
    $proc = Start-Process -FilePath $setupExe -ArgumentList '-i','-h' -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Write-Warn2 "First install attempt returned exit code $($proc.ExitCode); retrying with /S"
        $proc = Start-Process -FilePath $setupExe -ArgumentList '/S' -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            throw "VB-Cable installer failed with exit code $($proc.ExitCode)"
        }
    }
    Write-Ok "VB-Cable installed (a reboot is recommended)"
    return $true
}

function Install-Obs {
    Write-Step "Checking OBS Studio"
    $obsExe = 'C:\Program Files\obs-studio\bin\64bit\obs64.exe'
    if ((Test-Path $obsExe) -and -not $Force) {
        Write-Ok "OBS Studio already installed"
    } else {
        Write-Step "Installing OBS Studio via winget"
        Invoke-Winget @('install','--id','OBSProject.OBSStudio','-e')
        if (-not (Test-Path $obsExe)) {
            throw "OBS install completed but obs64.exe not found at expected path"
        }
        Write-Ok "OBS Studio installed"
    }

    # Register the DirectShow filter by launching OBS once. obs-studio
    # registers the filter on first run, then it stays registered even
    # when OBS isn't running.
    $filterDll = 'C:\Program Files\obs-studio\data\obs-plugins\win-dshow\obs-virtualcam-module64.dll'
    if (Test-Path $filterDll) {
        Write-Step "Registering OBS Virtual Camera DirectShow filter"
        try {
            & regsvr32.exe /s $filterDll
            Write-Ok "DirectShow filter registered"
        } catch {
            Write-Warn2 "regsvr32 failed: $_  (will try by launching OBS once)"
            Start-Process -FilePath $obsExe -ArgumentList '--minimize-to-tray','--disable-shutdown-check' -PassThru | Out-Null
            Start-Sleep -Seconds 8
            Get-Process obs64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Warn2 "obs-virtualcam-module64.dll not found; launching OBS once to self-register"
        Start-Process -FilePath $obsExe -ArgumentList '--minimize-to-tray','--disable-shutdown-check' -PassThru | Out-Null
        Start-Sleep -Seconds 8
        Get-Process obs64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

function Install-PythonDeps {
    Write-Step "Creating Python virtual environment in $VenvPath"
    if (-not (Test-Path $VenvPath) -or $Force) {
        if (Test-Path $VenvPath) { Remove-Item $VenvPath -Recurse -Force }
        & python -m venv $VenvPath
    } else {
        Write-Ok "venv already exists"
    }

    $venvPy = Join-Path $VenvPath 'Scripts\python.exe'
    if (-not (Test-Path $venvPy)) {
        throw "venv python not found at $venvPy"
    }

    Write-Step "Upgrading pip"
    & $venvPy -m pip install --quiet --upgrade pip

    Write-Step "Installing Python dependencies"
    $req = Join-Path $RepoRoot 'requirements.txt'
    & $venvPy -m pip install --quiet -r $req

    Write-Step "Installing teams-simulator (editable)"
    & $venvPy -m pip install --quiet -e $RepoRoot

    Write-Ok "Python environment ready: $VenvPath"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Teams Simulator Setup" -ForegroundColor Magenta
Write-Host "=====================" -ForegroundColor Magenta

Assert-Admin

Install-Python
Install-Ffmpeg
$rebootNeeded = Install-VBCable
Install-Obs
Install-PythonDeps

Write-Host ""
Write-Host "Setup finished." -ForegroundColor Magenta
Write-Host "Next steps:" -ForegroundColor Magenta
Write-Host "  1. Verify devices:"
Write-Host "        powershell -ExecutionPolicy Bypass -File .\setup\verify.ps1" -ForegroundColor Gray
Write-Host "  2. In Teams choose:"
Write-Host "        Microphone : 'CABLE Output (VB-Audio Virtual Cable)'" -ForegroundColor Gray
Write-Host "        Camera     : 'OBS Virtual Camera'" -ForegroundColor Gray
Write-Host "  3. Start the UI:"
Write-Host "        .\.venv\Scripts\python.exe -m teams_simulator" -ForegroundColor Gray
Write-Host ""

if ($rebootNeeded -and -not $SkipReboot) {
    $resp = Read-Host "VB-Cable was just installed. Reboot now? [y/N]"
    if ($resp -match '^[yY]') {
        Restart-Computer -Force
    } else {
        Write-Warn2 "Please reboot before running the simulator (Teams won't see the mic until then)."
    }
}
