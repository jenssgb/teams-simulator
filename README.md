# Teams Simulator

Stream a prepared **audio file** and a **static avatar image** (with an
animated audio-level overlay) into Microsoft Teams on a Windows VM, as if
they came from a real microphone and webcam.

> 🎙️📷 Use it to test Teams meeting features (recording, Copilot,
> compliance bots, transcription, …) without needing a real participant.

---

## How it works

```
your_audio.wav  ──►  sounddevice    ──►  "CABLE Input"   ──►  Teams mic
                                          (VB-Audio Virtual Cable)

your_avatar.png ──►  pyvirtualcam   ──►  "OBS Virtual Camera"  ──►  Teams cam
   + waveform                              (DirectShow filter)
   overlay
```

Two virtual Windows devices do the heavy lifting:

| Device                 | Provided by                  | What it is                                                                  |
| ---------------------- | ---------------------------- | --------------------------------------------------------------------------- |
| `CABLE Input/Output`   | VB-Audio Virtual Cable       | A loopback audio driver. Anything we play to `CABLE Input` is captured by `CABLE Output`, which Teams can pick as a microphone. |
| `OBS Virtual Camera`   | OBS Studio's DirectShow filter | A virtual webcam. We push BGR frames via `pyvirtualcam`; OBS itself doesn't even need to be running. |

The simulator coordinates both sides on a single timeline: it streams
audio frame-accurately into `CABLE Input`, samples the RMS level, and
draws an equalizer-style waveform overlay onto the avatar image so Teams
participants see "the avatar is talking now".

## Quickstart (fresh Windows 10/11 VM)

```powershell
# 1. Get the code
git clone <repo-url> C:\teams-simulator
cd C:\teams-simulator

# 2. Bootstrap the VM (elevated PowerShell)

# Option A - fully unattended (auto-reboot, scheduled task continues setup):
powershell -ExecutionPolicy Bypass -File .\setup\install.ps1 -Auto

# Option B - interactive:
powershell -ExecutionPolicy Bypass -File .\setup\install.ps1
#   -> Installs Python 3.11 (winget) + ffmpeg + VB-Audio Virtual Cable
#      + OBS Studio (winget, registers DirectShow filter) + .venv + deps
#   -> Asks at the end whether to reboot (VB-Cable is a kernel driver).

# Optional - dry run (no admin needed, modifies nothing, prints the plan):
powershell -ExecutionPolicy Bypass -File .\setup\install.ps1 -DryRun

# 3. After reboot: verify the wiring
powershell -ExecutionPolicy Bypass -File .\setup\verify.ps1

# 4. In Teams (or Teams Web in Edge):
#    Settings -> Devices ->
#       Microphone : "CABLE Output (VB-Audio Virtual Cable)"
#       Camera     : "OBS Virtual Camera"

# 5. Launch the GUI
.\.venv\Scripts\python.exe -m teams_simulator
```

> **One-paste lazy mode** on a fresh Windows 10/11 VM, elevated PowerShell:
> ```powershell
> iex (irm 'https://raw.githubusercontent.com/jenssgb/teams-simulator/main/setup/bootstrap.ps1')
> ```
> clones the repo to `C:\teams-simulator` and runs `install.ps1 -Auto`.
>

## Using the simulator

### GUI

`python -m teams_simulator` opens a small Tkinter window:

* **Virtual devices** panel — green/red status for the mic and camera.
  Hit **Re-check** after running `install.ps1`.
* **Inputs** — pick any `.wav`, `.flac`, `.ogg`, `.aiff` (or `.mp3` if
  ffmpeg is installed) and any `.png`/`.jpg`/`.bmp`. The bundled
  `samples/demo_audio.wav` and `samples/demo_avatar.png` are pre-filled.
* **Options** — *Loop audio* (default on) and *FPS* spinbox.
* **▶ Start / ⏸ Pause / ⏹ Stop** — start streams audio + video atomically.
* **Live audio level** progress bar — the same RMS that drives the
  in-camera waveform.
* **Log** — INFO/ERROR messages from the controller.

### CLI / scripted

```powershell
.\.venv\Scripts\teams-sim.exe `
    --audio  samples\demo_audio.wav `
    --image  samples\demo_avatar.png `
    --loop `
    --fps 30 `
    --resolution 1280x720
```

`teams-sim --help` lists all flags. `--duration N` auto-stops after N
seconds (handy for CI).

### Programmatic

```python
from teams_simulator.sync import SimulatorController

