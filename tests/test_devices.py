"""Unit tests for :mod:`teams_simulator.devices` (mock-based)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teams_simulator import devices


FAKE_DEVICES_WITH_CABLE = [
    {"name": "Microsoft Sound Mapper", "max_input_channels": 2, "max_output_channels": 0,
     "default_samplerate": 44100},
    {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000},
    {"name": "CABLE Output (VB-Audio Virtual Cable)", "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 48000},
    {"name": "Speakers (Realtek)", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 48000},
]

FAKE_DEVICES_NO_CABLE = [
    {"name": "Microsoft Sound Mapper", "max_input_channels": 2, "max_output_channels": 0,
     "default_samplerate": 44100},
    {"name": "Speakers (Realtek)", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 48000},
]


# Real device list reported by VB-Cable Driver Pack 45 (Oct 2024). The legacy
# "CABLE Input" / "CABLE Output" names became "Output (VB-Audio Point)" and
# "CABLE Output (VB-Audio Point)" — capture this so we don't regress.
FAKE_DEVICES_DRIVER_PACK_45 = [
    {"name": "Microsoft Sound Mapper - Output", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 44100},
    {"name": "Remote Audio", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 44100},
    {"name": "Primary Sound Driver", "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 44100},
    {"name": "Remote Audio", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 44100},
    {"name": "Remote Audio", "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 48000},
    {"name": "CABLE Output (VB-Audio Point)", "max_input_channels": 16,
     "max_output_channels": 0, "default_samplerate": 48000},
    {"name": "Output (VB-Audio Point)", "max_input_channels": 0,
     "max_output_channels": 16, "default_samplerate": 48000},
    {"name": "Input (VB-Audio Point)", "max_input_channels": 16,
     "max_output_channels": 0, "default_samplerate": 48000},
]


def test_list_audio_devices_wraps_sounddevice_output():
    with patch("teams_simulator.devices.sd.query_devices", return_value=FAKE_DEVICES_WITH_CABLE):
        result = devices.list_audio_devices()
    assert len(result) == 4
    assert result[1].name.startswith("CABLE Input")
    assert result[1].is_output
    assert result[1].max_output_channels == 2


def test_find_cable_input_returns_playback_endpoint():
    with patch("teams_simulator.devices.sd.query_devices", return_value=FAKE_DEVICES_WITH_CABLE):
        cable = devices.find_cable_input()
    assert cable.index == 1
    assert "CABLE Input" in cable.name
    assert cable.is_output


def test_find_cable_input_raises_when_missing():
    with patch("teams_simulator.devices.sd.query_devices", return_value=FAKE_DEVICES_NO_CABLE):
        with pytest.raises(devices.DeviceNotFoundError) as exc:
            devices.find_cable_input()
    assert "install.ps1" in str(exc.value)


def test_find_cable_output_returns_capture_endpoint():
    with patch("teams_simulator.devices.sd.query_devices", return_value=FAKE_DEVICES_WITH_CABLE):
        cable = devices.find_cable_output()
    assert cable is not None
    assert cable.index == 2
    assert "CABLE Output" in cable.name


def test_find_cable_output_returns_none_when_missing():
    with patch("teams_simulator.devices.sd.query_devices", return_value=FAKE_DEVICES_NO_CABLE):
        assert devices.find_cable_output() is None


def test_find_cable_input_handles_driver_pack_45_naming():
    """Driver Pack 45 renames 'CABLE Input' to 'Output (VB-Audio Point)'."""
    with patch("teams_simulator.devices.sd.query_devices", return_value=FAKE_DEVICES_DRIVER_PACK_45):
        cable = devices.find_cable_input()
    assert cable.name == "Output (VB-Audio Point)"
    assert cable.is_output


def test_find_cable_output_handles_driver_pack_45_naming():
    """Driver Pack 45 keeps 'CABLE Output' but appends '(VB-Audio Point)'."""
    with patch("teams_simulator.devices.sd.query_devices", return_value=FAKE_DEVICES_DRIVER_PACK_45):
        cable = devices.find_cable_output()
    assert cable is not None
    assert cable.name == "CABLE Output (VB-Audio Point)"
    assert cable.max_input_channels > 0


def test_find_cable_input_prefers_legacy_name_when_both_present():
    """If a system has both DP43 and DP45 endpoints, prefer the legacy one."""
    mixed = FAKE_DEVICES_DRIVER_PACK_45 + [
        {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_input_channels": 0,
         "max_output_channels": 2, "default_samplerate": 48000},
    ]
    with patch("teams_simulator.devices.sd.query_devices", return_value=mixed):
        cable = devices.find_cable_input()
    assert "CABLE Input" in cable.name


def test_check_obs_virtual_camera_passes_when_open_succeeds():
    fake_cam = type("FakeCam", (), {
        "device": "OBS Virtual Camera",
        "__enter__": lambda self: self,
        "__exit__": lambda self, *a: False,
    })()

    with patch("pyvirtualcam.Camera", return_value=fake_cam):
        name = devices.check_obs_virtual_camera()
    assert name == "OBS Virtual Camera"


def test_check_obs_virtual_camera_raises_with_helpful_message():
    with patch("pyvirtualcam.Camera", side_effect=RuntimeError("no backend")):
        with pytest.raises(devices.DeviceNotFoundError) as exc:
            devices.check_obs_virtual_camera()
    assert "OBS Virtual Camera" in str(exc.value)
    assert "install.ps1" in str(exc.value)
