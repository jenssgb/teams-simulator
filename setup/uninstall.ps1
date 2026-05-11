#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Remove the Teams Simulator venv and print manual uninstall hints.
#>
[CmdletBinding()]
param()

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $RepoRoot '.venv'
$Downloads = Join-Path $PSScriptRoot '_downloads'

if (Test-Path $VenvPath)  { Remove-Item $VenvPath  -Recurse -Force; Write-Host "Removed $VenvPath" -ForegroundColor Green }
if (Test-Path $Downloads) { Remove-Item $Downloads -Recurse -Force; Write-Host "Removed $Downloads" -ForegroundColor Green }

Write-Host ""
Write-Host "Manual uninstall steps (Apps & Features):" -ForegroundColor Yellow
Write-Host "  - VB-Audio Virtual Cable" -ForegroundColor Gray
Write-Host "  - OBS Studio" -ForegroundColor Gray
Write-Host "  - ffmpeg (Gyan.FFmpeg) - winget uninstall Gyan.FFmpeg" -ForegroundColor Gray
Write-Host "  - Python 3.11 - winget uninstall Python.Python.3.11" -ForegroundColor Gray
