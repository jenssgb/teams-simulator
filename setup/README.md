# Setup scripts

These PowerShell scripts prepare a fresh Windows 10/11 VM to run the Teams
Simulator. They are idempotent: re-running them after a partial install
just fills in the gaps.

## install.ps1

Run as **Administrator**:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup\install.ps1
```

It installs:

| Component | Source | Why |
| --- | --- | --- |
| Python 3.11 | winget `Python.Python.3.11` | Runtime |
| ffmpeg | winget `Gyan.FFmpeg` | MP3 → PCM decoding for the audio loader |
| VB-Audio Virtual Cable | direct download from vb-audio.com (Donationware) | Provides the virtual microphone (`CABLE Input` / `CABLE Output`) |
| OBS Studio | winget `OBSProject.OBSStudio` | Provides the OBS Virtual Camera DirectShow filter |
| Python venv + deps | local | Project dependencies |

After installing VB-Cable a **reboot is recommended**. The script asks at
the end (`-SkipReboot` to skip the prompt for unattended runs).

### Flags

* `-SkipReboot` — never prompt for reboot.
* `-Force` — reinstall everything even if already present.

## verify.ps1

Sanity-checks the installation:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup\verify.ps1
```

Reports OK / FAIL for each requirement.

## uninstall.ps1

Removes the venv and prints manual uninstall instructions for VB-Cable
and OBS (they have their own uninstallers in `Add or Remove Programs`).

## Licence notes

* **VB-Audio Virtual Cable** is donationware — free to use, donations
  encouraged at <https://vb-audio.com/Cable/>.
* **OBS Studio** is GPLv2.
* **ffmpeg** (Gyan.FFmpeg build) is LGPLv2.1 by default.
