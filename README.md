<div align="center">

# 🎙️📷 Teams Simulator

**A virtual participant for Microsoft Teams.**
Stream a pre-recorded monologue and an AI avatar into any Teams meeting
on a Windows 11 VM — exposed as a real virtual mic and webcam.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](#)
[![Windows 11](https://img.shields.io/badge/Windows-11-0078D6?logo=windows&logoColor=white)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-black)](#-license)
[![Tests: 46 passing](https://img.shields.io/badge/tests-46_passing-brightgreen)](#)

</div>

---

## ⚡ Install

> [!IMPORTANT]
> **Open PowerShell as Administrator** ( `Win` → type `PowerShell` → `Ctrl+Shift+Enter` ),
> then paste **one** line:

```powershell
iex (irm 'https://raw.githubusercontent.com/jenssgb/teams-simulator/main/setup/bootstrap.ps1')
```

That's it. The bootstrapper installs Python 3.11, ffmpeg, VB-Audio Virtual
Cable and OBS Studio (for the virtual webcam), creates a venv, drops a
**Teams Simulator** shortcut on your Desktop, and writes every log to
`Desktop\TeamsSimulatorLogs`. Reboot once when prompted.

---

## ▶ Use

1. **Reboot** so the virtual audio driver loads.
2. **Double-click** the **Teams Simulator** shortcut on your Desktop.
3. Pick an avatar + a sample, hit **▶ Start**.
4. In your Teams meeting, choose:
   - 🎙 **Microphone** → `CABLE Output (VB-Audio Virtual Cable)`
   - 📷 **Camera** → `OBS Virtual Camera`

That's the whole flow. Done.

> 💡 **On RDP?** In your RDP client, set **Remote audio playback → Play on
> this computer**, otherwise Teams won't see any signal.

---

## 🎁 What's bundled

**5 AI avatars** — Atlas · Cosmo · Jasper · Maeve · Wren — each with an
animated audio-level waveform overlay so the picture looks alive.

**3 tiers of English speech** in the **Audio sample** dropdown:

| | | |
|---|---|---|
| 💼 **Business** | AI in software engineering · Cloud architecture lessons | ~13 min each, bundled |
| 📚 **Classic** | Sherlock Holmes — Red-Headed League · Walden | ~30–60 min, on-demand download |
| 🔬 **Quick test** | Welcome · TED-style snippet · Storytelling | ~10 s, bundled |

Default is the first **💼 Business** monologue — transcript-ready out of the
box. Want your own audio? Use the file picker.

---

## 🧩 How it works

```
┌──────────────┐   PCM    ┌──────────────────┐  virtual  ┌──────────┐
│  Audio file  │ ───────▶ │   AudioPlayer    │ ────────▶ │          │
└──────────────┘  16 kHz  │   (sounddevice)  │   mic     │          │
                          └──────────────────┘           │  Teams   │
┌──────────────┐  frames  ┌──────────────────┐  virtual  │          │
│  Avatar PNG  │ ───────▶ │  VideoStreamer   │ ────────▶ │          │
└──────────────┘  +waveform│  (OBS DShow)     │   cam     └──────────┘
                          └──────────────────┘
                              ▲ live RMS
                              └────── audio level overlay
```

A single `SimulatorController` orchestrates both sides atomically and surfaces
state (idle / starting / streaming / paused / error) plus live audio level &
position to the GUI.

---

## 🖥 GUI at a glance

A clean Tkinter window with everything in one place:

- **Virtual devices** — green/red status for the mic and camera
- **Inputs** — avatar + audio sample, or pick your own files
- **Options** — loop, FPS
- **Playback** — color-coded status banner, async start (UI never freezes),
  audio progress bar with countdown (`⏳ 7:10 remaining`), live level meter
- **Log** — INFO/ERROR stream, also persisted to `Desktop\TeamsSimulatorLogs`

---

## 🛠 CLI

```powershell
.venv\Scripts\teams-sim.exe `
    --audio  samples\long\business_01_ai_in_software_engineering.mp3 `
    --image  samples\avatars\atlas.png `
    --loop --fps 30 --resolution 1280x720
```

`teams-sim --help` lists every flag. `--duration N` auto-stops after N seconds.

---

## 📦 Offline / manual install

Got a sealed VM with no internet? Copy the repo onto it and run:

```powershell
cd C:\teams-simulator
.\setup\install.ps1          # downloads tools + sets up venv
# OR
.\setup\install.ps1 -Offline # skip downloads, use bundled installers
```

After the reboot prompt, `verify.ps1` confirms the virtual mic + camera are
visible to Teams.

---

## 🩹 Troubleshooting

| Symptom | Fix |
|---|---|
| Teams doesn't see `CABLE Output` | Reboot. If still missing, **Settings → Privacy & security → Windows Security → Device security → Core isolation → Memory integrity = Off**, reboot. (Win 11 HVCI blocks third-party audio drivers.) |
| `OBS Virtual Camera` missing | Run `.\setup\fix-audio.ps1` or reinstall OBS Studio. |
| No audio level in Teams over RDP | RDP client → **Remote audio playback → Play on this computer**. |
| Console closes before you can read it | All scripts now show **"Press Enter to close…"**. Set `$env:TEAMS_SIMULATOR_NONINTERACTIVE=1` to disable in CI. |
| Anything else | `.\setup\diagnose.ps1` — copies a full report to your clipboard and `Desktop\TeamsSimulatorLogs\`. |

---

## 🧪 Development

```powershell
pip install -e .[dev]
pytest                        # 46 tests, no real devices required
ruff check .                  # lint
```

Repository layout:

```
src/teams_simulator/   Python package (audio, video, sync, ui, cli)
setup/                 PowerShell bootstrap, install, verify, diagnose, fix
samples/               avatars + speech samples (business + quick-test bundled)
scripts/               sample generators (Edge-TTS) + LibriVox downloader
tests/                 pytest suite
```

---

## 📜 License

MIT. Bundled audio: Edge-TTS output (locally generated, freely
redistributable) and LibriVox recordings (public domain). Avatars are
AI-generated and ship under MIT with the rest of the repo.

> Built for testing Teams meeting features (recording, Copilot, transcription,
> compliance bots) without needing a real participant.
