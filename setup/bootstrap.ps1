#Requires -Version 5.1
<#
.SYNOPSIS
    One-liner bootstrap: clone the Teams Simulator repo and run the
    headless installer. Designed for: copy URL once, paste into an
    elevated PowerShell on a fresh VM, walk away.

.DESCRIPTION
    Steps:
      1. Make sure git is available (winget-install if missing).
      2. Clone $RepoUrl into $TargetDir (default: C:\teams-simulator).
      3. Invoke setup\install.ps1 with whatever switches you pass via
         -InstallArgs (default: -Auto for fully unattended).

.PARAMETER RepoUrl
    Git URL of the teams-simulator repo. Override if you forked it.

.PARAMETER TargetDir
    Where to clone. Default: C:\teams-simulator

.PARAMETER InstallArgs
    Arguments forwarded to install.ps1. Default: '-Auto'

.EXAMPLE
    # Fresh Win11 VM, elevated PowerShell, one paste:
    iex (irm 'https://raw.githubusercontent.com/jenssgb/teams-simulator/main/setup/bootstrap.ps1')

.EXAMPLE
    # Custom location and interactive install:
    .\bootstrap.ps1 -TargetDir D:\sim -InstallArgs ''
#>
[CmdletBinding()]
param(
    [string]$RepoUrl     = 'https://github.com/jenssgb/teams-simulator.git',
    [string]$TargetDir   = 'C:\teams-simulator',
    [string]$InstallArgs = '-Auto'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# When bootstrap is invoked via 'iex (irm ...)' there is no script file
# on disk yet, so $PSScriptRoot is empty. Fall back to TEMP for the very
# first transcript; later install.ps1 will route logs to Desktop properly.
$bootstrapLogDir = $null
try {
    $userDesktop = [Environment]::GetFolderPath('Desktop')
    if ($userDesktop) {
        $bootstrapLogDir = Join-Path $userDesktop 'TeamsSimulatorLogs'
        New-Item -ItemType Directory -Path $bootstrapLogDir -Force -ErrorAction Stop | Out-Null
    }
} catch { $bootstrapLogDir = Join-Path $env:TEMP 'TeamsSimulatorLogs'; New-Item -ItemType Directory -Path $bootstrapLogDir -Force -ErrorAction SilentlyContinue | Out-Null }

if ($bootstrapLogDir) {
    $bootstrapLog = Join-Path $bootstrapLogDir ("bootstrap-console-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch { }
    try {
        Start-Transcript -Path $bootstrapLog -Append -Force -ErrorAction Stop | Out-Null
        Write-Host "[log] transcript -> $bootstrapLog" -ForegroundColor DarkGray
    } catch {
        Write-Host "[log] transcript could not start: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

function Test-Cmd([string]$n) { $null -ne (Get-Command $n -ErrorAction SilentlyContinue) }
function Step([string]$m)     { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok  ([string]$m)     { Write-Host "    [OK]  $m" -ForegroundColor Green }

# Admin required because install.ps1 is.
$current   = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($current)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "bootstrap.ps1 must be run from an elevated PowerShell (Run as Administrator)."
}

if (-not (Test-Cmd git)) {
    Step "git not found - installing via winget"
    if (-not (Test-Cmd winget)) {
        throw "winget is not available. Install 'App Installer' from the Microsoft Store first."
    }
    & winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
    if (-not (Test-Cmd git)) { throw "git install completed but git is not on PATH." }
    Ok "git installed"
}

if (Test-Path $TargetDir) {
    Step "$TargetDir already exists - pulling latest"
    Push-Location $TargetDir
    try { & git pull --ff-only } finally { Pop-Location }
} else {
    Step "cloning $RepoUrl -> $TargetDir"
    & git clone $RepoUrl $TargetDir
}

$installScript = Join-Path $TargetDir 'setup\install.ps1'
if (-not (Test-Path $installScript)) {
    throw "After clone, install.ps1 was not found at $installScript"
}

Step "running install.ps1 $InstallArgs"
$argList = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$installScript)
if ($InstallArgs.Trim()) {
    # Split on whitespace (simple but enough for switch-style args).
    $argList += ($InstallArgs.Trim() -split '\s+')
}
try {
    & powershell.exe @argList
    $exit = $LASTEXITCODE
} finally {
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch { }
    # User-friendly: never let the window close before the user has
    # seen whether bootstrap succeeded.
    Write-Host ""
    if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected -and -not $env:TEAMS_SIMULATOR_NONINTERACTIVE) {
        Write-Host "Press Enter to close this window..." -ForegroundColor Cyan
        try { [void](Read-Host) } catch { Start-Sleep -Seconds 30 }
    }
}
exit $exit
