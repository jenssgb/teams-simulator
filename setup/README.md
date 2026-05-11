# Setup scripts

These PowerShell scripts prepare a fresh Windows 10/11 VM to run the
Teams Simulator. They are **idempotent** — re-running them after a
partial install just fills in the gaps.

## TL;DR — fully unattended on a fresh VM

```powershell
# Elevated PowerShell on the target VM, one paste:
powershell -ExecutionPolicy Bypass -File .\setup\install.ps1 -Auto
```

`-Auto` registers a one-shot scheduled task and auto-reboots after
installing VB-Cable; the task fires on the next logon, finishes the
install, runs `verify.ps1`, and removes itself. Walk away.

## install.ps1

The headless installer. Installs:

| Component | Source | Why |
| --- | --- | --- |
| Python 3.11 | winget `Python.Python.3.11` | Runtime |
| ffmpeg | winget `Gyan.FFmpeg` | MP3 → PCM decoding for the audio loader |
| VB-Audio Virtual Cable | direct download from vb-audio.com (donationware) | Virtual microphone (`CABLE Input` / `CABLE Output`) |
| OBS Studio | winget `OBSProject.OBSStudio` | Provides the OBS Virtual Camera DirectShow filter |
| Python venv + deps | local | Project dependencies (`.venv` inside the repo) |

### Flags

| Flag | Meaning |
| --- | --- |
| `-Auto` | Fully unattended: no prompts, auto-reboot, scheduled-task resume after reboot. |
| `-NoReboot` | Never reboot. Exit code `2` if a reboot would be required. |
| `-Force` | Reinstall everything even if already present. |
| `-DryRun` | Log every action, modify nothing. Doesn't even need admin. |
| `-ContinueAfterReboot` | **Internal**: set by the resume scheduled task. |
| `-LogFile <path>` | Override default log location (`setup\_logs\install-<ts>.log`). |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Done — Teams will see the devices after the next reboot (if any was required and applied). |
| `1` | An installation step failed (see log). |
| `2` | Install OK, but a reboot is required and `-NoReboot` was passed. Reboot manually then re-run. |

### Reboot model

VB-Cable installs a kernel audio driver. Until you reboot, Teams will
not see the `CABLE Output` microphone.

* Without `-Auto`: the script prints the reboot reminder. You re-run
  `install.ps1` after the reboot — second run is a no-op for everything
  already installed and finishes with `verify.ps1`.
* With `-Auto`: a scheduled task `TeamsSimulatorSetupResume` is
  registered for the current user with `RunLevel Highest`. The script
  then calls `Restart-Computer -Force`. After the user logs back in,
  the task wakes up, runs `install.ps1 -ContinueAfterReboot`, finishes
  the deps, runs `verify.ps1`, and unregisters itself.

## verify.ps1

End-to-end sanity check on the VM:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup\verify.ps1
```

Verifies python on PATH, ffmpeg on PATH, the project venv exists, all
Python dependencies import, the `teams_simulator` package is importable,
both `CABLE Input` / `CABLE Output` PortAudio devices are visible (so
Teams will see the mic), and the OBS Virtual Camera DirectShow filter
is registered. Prints exact device names. Exit 0 = ready.

## dryrun.ps1

Run this on your **dev** machine before shipping a change to the
installer to a customer VM. It does not install anything; it:

1. Parses every `.ps1` in this folder for syntax errors.
2. Runs PSScriptAnalyzer if installed (`Install-Module PSScriptAnalyzer -Scope CurrentUser`).
3. Asks `winget show` to resolve every package id we depend on.
4. HEAD-tests the VB-Cable download URL (must return 200, > 1 MB).
5. Runs `install.ps1 -DryRun -NoReboot` — this exercises every code
   path including the VB-Cable install branch, but writes no files and
   spawns no installers (it only logs what it *would* do).
6. Runs `verify.ps1` against the local box (FAILs are expected for
   anything not installed locally — what matters is that the script
   doesn't crash).
7. Probes the OBS DirectShow DLL signature if OBS is installed locally.
8. Confirms `pyproject.toml` and `requirements.txt` exist.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup\dryrun.ps1
```

Exits 0 on success, 1 on failure.

## bootstrap.ps1

One-paste installer for the truly lazy operator. Designed to be served
via a one-liner like:

```powershell
iex (irm 'https://raw.githubusercontent.com/jenssgb/teams-simulator/main/setup/bootstrap.ps1')
```

It installs git via winget if needed, clones the repo to
`C:\teams-simulator`, and runs `install.ps1 -Auto`. Override
`-RepoUrl`, `-TargetDir`, or `-InstallArgs` if you fork or want
interactive install.

## uninstall.ps1

Removes the venv and prints manual uninstall instructions for VB-Cable
and OBS (they have their own uninstallers in *Add or Remove Programs*).

## Licence notes

* **VB-Audio Virtual Cable** is donationware — free to use, donations
  encouraged at <https://vb-audio.com/Cable/>.
* **OBS Studio** is GPLv2.
* **ffmpeg** (Gyan.FFmpeg build) is LGPLv2.1 by default.
