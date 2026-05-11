#Requires -Version 5.1
<#
.SYNOPSIS
    Headless end-to-end installer for the Teams Simulator on a fresh
    Windows 10/11 VM.

.DESCRIPTION
    Installs everything required to run the simulator:
      * Python 3.11+              (winget: Python.Python.3.11)
      * ffmpeg                    (winget: Gyan.FFmpeg, for MP3 decoding)
      * VB-Audio Virtual Cable    (download + silent NSIS install)
      * OBS Studio                (winget: OBSProject.OBSStudio, ships
                                   the DirectShow Virtual Camera filter)
      * Project venv + pip deps   (.venv inside the repo)

    The script is **idempotent**: anything already installed is detected
    and skipped, so it is safe to re-run (e.g. after the post-VB-Cable
    reboot).

    With -Auto it runs fully unattended: no prompts, auto-reboot when
    VB-Cable was just installed, and an optional scheduled task that
    resumes the script automatically after the reboot.

.PARAMETER Auto
    Unattended mode — no interactive elevation prompts, accept all
    third-party EULAs, install everything in silent mode, register a
    one-shot scheduled task ("TeamsSimulatorSetupResume") that re-runs
    this script after the reboot to finish + verify. The script asks
    ONE final yes/no question before actually rebooting (default Y),
    so the user can confirm the reboot happens at a sensible moment.

.PARAMETER NoReboot
    Never reboot, even if VB-Cable installation needs it. The script
    prints a warning and exits with code 2 in that case.

.PARAMETER Force
    Reinstall everything even if already present.

.PARAMETER DryRun
    Log every action that would be taken, but do not actually run any
    installer or modify the system. Useful for verification.

.PARAMETER ContinueAfterReboot
    Internal: set by the scheduled task that resumes the install after
    a reboot. Triggers the post-reboot phase (deps + verify) and
    deletes the task.

.PARAMETER LogFile
    Optional path to a log file. Defaults to setup\_logs\install-<timestamp>.log.

.EXAMPLE
    # Interactive install on a freshly-provisioned VM:
    powershell -ExecutionPolicy Bypass -File .\setup\install.ps1

.EXAMPLE
    # Fully unattended install (CI / automation / kiosk VM):
    powershell -ExecutionPolicy Bypass -File .\setup\install.ps1 -Auto

.EXAMPLE
    # See what would happen without touching the system:
    powershell -ExecutionPolicy Bypass -File .\setup\install.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [switch]$Auto,
    [switch]$NoReboot,
    [switch]$Force,
    [switch]$DryRun,
    [switch]$ContinueAfterReboot,
    [string]$LogFile
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
$RepoRoot    = Split-Path -Parent $PSScriptRoot
$DownloadDir = Join-Path $PSScriptRoot '_downloads'
$LogDir      = Join-Path $PSScriptRoot '_logs'
$VenvPath    = Join-Path $RepoRoot '.venv'
$VenvPy      = Join-Path $VenvPath 'Scripts\python.exe'
$ScriptPath  = $MyInvocation.MyCommand.Path

$VBCableUrl  = 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip'
$VBCableZip  = Join-Path $DownloadDir 'VBCABLE_Driver_Pack45.zip'
$VBCableDir  = Join-Path $DownloadDir 'VBCABLE_Driver_Pack45'

$ObsExe      = 'C:\Program Files\obs-studio\bin\64bit\obs64.exe'
$ObsFilter   = 'C:\Program Files\obs-studio\data\obs-plugins\win-dshow\obs-virtualcam-module64.dll'

$ResumeTaskName = 'TeamsSimulatorSetupResume'

# winget exit codes that mean "this is fine"
$WingetOk    = 0
$WingetNoUpd = -1978335189   # APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE

