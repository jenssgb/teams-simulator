#Requires -Version 5.1
<#
.SYNOPSIS
    Shared helper: where do all Teams Simulator logs go?

.DESCRIPTION
    Every .ps1 in this repo dot-sources this file and uses:

        $LogRoot = Get-LogRoot
        Start-LogTranscript -ScriptName 'install'

    so that the user always finds every log under ONE folder, even if
    the terminal window slams shut on a crash.

    Resolution order for the log root:
      1. $env:TEAMS_SIMULATOR_LOG_DIR  (escape hatch for power users / CI)
      2. <UserDesktop>\TeamsSimulatorLogs       (preferred)
      3. <PublicDesktop>\TeamsSimulatorLogs     (per-machine fallback)
      4. <RepoRoot>\setup\_logs                 (final fallback)
#>

function Get-LogRoot {
    [CmdletBinding()]
    param(
        # Optional: where the calling script lives, used to compute the
        # repo-root fallback. Pass $PSScriptRoot from the caller.
        [string]$CallerScriptRoot
    )

    # 1. explicit override
    if ($env:TEAMS_SIMULATOR_LOG_DIR) {
        $candidate = $env:TEAMS_SIMULATOR_LOG_DIR
        if (Test-LogDirWritable $candidate) { return $candidate }
    }

    # 2. user desktop
    try {
        $userDesktop = [Environment]::GetFolderPath('Desktop')
        if ($userDesktop) {
            $candidate = Join-Path $userDesktop 'TeamsSimulatorLogs'
            if (Test-LogDirWritable $candidate) { return $candidate }
        }
    } catch { }

    # 3. public desktop (visible to every user on the box)
    try {
        $publicDesktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
        if ($publicDesktop) {
            $candidate = Join-Path $publicDesktop 'TeamsSimulatorLogs'
            if (Test-LogDirWritable $candidate) { return $candidate }
        }
    } catch { }

    # 4. repo-root fallback (always works because we just wrote here on clone)
    if ($CallerScriptRoot) {
        $repoFallback = Join-Path $CallerScriptRoot '_logs'
        if (Test-LogDirWritable $repoFallback) { return $repoFallback }
    }

    # absolute last resort: temp
    $tmp = Join-Path $env:TEMP 'TeamsSimulatorLogs'
    [void](New-Item -ItemType Directory -Path $tmp -Force -ErrorAction SilentlyContinue)
    return $tmp
}

function Test-LogDirWritable {
    param([Parameter(Mandatory)][string]$Path)
    try {
        if (-not (Test-Path $Path)) {
            New-Item -ItemType Directory -Path $Path -Force -ErrorAction Stop | Out-Null
        }
        $probe = Join-Path $Path ('.write-probe-{0}' -f [Guid]::NewGuid())
        Set-Content -Path $probe -Value 'ok' -ErrorAction Stop
        Remove-Item $probe -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

function Start-LogTranscript {
    <#
        Begins a PowerShell transcript that captures EVERYTHING the
        script prints (Write-Host, Write-Output, Write-Error, native
        process stderr, the lot). The transcript file is returned.

        Safe to call even if a transcript is already running - we stop
        it first.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ScriptName,
        [string]$LogRoot
    )

    if (-not $LogRoot) { $LogRoot = Get-LogRoot -CallerScriptRoot $PSScriptRoot }
    if (-not (Test-Path $LogRoot)) {
        New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
    }

    $stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
    $logFile = Join-Path $LogRoot ("{0}-{1}.log" -f $ScriptName, $stamp)

    # Stop any inherited transcript before starting ours.
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch { }

    try {
        Start-Transcript -Path $logFile -Append -Force -ErrorAction Stop | Out-Null
        Write-Host ("[log] transcript -> {0}" -f $logFile) -ForegroundColor DarkGray
    } catch {
        # Transcript can fail (e.g. host doesn't support it) - never fatal.
        Write-Host ("[log] transcript could not start: {0}" -f $_.Exception.Message) -ForegroundColor DarkYellow
    }

    return $logFile
}

function Stop-LogTranscript {
    [CmdletBinding()]
    param()
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch { }
}
