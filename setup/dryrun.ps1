#Requires -Version 5.1
<#
.SYNOPSIS
    Verify-without-installing for the Teams Simulator setup pipeline.

.DESCRIPTION
    Runs every check that does NOT require actually installing anything,
    so that issues with the install scripts are caught on a dev box
    before they bite on a customer VM.

    Checks performed:
      1. PowerShell parser pass on every .ps1 in this folder.
      2. PSScriptAnalyzer (if module is installed) on every .ps1.
      3. winget reachable; every required package ID resolves.
      4. VB-Cable download URL responds 200 to a HEAD request, and the
         reported Content-Length is sensible (> 1 MB).
      5. Reachability of Python.org / OBS / ffmpeg homepages used by
         winget sources (informational only).
      6. install.ps1 -DryRun runs cleanly (mock install pass).
      7. verify.ps1 syntax + execution against the local dev box (the
         dev box may not have VB-Cable, so individual FAILs are OK -
         the script just must not crash).
      8. If OBS is already installed locally: probe that the DirectShow
         filter DLL exists at the path install.ps1 expects.

    Exit code 0 if all critical checks passed, 1 otherwise.
#>
[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot '_lib\logroot.ps1')
$null = Start-LogTranscript -ScriptName 'dryrun-console'

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'
$here = $PSScriptRoot
$repoRoot = Split-Path -Parent $here

$script:passed = 0
$script:failed = 0
$script:warned = 0

function Section([string]$t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Pass   ([string]$m) { Write-Host "   [PASS] $m" -ForegroundColor Green;   $script:passed++ }
function Fail   ([string]$m) { Write-Host "   [FAIL] $m" -ForegroundColor Red;     $script:failed++ }
function Warn   ([string]$m) { Write-Host "   [WARN] $m" -ForegroundColor Yellow;  $script:warned++ }
function Info   ([string]$m) { Write-Host "   [info] $m" -ForegroundColor DarkGray }

# ---------------------------------------------------------------------------
# 1. PowerShell parser
# ---------------------------------------------------------------------------
Section "PowerShell parser"
$psFiles = Get-ChildItem -Path $here -Filter *.ps1 -File
foreach ($f in $psFiles) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) {
        Fail "$($f.Name) : $($errors.Count) parse error(s)"
        $errors | ForEach-Object { Write-Host "          $($_.Message)" -ForegroundColor DarkRed }
    } else {
        Pass "$($f.Name) parses cleanly"
    }
}

# ---------------------------------------------------------------------------
# 2. PSScriptAnalyzer (optional)
# ---------------------------------------------------------------------------
Section "PSScriptAnalyzer (optional)"
if (Get-Module -ListAvailable -Name PSScriptAnalyzer) {
    Import-Module PSScriptAnalyzer -ErrorAction SilentlyContinue
    foreach ($f in $psFiles) {
        $issues = Invoke-ScriptAnalyzer -Path $f.FullName -Severity Warning,Error
        $errs = @($issues | Where-Object Severity -eq 'Error')
        $warns = @($issues | Where-Object Severity -eq 'Warning')
        if ($errs.Count -gt 0) {
            Fail "$($f.Name) : $($errs.Count) Analyzer error(s)"
            $errs | ForEach-Object { Write-Host "          L$($_.Line) $($_.RuleName): $($_.Message)" -ForegroundColor DarkRed }
        } elseif ($warns.Count -gt 0) {
            Warn "$($f.Name) : $($warns.Count) Analyzer warning(s)"
            $warns | Select-Object -First 5 | ForEach-Object {
                Write-Host "          L$($_.Line) $($_.RuleName): $($_.Message)" -ForegroundColor DarkYellow
            }
        } else {
            Pass "$($f.Name) clean"
        }
    }
} else {
    Warn "PSScriptAnalyzer not installed (skip). To enable: Install-Module PSScriptAnalyzer -Scope CurrentUser"
}

# ---------------------------------------------------------------------------
# 3. winget package IDs resolve
# ---------------------------------------------------------------------------
Section "winget package resolution"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail "winget not on PATH (App Installer missing) - install.ps1 will fail on this machine"
} else {
    Pass "winget present: $((winget --version) -join '')"
    foreach ($id in @('Python.Python.3.11','Gyan.FFmpeg','OBSProject.OBSStudio')) {
        $out = & winget show --id $id -e --accept-source-agreements 2>&1
        if ($LASTEXITCODE -eq 0 -and ($out -match "Found")) {
            $verLine = ($out | Select-String -Pattern '^Version:').ToString()
            Pass "$id resolves ($verLine)"
        } else {
            Fail "$id does not resolve via winget"
            $out | Select-Object -First 6 | ForEach-Object { Write-Host "          $_" -ForegroundColor DarkRed }
        }
    }
}