# State flags filled in during the run
$script:RebootRequired = $false
$script:DryRun         = [bool]$DryRun

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
if (-not $LogFile) {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    $LogFile = Join-Path $LogDir ("install-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
}

function Write-Journal {
    param([string]$Level, [string]$Message, [ConsoleColor]$Color = 'Gray')
    $ts = Get-Date -Format 'HH:mm:ss'
    $line = "[$ts] [$Level] $Message"
    Write-Host $line -ForegroundColor $Color
    try { Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue }
    catch { $null = $_ } # logging failures must never break the installer
}
function Write-Step ([string]$m) { Write-Journal 'STEP' $m  Cyan }
function Write-Ok   ([string]$m) { Write-Journal ' OK ' $m  Green }
function Write-Skip ([string]$m) { Write-Journal 'SKIP' $m  DarkGray }
function Write-Warn2([string]$m) { Write-Journal 'WARN' $m  Yellow }
function Write-ErrL ([string]$m) { Write-Journal ' ERR' $m  Red }
function Write-Dry  ([string]$m) { Write-Journal 'DRY ' $m  Magenta }

function Invoke-Action {
    <#
        Runs a script block normally, OR logs it without executing
        when -DryRun is active.
    #>
    param(
        [string]$Description,
        [scriptblock]$Action
    )
    if ($script:DryRun) {
        Write-Dry $Description
        return
    }
    & $Action
}

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
function Assert-Admin {
    if ($script:DryRun) { return }
    $current   = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run as Administrator. Right-click PowerShell -> Run as administrator. (Use -DryRun to inspect what would happen without admin.)"
    }
}

function Test-CommandAvailable([string]$name) {
    $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Update-SessionPath {
    $env:Path = `
        [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + `
        [Environment]::GetEnvironmentVariable('Path','User')
}

function Find-PythonExe {
    <#
        Returns the absolute path to a usable python.exe (>= 3.10), or
        $null if none is installed. Critically: ignores the Microsoft
        Store "App Execution Alias" (Windows 10/11 ships a 0-byte
        python.exe stub in WindowsApps that just nags the user to
        install Python from the Store - it returns from `Get-Command`
        but throws when actually executed).
    #>
    # 1) Prefer the py launcher - if installed, it always points at a
    #    real Python.
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $exe = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe)) {
            $ver = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($ver -match '^3\.(1[0-9]|[2-9])') { return $exe }
        }
    }

    # 2) Walk every python.exe on PATH; skip the Store alias (zero-byte
    #    reparse point) and require a working --version.
    $cands = @(Get-Command python.exe -All -ErrorAction SilentlyContinue)
    foreach ($c in $cands) {
        if ($c.Source -match '\\WindowsApps\\python\.exe$') {
            $f = Get-Item -LiteralPath $c.Source -ErrorAction SilentlyContinue
            if (-not $f -or $f.Length -lt 1024) { continue }
        }
        $out = & $c.Source --version 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -and $out -match 'Python\s+3\.(1[0-9]|[2-9])') {
            return $c.Source
        }
    }

    # 3) Known per-user / per-machine install locations from python.org
    #    + winget. Try newest first.
    $known = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe"
    )
    foreach ($k in $known) {
        if (Test-Path -LiteralPath $k) {
            $out = & $k --version 2>&1 | Out-String
            if ($LASTEXITCODE -eq 0 -and $out -match 'Python\s+3\.(1[0-9]|[2-9])') {
                return $k
            }
        }
    }

    return $null
}

# Resolved during Install-Python; used by Install-PythonDeps and
# friends. Avoids relying on the App Execution Alias.
$script:PythonExe = $null

function Test-VBCableInstalled {
    # The driver registers a sound device whose FriendlyName starts with
    # "CABLE Input" / "CABLE Output". Get-PnpDevice surfaces these as
    # AudioEndpoint or MEDIA class devices.
    $hits = Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object {
        $_.FriendlyName -like '*VB-Audio*' -or $_.FriendlyName -like 'CABLE *'
    }
    return ($null -ne $hits -and $hits.Count -gt 0)
}

