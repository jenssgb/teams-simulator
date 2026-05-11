"""Discover the virtual audio and video devices required by the simulator.

The simulator routes audio into VB-Audio Virtual Cable's playback endpoint
so that Microsoft Teams sees the matching capture endpoint as a microphone,
and pushes video frames to the OBS Virtual Camera DirectShow filter so that
Teams sees it as a webcam.

This module locates those devices and provides helpful errors if the user
hasn't run ``setup\\install.ps1`` yet.

Naming is normalised across two VB-Cable releases:

* Driver Pack 43 and earlier — "CABLE Input (VB-Audio Virtual Cable)" /
  "CABLE Output (VB-Audio Virtual Cable)".
* Driver Pack 45 (Oct 2024) — "Output (VB-Audio Point)" /
  "CABLE Output (VB-Audio Point)" / "Input (VB-Audio Point)".

We accept any device name containing one of the VB-Audio markers below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sounddevice as sd

# Substring used to identify the VB-Cable playback device. The full Windows
# name is something like "CABLE Input (VB-Audio Virtual Cable)" on the older
# Driver Pack 43, or "Output (VB-Audio Point)" on Driver Pack 45.
CABLE_INPUT_NAME = "CABLE Input"

# Substring used to identify the matching capture endpoint (what Teams hears
# as a microphone). Surfaced for the verify script and UI display.
CABLE_OUTPUT_NAME = "CABLE Output"

# Display name registered by OBS Studio's built-in Virtual Camera.
OBS_VIRTUAL_CAMERA_NAME = "OBS Virtual Camera"

# Markers that identify a VB-Audio Virtual Cable device regardless of which
# Driver Pack version installed it. Matching is case-insensitive.
_VBAUDIO_MARKERS = (
    "vb-audio",         # "VB-Audio Virtual Cable" / "VB-Audio Point"
    "vb-cable",         # rare, some translations
    "vbaudio",          # WDM-KS sometimes drops the dash
    "cable input",      # legacy, Driver Pack 43
    "cable output",     # legacy, Driver Pack 43
)

INSTALL_HINT = (
    "Run setup\\install.ps1 (as Administrator) to install VB-Audio Virtual "
    "Cable and OBS Studio, then reboot if prompted."
)


class DeviceNotFoundError(RuntimeError):
    """Raised when a required virtual device is missing on this machine."""


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float

    @property
    def is_output(self) -> bool:
        return self.max_output_channels > 0


def list_audio_devices() -> list[AudioDevice]:
    """Return all audio devices visible to PortAudio."""
    devices = []
    for i, info in enumerate(sd.query_devices()):
        devices.append(
            AudioDevice(
                index=i,
                name=info["name"],
                max_input_channels=int(info["max_input_channels"]),
                max_output_channels=int(info["max_output_channels"]),
                default_samplerate=float(info["default_samplerate"]),
            )
        )
    return devices


def _is_vbaudio(name: str) -> bool:
    n = name.lower()
    return any(marker in n for marker in _VBAUDIO_MARKERS)


def _score_playback_candidate(dev: AudioDevice) -> int:
    """Higher = better fit for 'where do we WRITE audio to?'."""
    n = dev.name.lower()
    score = 0
    if "cable input" in n:        # legacy DP43 - the canonical name
        score += 100
    elif "output (vb-audio" in n:  # DP45 - playback endpoint
        score += 80
    elif "vb-audio" in n or "vbaudio" in n:
        score += 40
    # Prefer fewer channels first - the legacy 2ch endpoint is what Teams
    # normally pairs with. The newer 16ch endpoint also works but Teams
    # may negotiate a different sample format.
    score += max(0, 16 - dev.max_output_channels)
    return score


def _score_capture_candidate(dev: AudioDevice) -> int:
    """Higher = better fit for 'what should the user pick as MIC in Teams?'."""
    n = dev.name.lower()
    score = 0
    if "cable output" in n:       # both DP43 and DP45 expose this
        score += 100
    elif "input (vb-audio" in n:  # DP45 generic input endpoint
        score += 60
    elif "vb-audio" in n or "vbaudio" in n:
        score += 40
    score += max(0, 16 - dev.max_input_channels)
    return score


def find_cable_input(devices: Optional[list[AudioDevice]] = None) -> AudioDevice:
    """Locate the VB-Cable playback endpoint we write audio to.

    Matches both Driver Pack 43 (``CABLE Input (VB-Audio Virtual Cable)``)
    and Driver Pack 45 (``Output (VB-Audio Point)``).

    Raises:
        DeviceNotFoundError: if no VB-Audio playback device exists.
    """
    if devices is None:
        devices = list_audio_devices()
    candidates = [d for d in devices if d.is_output and _is_vbaudio(d.name)]
    if not candidates:
        raise DeviceNotFoundError(
            f"Virtual microphone playback device '{CABLE_INPUT_NAME}' not found.\n"
            f"{INSTALL_HINT}"
        )
    candidates.sort(key=_score_playback_candidate, reverse=True)
    return candidates[0]


def find_cable_output(devices: Optional[list[AudioDevice]] = None) -> Optional[AudioDevice]:
    """Locate the matching capture endpoint Teams should pick as its mic.

    Matches both Driver Pack 43 (``CABLE Output (VB-Audio Virtual Cable)``)
    and Driver Pack 45 (``CABLE Output (VB-Audio Point)``).

    Returns ``None`` rather than raising — this is informational only, used
    by the verify script and the UI to display "Teams should select: …".
    """
    if devices is None:
        devices = list_audio_devices()
    candidates = [d for d in devices if d.max_input_channels > 0 and _is_vbaudio(d.name)]
    if not candidates:
        return None
    candidates.sort(key=_score_capture_candidate, reverse=True)
    return candidates[0]


def check_obs_virtual_camera() -> str:
    """Verify the OBS Virtual Camera DirectShow filter is registered.

    We try to open a 1x1 ``pyvirtualcam.Camera`` with the OBS backend; if
    that succeeds, the filter is installed. We close it immediately.

    Returns:
        The name of the camera device that was opened (e.g.
        ``"OBS Virtual Camera"``).

    Raises:
        DeviceNotFoundError: if pyvirtualcam can't open the OBS backend.
    """
    try:
        # Importing inside the function so the module remains importable
        # (and unit-testable) on machines without pyvirtualcam ready.
        import pyvirtualcam  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - dev-time only
        raise DeviceNotFoundError(
            "pyvirtualcam is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    try:
        with pyvirtualcam.Camera(width=320, height=240, fps=20, backend="obs") as cam:
            return cam.device
    except Exception as exc:  # pyvirtualcam raises generic RuntimeError
        raise DeviceNotFoundError(
            f"OBS Virtual Camera not available ({exc}).\n{INSTALL_HINT}\n"
            "Make sure OBS Studio is installed AND has been started at "
            "least once so its DirectShow filter is registered."
        ) from exc


def main() -> int:
    """CLI: ``python -m teams_simulator.devices`` lists what was found."""
    print("=== Audio devices (PortAudio) ===")
    devices = list_audio_devices()
    for dev in devices:
        print(
            f"  [{dev.index:2d}] in={dev.max_input_channels} "
            f"out={dev.max_output_channels} sr={dev.default_samplerate:>6.0f}  {dev.name}"
        )

    print("\n=== Required virtual devices ===")
    rc = 0

    try:
        cable_in = find_cable_input(devices)
        print(f"  [OK]   {CABLE_INPUT_NAME:<14} -> #{cable_in.index} '{cable_in.name}'")
    except DeviceNotFoundError as exc:
        print(f"  [FAIL] {CABLE_INPUT_NAME:<14} -> {exc}")
        rc = 1

    cable_out = find_cable_output(devices)
    if cable_out is not None:
        print(
            f"  [OK]   {CABLE_OUTPUT_NAME:<14} -> #{cable_out.index} "
            f"'{cable_out.name}'  (select this as MIC in Teams)"
        )
    else:
        print(f"  [WARN] {CABLE_OUTPUT_NAME:<14} -> not found (Teams will not see a mic)")

    try:
        cam_name = check_obs_virtual_camera()
        print(f"  [OK]   {OBS_VIRTUAL_CAMERA_NAME:<14} -> '{cam_name}'  (select this as CAMERA in Teams)")
    except DeviceNotFoundError as exc:
        print(f"  [FAIL] {OBS_VIRTUAL_CAMERA_NAME:<14} -> {exc}")
        rc = 1

    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