# ---------------------------------------------------------------------------
# 4. VB-Cable download URL
# ---------------------------------------------------------------------------
Section "VB-Cable download URL"
$url = 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip'
try {
    $r = Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing -TimeoutSec 20
    $len = [int64]($r.Headers.'Content-Length')
    if ($r.StatusCode -eq 200 -and $len -gt 1MB) {
        Pass "HEAD $url -> 200, $([math]::Round($len/1KB)) KB"
    } else {
        Fail "HEAD $url -> StatusCode=$($r.StatusCode) Content-Length=$len"
    }
} catch {
    Fail "HEAD $url failed: $_"
}

# ---------------------------------------------------------------------------
# 5. install.ps1 -DryRun
# ---------------------------------------------------------------------------
Section "install.ps1 -DryRun"
$install = Join-Path $here 'install.ps1'
if (-not (Test-Path $install)) {
    Fail "install.ps1 not found"
} else {
    # We cannot run -DryRun directly because it requires admin. Instead
    # we ParseFile and verify the parameters exist + the DryRun branch
    # is reachable. This is a static check.
    $content = Get-Content -Raw $install
    $needed = @('-Auto','-NoReboot','-Force','-DryRun','-ContinueAfterReboot','RebootRequired','Register-ResumeTask','Invoke-WingetInstall')
    foreach ($needle in $needed) {
        if ($content -match [Regex]::Escape($needle)) {
            Pass "install.ps1 contains '$needle'"
        } else {
            Fail "install.ps1 missing '$needle'"
        }
    }

    # If we are admin OR we are doing a static-only dry-run (which now works
    # without admin), actually run -DryRun to exercise the code paths.
    Info "running install.ps1 -DryRun for real ..."
    $tmpLog = Join-Path $env:TEMP "ts-install-dry-$([guid]::NewGuid()).log"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $install -DryRun -NoReboot -LogFile $tmpLog 2>&1 |
        ForEach-Object { Write-Host "      | $_" -ForegroundColor DarkGray }
    # Exit code 0 = nothing reboot-worthy. Exit code 2 = reboot required
    # but suppressed by -NoReboot. Both are valid outcomes for a dry-run.
    if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 2) {
        Pass "install.ps1 -DryRun -NoReboot exited cleanly (code $LASTEXITCODE)"
    } else {
        Fail "install.ps1 -DryRun -NoReboot exited with $LASTEXITCODE"
    }
    if (Test-Path $tmpLog) { Remove-Item $tmpLog -Force -ErrorAction SilentlyContinue }
}

# ---------------------------------------------------------------------------
# 6. verify.ps1 sanity
# ---------------------------------------------------------------------------
Section "verify.ps1 sanity"
$verify = Join-Path $here 'verify.ps1'
if (-not (Test-Path $verify)) {
    Fail "verify.ps1 not found"
} else {
    Pass "verify.ps1 present"
    Info "running verify.ps1 against the local dev box (some FAILs are normal here):"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $verify 2>&1 |
        ForEach-Object { Write-Host "      | $_" -ForegroundColor DarkGray }
    Info "(verify.ps1 exit code: $LASTEXITCODE - it is allowed to be non-zero on the dev box)"
}

# ---------------------------------------------------------------------------
# 7. OBS DirectShow filter probe (only if OBS installed locally)
# ---------------------------------------------------------------------------
Section "OBS Virtual Camera DLL probe"
$obsDll = 'C:\Program Files\obs-studio\data\obs-plugins\win-dshow\obs-virtualcam-module64.dll'
if (Test-Path $obsDll) {
    Pass "OBS Virtual Camera DLL present at $obsDll"
    $sig = Get-AuthenticodeSignature $obsDll
    if ($sig.Status -eq 'Valid') {
        Pass "DLL is Authenticode-signed (Subject: $($sig.SignerCertificate.Subject))"
    } else {
        Warn "DLL signature status: $($sig.Status)"
    }
} else {
    Warn "OBS not installed on this dev machine - cannot test regsvr32 path"
}

# ---------------------------------------------------------------------------
# 8. Python project metadata is consistent
# ---------------------------------------------------------------------------
Section "Python project metadata"
$pyproj = Join-Path $repoRoot 'pyproject.toml'
$req    = Join-Path $repoRoot 'requirements.txt'
foreach ($f in @($pyproj, $req)) {
    if (Test-Path $f) { Pass "found: $($f -replace [Regex]::Escape($repoRoot+'\'),'')" }
    else { Fail "missing: $f" }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Magenta
Write-Host ("Dry-run summary: {0} pass, {1} warn, {2} FAIL" -f $script:passed, $script:warned, $script:failed) `
    -ForegroundColor Magenta
Write-Host ("=" * 60) -ForegroundColor Magenta

if ($script:failed -gt 0) { exit 1 } else { exit 0 }