function Test-ObsVirtualCamRegistered {
    # The OBS Virtual Camera registers as a DirectShow source named
    # "OBS Virtual Camera" under HKLM\SOFTWARE\Classes\CLSID. Easiest
    # cross-version probe: look for the well-known CLSID key.
    $clsid = '{A3FCE0F5-3493-419F-958A-ABA1250EC20B}'   # OBS Virtual Camera (since OBS 28+)
    $paths = @(
        "HKLM:\SOFTWARE\Classes\CLSID\$clsid",
        "HKLM:\SOFTWARE\Classes\WOW6432Node\CLSID\$clsid"
    )
    foreach ($p in $paths) { if (Test-Path $p) { return $true } }
    return $false
}

# ---------------------------------------------------------------------------
# winget helpers
# ---------------------------------------------------------------------------
function Test-Winget {
    if (-not (Test-CommandAvailable 'winget')) { return $false }
    try {
        $null = & winget --version 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Invoke-WingetInstall {
    param(
        [Parameter(Mandatory)] [string]$Id,
        [int]$Retries = 2
    )
    if (-not (Test-Winget)) {
        throw "winget is unavailable. On Windows 10 install 'App Installer' from the Microsoft Store first."
    }
    for ($i = 0; $i -le $Retries; $i++) {
        Write-Step "winget install --id $Id (attempt $($i+1)/$($Retries+1))"
        if ($script:DryRun) {
            Write-Dry "would run: winget install --id $Id -e --silent --accept-source-agreements --accept-package-agreements"
            return
        }
        & winget install --id $Id -e --silent `
            --accept-source-agreements --accept-package-agreements
        $code = $LASTEXITCODE
        if ($code -eq $WingetOk -or $code -eq $WingetNoUpd) {
            Write-Ok "winget: $Id (exit $code)"
            return
        }
        Write-Warn2 "winget exit $code for $Id; retrying after 5s"
        Start-Sleep -Seconds 5
    }
    throw "winget install failed for $Id (last exit code $LASTEXITCODE)"
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
function Install-Python {
    Write-Step 'Python 3.11+'
    if (-not $Force) {
        $existing = Find-PythonExe
        if ($existing) {
            $ver = (& $existing --version 2>&1 | Out-String).Trim()
            Write-Ok "found $ver  ($existing)"
            $script:PythonExe = $existing
            return
        }
        Write-Skip "no real Python detected (App Execution Alias does not count)"
    }
    Invoke-WingetInstall -Id 'Python.Python.3.11'
    Update-SessionPath
    if ($script:DryRun) { return }

    $script:PythonExe = Find-PythonExe
    if (-not $script:PythonExe) {
        throw @"
Python install completed but no usable python.exe was found.
This usually means the Microsoft Store App Execution Alias for
'python' is shadowing the real interpreter. Open
  Settings -> Apps -> Advanced app settings -> App execution aliases
and turn OFF 'python.exe' and 'python3.exe', then re-run this script.
"@
    }
    Write-Ok ("python: " + (& $script:PythonExe --version 2>&1 | Out-String).Trim() + "  ($script:PythonExe)")
}

function Install-Ffmpeg {
    Write-Step 'ffmpeg (MP3 decoding)'
    if (-not $Force -and (Test-CommandAvailable 'ffmpeg')) {
        Write-Ok 'ffmpeg already on PATH'
        return
    }
    Invoke-WingetInstall -Id 'Gyan.FFmpeg'
    Update-SessionPath
    if (-not $script:DryRun) {
        if (Test-CommandAvailable 'ffmpeg') { Write-Ok 'ffmpeg installed' }
        else { Write-Warn2 'ffmpeg not on PATH yet (a new shell may be required)' }
    }
}

function Install-VBCable {
    <#
        Returns $true if VB-Cable was just installed (=> reboot needed).
        Returns $false if it was already there.
    #>
    Write-Step 'VB-Audio Virtual Cable'
    if (-not $Force -and (Test-VBCableInstalled)) {
        Write-Ok 'VB-Cable driver already present'
        return $false
    }

    Invoke-Action "create download dir $DownloadDir" {
        New-Item -ItemType Directory -Path $DownloadDir -Force | Out-Null
    }

    if ($Force -or -not (Test-Path $VBCableZip)) {
        Write-Step "downloading $VBCableUrl"
        Invoke-Action "Invoke-WebRequest $VBCableUrl -> $VBCableZip" {
            # Force TLS 1.2 (Windows PowerShell 5.1 defaults can fail
            # against modern endpoints) and retry transient failures.
            try {
                [Net.ServicePointManager]::SecurityProtocol =
                    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            } catch { $null = $_ }
            $attempts = 0
            $maxAttempts = 3
            while ($true) {
                $attempts++
                try {
                    Invoke-WebRequest -Uri $VBCableUrl -OutFile $VBCableZip -UseBasicParsing -TimeoutSec 90
                    break
                } catch {
                    if ($attempts -ge $maxAttempts) { throw }
                    Write-Warn2 "download failed (attempt $attempts/$maxAttempts): $_  - retrying in 5s"
                    Start-Sleep -Seconds 5
                }
            }
            Unblock-File -Path $VBCableZip -ErrorAction SilentlyContinue
        }
    } else {
        Write-Skip "already downloaded: $VBCableZip"
    }

    Invoke-Action "extract $VBCableZip -> $VBCableDir" {
        if (Test-Path $VBCableDir) { Remove-Item $VBCableDir -Recurse -Force }
        Expand-Archive -Path $VBCableZip -DestinationPath $VBCableDir -Force
    }

    $setupExe = Join-Path $VBCableDir 'VBCABLE_Setup_x64.exe'
    if (-not $script:DryRun -and -not (Test-Path $setupExe)) {
        throw "Could not find VBCABLE_Setup_x64.exe in extracted archive at $VBCableDir"
    }

    # The VB-Cable installer is a custom (NSIS-based) executable. Tested
    # silent flags across Driver Pack 43..45:
    #   -i  install
    #   -h  hidden (no UI)
    # Some older variants honour /S as a generic NSIS silent flag.
    $argSets = @(
        @('-i','-h'),
        @('/S')
    )

    $installed = $false
    foreach ($a in $argSets) {
        Write-Step "running VB-Cable installer: $($a -join ' ')"
        if ($script:DryRun) {
            Write-Dry "would run: $setupExe $($a -join ' ')"
            $installed = $true
            break
        }
        $proc = Start-Process -FilePath $setupExe -ArgumentList $a -Wait -PassThru -ErrorAction SilentlyContinue
        if ($null -ne $proc -and $proc.ExitCode -eq 0) {
            $installed = $true
            break
        }
        Write-Warn2 "exit code $($proc.ExitCode); trying next argument set"
    }

    if (-not $installed) {
        throw "VB-Cable installer failed for every known argument combination."
    }

    Write-Ok 'VB-Cable installed (reboot required to load driver)'
    $script:RebootRequired = $true
    return $true
}

function Install-Obs {
    Write-Step 'OBS Studio (provides Virtual Camera DirectShow filter)'
    if (-not $Force -and (Test-Path $ObsExe)) {
        Write-Ok 'OBS Studio already installed'
    } else {
        Invoke-WingetInstall -Id 'OBSProject.OBSStudio'
        if (-not $script:DryRun -and -not (Test-Path $ObsExe)) {
            throw "OBS install completed but obs64.exe not found at $ObsExe"
        }
    }

    if (-not $Force -and (Test-ObsVirtualCamRegistered)) {
        Write-Ok 'OBS Virtual Camera DirectShow filter already registered'
        return
    }

    if (-not $script:DryRun -and -not (Test-Path $ObsFilter)) {
        Write-Warn2 "obs-virtualcam-module64.dll not found; trying first-launch self-registration"
        Invoke-Action "launch+kill OBS once for filter registration" {
            $p = Start-Process -FilePath $ObsExe `
                -ArgumentList '--minimize-to-tray','--disable-shutdown-check' -PassThru
            Start-Sleep -Seconds 8
            if (-not $p.HasExited) {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        }
        return
    }

    Write-Step "registering DirectShow filter via regsvr32"
    Invoke-Action "regsvr32 /s $ObsFilter" {
        & regsvr32.exe /s "$ObsFilter"
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            Write-Warn2 "regsvr32 returned $code; falling back to OBS first-launch"
            $p = Start-Process -FilePath $ObsExe `
                -ArgumentList '--minimize-to-tray','--disable-shutdown-check' -PassThru
            Start-Sleep -Seconds 8
            if (-not $p.HasExited) {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }

    if (-not $script:DryRun) {
        if (Test-ObsVirtualCamRegistered) { Write-Ok 'OBS Virtual Camera filter registered' }
        else { Write-Warn2 'OBS Virtual Camera filter not yet visible in registry; may need a reboot' }
    }
}

function Install-PythonDeps {
    if (-not $script:PythonExe) { $script:PythonExe = Find-PythonExe }
    if (-not $script:DryRun -and -not $script:PythonExe) {
        throw "No usable python.exe found - cannot create venv. (Disable the python App Execution Alias in Settings, then re-run.)"
    }
    $pythonExe = if ($script:PythonExe) { $script:PythonExe } else { 'python' }

    Write-Step "creating Python venv at $VenvPath  (using $pythonExe)"
    if (-not $Force -and (Test-Path $VenvPy)) {
        Write-Ok 'venv already exists'
    } else {
        Invoke-Action "create venv: $pythonExe -m venv $VenvPath" {
            if (Test-Path $VenvPath) { Remove-Item $VenvPath -Recurse -Force }
            & $pythonExe -m venv $VenvPath
            if ($LASTEXITCODE -ne 0) { throw "python -m venv failed (exit $LASTEXITCODE)" }
        }
    }

    if (-not $script:DryRun -and -not (Test-Path $VenvPy)) {
        throw "venv python not found at $VenvPy"
    }

    Invoke-Action "upgrade pip" {
        & $VenvPy -m pip install --quiet --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit $LASTEXITCODE)" }
    }

    $req = Join-Path $RepoRoot 'requirements.txt'
    Invoke-Action "pip install -r $req" {
        & $VenvPy -m pip install --quiet -r $req
        if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt failed (exit $LASTEXITCODE)" }
    }

    Invoke-Action "pip install -e $RepoRoot" {
        & $VenvPy -m pip install --quiet -e $RepoRoot
        if ($LASTEXITCODE -ne 0) { throw "pip install -e . failed (exit $LASTEXITCODE)" }
    }

    Write-Ok "Python environment ready: $VenvPath"
}

# ---------------------------------------------------------------------------
# Resume-after-reboot scheduling
# ---------------------------------------------------------------------------
function Register-ResumeTask {
    Write-Step "registering scheduled task '$ResumeTaskName' to resume after reboot"
    if ($script:DryRun) {
        Write-Dry "would create scheduled task '$ResumeTaskName' running this script with -ContinueAfterReboot at next user logon (highest privileges)"
        return
    }

    # ContinueAfterReboot phase only needs to: install deps + verify.
    # Run as the user who is logging in, with highest privileges.
    $runUser  = "$env:USERDOMAIN\$env:USERNAME"
    $argLine  = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -ContinueAfterReboot"
    $action   = New-ScheduledTaskAction   -Execute 'powershell.exe' -Argument $argLine
    $trigger  = New-ScheduledTaskTrigger  -AtLogOn -User $runUser
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                                              -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    $principal = New-ScheduledTaskPrincipal -UserId $runUser -RunLevel Highest -LogonType Interactive

    Register-ScheduledTask -TaskName $ResumeTaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Ok "scheduled task registered (will fire on next logon for $runUser)"
}

function Unregister-ResumeTask {
    if (Get-ScheduledTask -TaskName $ResumeTaskName -ErrorAction SilentlyContinue) {
        Write-Step "removing scheduled resume task"
        if (-not $script:DryRun) {
            Unregister-ScheduledTask -TaskName $ResumeTaskName -Confirm:$false
        }
        Write-Ok "resume task removed"
    }
}

# ---------------------------------------------------------------------------
# Verify (calls verify.ps1)
# ---------------------------------------------------------------------------
function Invoke-Verify {
    $verify = Join-Path $PSScriptRoot 'verify.ps1'
    if (-not (Test-Path $verify)) { return }
    Write-Step "running verify.ps1"
    if ($script:DryRun) {
        Write-Dry "would run: powershell -File $verify"
        return
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $verify
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "verify.ps1 exited with code $LASTEXITCODE - some checks failed (see above)"
    } else {
        Write-Ok "verify.ps1 reports all checks green"
    }
}

# ---------------------------------------------------------------------------
# Desktop + Start Menu shortcuts
# ---------------------------------------------------------------------------
function New-AppShortcuts {
    Write-Step 'creating Desktop + Start Menu shortcuts'

    $launcher = Join-Path $RepoRoot 'teams-simulator.cmd'
    $iconPath = Join-Path $RepoRoot 'assets\app.ico'

    if (-not (Test-Path $launcher)) {
        Write-Warn2 "launcher not found: $launcher (skipping shortcuts)"
        return
    }

    $iconArg = if (Test-Path $iconPath) { $iconPath } else { $null }

    $publicDesktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $userDesktop   = [Environment]::GetFolderPath('Desktop')
    $startMenuDir  = Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'Teams Simulator'

    $targets = @(
        (Join-Path $publicDesktop 'Teams Simulator.lnk'),
        (Join-Path $userDesktop   'Teams Simulator.lnk'),
        (Join-Path $startMenuDir  'Teams Simulator.lnk')
    )

    if ($script:DryRun) {
        foreach ($t in $targets) { Write-Dry "would create shortcut: $t -> $launcher" }
        return
    }

    if (-not (Test-Path $startMenuDir)) {
        New-Item -ItemType Directory -Path $startMenuDir -Force | Out-Null
    }

    $shell = New-Object -ComObject WScript.Shell
    foreach ($lnkPath in $targets) {
        try {
            $sc = $shell.CreateShortcut($lnkPath)
            $sc.TargetPath       = $launcher
            $sc.WorkingDirectory = $RepoRoot
            $sc.Description      = 'Teams Simulator - virtual mic + virtual camera for Microsoft Teams'
            $sc.WindowStyle      = 7  # minimized (the .cmd just spawns pythonw and exits)
            if ($iconArg) { $sc.IconLocation = $iconArg }
            $sc.Save()
            Write-Ok "shortcut: $lnkPath"
        } catch {
            Write-Warn2 "could not create $lnkPath  ($_)"
        }
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Teams Simulator - Headless Install" -ForegroundColor Magenta
Write-Host "===================================" -ForegroundColor Magenta
Write-Journal 'INFO' "log file: $LogFile" Gray
Write-Journal 'INFO' "mode: $(if($Auto){'Auto '}else{''})$(if($NoReboot){'NoReboot '}else{''})$(if($Force){'Force '}else{''})$(if($DryRun){'DryRun '}else{''})$(if($ContinueAfterReboot){'ContinueAfterReboot'}else{''})" Gray

Assert-Admin

if ($ContinueAfterReboot) {
    # Post-reboot phase: only deps + verify, then clean up.
    # Wrap everything so a failure does NOT slam the window shut before
    # the user can read what went wrong.
    Write-Step "post-reboot phase"
    $resumeError = $null
    try {
        Update-SessionPath
        Install-PythonDeps
        Invoke-Verify
        New-AppShortcuts
        Unregister-ResumeTask
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host " Setup complete." -ForegroundColor Green
        Write-Host " Launch the app via the 'Teams Simulator' icon on your Desktop" -ForegroundColor Green
        Write-Host " (or in the Start Menu)." -ForegroundColor Green
        Write-Host ""
        Write-Host " In Teams pick:" -ForegroundColor Green
        Write-Host "   Microphone : 'CABLE Output (VB-Audio Virtual Cable)'" -ForegroundColor Gray
        Write-Host "   Camera     : 'OBS Virtual Camera'" -ForegroundColor Gray
        Write-Host "============================================================" -ForegroundColor Green
    } catch {
        $resumeError = $_
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host " POST-REBOOT SETUP FAILED" -ForegroundColor Red
        Write-Host "============================================================" -ForegroundColor Red
        Write-Host ""
        Write-Host "Error: $resumeError" -ForegroundColor Yellow
        if ($_.ScriptStackTrace) {
            Write-Host ""
            Write-Host "Stack trace:" -ForegroundColor DarkGray
            Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
        }
        Write-Host ""
        Write-Host "Full log: $LogFile" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Recovery steps:" -ForegroundColor Yellow
        Write-Host "  1. cd C:\teams-simulator" -ForegroundColor Gray
        Write-Host "  2. .\setup\verify.ps1                       (see exactly what is missing)" -ForegroundColor Gray
        Write-Host "  3. Get-Content '$LogFile' | more            (read the full setup log)" -ForegroundColor Gray
        Write-Host "  4. .\setup\install.ps1 -Force               (re-run the setup; idempotent)" -ForegroundColor Gray
        Write-Host ""
    } finally {
        Write-Host ""
        Write-Host "Press Enter to close this window..." -ForegroundColor Cyan
        try { [void](Read-Host) } catch { Start-Sleep -Seconds 30 }
    }
    if ($resumeError) { exit 1 }
    return
}

Install-Python
Install-Ffmpeg
[void](Install-VBCable)
Install-Obs

if ($script:RebootRequired) {
    # We schedule deps + verify to run after the reboot if -Auto was
    # requested. Without -Auto the user re-runs install.ps1 themselves.
    if ($Auto) {
        Register-ResumeTask
    }
} else {
    Install-PythonDeps
    Invoke-Verify
    New-AppShortcuts
}

Write-Host ""
Write-Host "Setup phase done." -ForegroundColor Magenta
Write-Host "Next steps:" -ForegroundColor Magenta
Write-Host "  1. In Teams set:" -ForegroundColor Gray
Write-Host "       Microphone : 'CABLE Output (VB-Audio Virtual Cable)'" -ForegroundColor Gray
Write-Host "       Camera     : 'OBS Virtual Camera'" -ForegroundColor Gray
Write-Host "  2. Launch the simulator from the 'Teams Simulator' Desktop icon" -ForegroundColor Gray
Write-Host "     (or from the Start Menu)." -ForegroundColor Gray
Write-Host ""

if ($script:RebootRequired) {
    if ($NoReboot) {
        Write-Warn2 "VB-Cable was just installed - reboot required, but -NoReboot was passed."
        Write-Warn2 "Reboot manually, then re-run: .\setup\install.ps1"
        exit 2
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host " VB-Audio Virtual Cable was just installed (kernel driver)." -ForegroundColor Yellow
    Write-Host " A reboot is REQUIRED before Teams will see the microphone." -ForegroundColor Yellow
    Write-Host " A scheduled task will resume setup automatically after login." -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow

    if ($Auto) {
        # In -Auto mode default to Y so just hitting Enter reboots.
        # Skip the prompt entirely under -DryRun so dryrun.ps1 doesn't hang.
        if ($script:DryRun) {
            Write-Dry "would prompt 'Reboot now? [Y/n]' (auto-default Y)"
            $reboot = $true
        } else {
            $resp = Read-Host "Reboot now? [Y/n]"
            $reboot = ($resp -eq '' -or $resp -match '^[yY]')
        }
    } else {
        # In interactive mode default to N to preserve the prior behaviour.
        $resp = Read-Host "Reboot now? [y/N]"
        $reboot = ($resp -match '^[yY]')
    }

    if ($reboot) {
        if ($script:DryRun) {
            Write-Dry "would call Restart-Computer -Force"
            return
        }
        Write-Warn2 "Rebooting in 5 seconds... Setup will continue automatically after you log back in."
        Start-Sleep -Seconds 5
        Restart-Computer -Force
        return
    }

    Write-Warn2 "Reboot skipped. Teams will NOT see the microphone until you reboot."
    Write-Warn2 "When you're ready: run  shutdown /r /t 0  -- the resume task is already registered."
    exit 2
}

exit 0