c = SimulatorController.from_paths("meeting.wav", "avatar.png", loop=True)
c.start()
# ... do work ...
c.stop()
```

## Repository layout

```
teams-simulator/
├── README.md                    <- this file
├── pyproject.toml               <- packaging + entry points
├── requirements.txt             <- pinned runtime deps
├── setup/                       <- VM bootstrap PowerShell scripts
│   ├── install.ps1              <- headless installer (-Auto / -DryRun / -NoReboot / -Force)
│   ├── verify.ps1               <- end-to-end self-test (devices, deps)
│   ├── dryrun.ps1               <- run on the dev box; verifies install.ps1 without installing
│   ├── bootstrap.ps1            <- one-paste clone+install (irm | iex friendly)
│   ├── uninstall.ps1
│   └── README.md
├── samples/
│   ├── demo_audio.wav           <- 6 s synthesised speech-like signal
│   ├── demo_avatar.png          <- 1280x720 placeholder portrait
│   └── README.md
├── scripts/
│   └── generate_samples.py      <- regenerates the bundled samples
├── src/teams_simulator/
│   ├── __main__.py              <- python -m teams_simulator -> GUI
│   ├── ui.py                    <- Tkinter window
│   ├── cli.py                   <- argparse CLI
│   ├── sync.py                  <- SimulatorController (the public API)
│   ├── devices.py               <- VB-Cable / OBS VCam discovery
│   ├── config.py                <- defaults
│   ├── audio/
│   │   ├── loader.py            <- WAV/FLAC/MP3 -> normalised numpy
│   │   └── player.py            <- sounddevice OutputStream + RMS meter
│   └── video/
│       ├── frame_source.py      <- image -> letterboxed BGR frame
│       ├── waveform.py          <- equalizer-bar overlay animator
│       └── streamer.py          <- pyvirtualcam loop -> OBS VCam
└── tests/                       <- pytest, no real devices required
```

## Requirements

| Component | Why                                                                |
| --- | --- |
| Windows 10 / 11 (host or VM)        | Required by VB-Audio Virtual Cable and OBS Virtual Camera. |
| Python 3.10–3.13 (64-bit)           | Runtime.                                                  |
| Administrator rights (for setup)    | VB-Cable installs a kernel-mode audio driver.             |
| Internet access (for setup only)    | To download installers / Python packages.                 |
| ~1 GB free disk                     | Python + OBS + venv.                                      |
| ffmpeg                              | Optional; only required to load MP3.                      |

GPU is **not** required — both virtual devices are pure user-space
software.

## VM compatibility

| Hypervisor / cloud           | Verdict | Notes |
| --- | --- | --- |
| **VMware Workstation / Player** | ✅ Best | Audio + 3D acceleration just work. |
| **VirtualBox 7.x**             | ✅ Good | Slightly slower; install Guest Additions. |
| **Hyper-V (Enhanced Session)** | ⚠️ OK | Standard session has no audio; enable Enhanced Session Mode. |
| **Azure Windows IaaS VM**      | ✅ Recommended for shared demos | Use D4s_v3 or larger. **Do not** use Azure Virtual Desktop (AVD) — it redirects Teams media to the local client. |

## Troubleshooting

<details>
<summary><strong>Teams shows "Microphone not found"</strong></summary>

Did you reboot after `install.ps1`? VB-Cable is a kernel-mode driver and
only appears after a reboot. Run `setup\verify.ps1` — it will tell you
which device is missing.
</details>

<details>
<summary><strong>"OBS Virtual Camera not available"</strong></summary>

The DirectShow filter is registered on first launch of OBS. The setup
script does this automatically with `regsvr32`, but if it failed, just
launch `obs64.exe` once manually and close it.
</details>

<details>
<summary><strong>MP3 file fails to load</strong></summary>

Install ffmpeg: `winget install Gyan.FFmpeg`, then open a fresh shell so
PATH is refreshed. WAV / FLAC / OGG don't need ffmpeg.
</details>

<details>
<summary><strong>Audio is choppy / underruns</strong></summary>

Increase the block size in `src/teams_simulator/config.py`
(`DEFAULT_BLOCK_SIZE`) from 960 to e.g. 1920, or lower the video FPS
(GUI: Options → FPS).
</details>

<details>
<summary><strong>Lip-sync? Real avatar?</strong></summary>

Out of scope for this MVP. The waveform overlay tells Teams "this person
is talking", which is enough for most testing. See
[`plan.md`](#) for Phase-2 ideas (Azure TTS Avatar, MuseTalk, MP4 loop).
</details>

## Development

```powershell
# Install in editable mode with dev extras
.\.venv\Scripts\python.exe -m pip install -e .[dev]

# Run the test suite (no real devices required)
.\.venv\Scripts\python.exe -m pytest

# Lint
.\.venv\Scripts\ruff check src tests
```

## License & credits

* This project: **MIT** (see `LICENSE` if present).
* **VB-Audio Virtual Cable** — donationware, redistributed installer
  downloaded directly from <https://vb-audio.com/Cable/>. Donations
  encouraged.
* **OBS Studio** — GPL v2.
* **ffmpeg (Gyan.FFmpeg build)** — LGPL v2.1.
* **pyvirtualcam** — GPL v2 (Windows backends use OBS / Unity Capture).

## Roadmap (not in MVP)

* TTS plugin (Azure AI Speech, OpenAI TTS, ElevenLabs) — generate audio
  from text live, no need to bring a WAV.
* MP4 loop instead of static image — stream a pre-rendered avatar
  video.
* Live lip-sync via MuseTalk / Wav2Lip — needs an NVIDIA GPU in the VM.
* Azure Communication Services Teams Interop — join a meeting
  programmatically without a VM.
