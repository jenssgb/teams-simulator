"""Discover the virtual audio and video devices required by the simulator.

The simulator routes audio into VB-Audio Virtual Cable's playback endpoint
("CABLE Input") so that Microsoft Teams sees the matching capture endpoint
("CABLE Output") as a microphone, and pushes video frames to the OBS Virtual
Camera DirectShow filter so that Teams sees it as a webcam.

This module locates those devices and provides helpful errors if the user
hasn't run ``setup\\install.ps1`` yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sounddevice as sd

# Substring used to identify the VB-Cable playback device. The full Windows
# name is something like "CABLE Input (VB-Audio Virtual Cable)".
CABLE_INPUT_NAME = "CABLE Input"

# Substring used to identify the matching capture endpoint (what Teams hears
# as a microphone). Surfaced for the verify script and UI display.
CABLE_OUTPUT_NAME = "CABLE Output"

# Display name registered by OBS Studio's built-in Virtual Camera.
OBS_VIRTUAL_CAMERA_NAME = "OBS Virtual Camera"

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


def find_cable_input(devices: Optional[list[AudioDevice]] = None) -> AudioDevice:
    """Locate the VB-Cable playback endpoint we write audio to.

    Raises:
        DeviceNotFoundError: if VB-Cable is not installed (or under a
            different name than ``CABLE Input``).
    """
    if devices is None:
        devices = list_audio_devices()
    for dev in devices:
        if CABLE_INPUT_NAME.lower() in dev.name.lower() and dev.is_output:
            return dev
    raise DeviceNotFoundError(
        f"Virtual microphone playback device '{CABLE_INPUT_NAME}' not found.\n"
        f"{INSTALL_HINT}"
    )


def find_cable_output(devices: Optional[list[AudioDevice]] = None) -> Optional[AudioDevice]:
    """Locate the matching capture endpoint Teams should pick as its mic.

    Returns ``None`` rather than raising — this is informational only, used
    by the verify script and the UI to display "Teams should select: …".
    """
    if devices is None:
        devices = list_audio_devices()
    for dev in devices:
        if CABLE_OUTPUT_NAME.lower() in dev.name.lower() and dev.max_input_channels > 0:
            return dev
    return None


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
