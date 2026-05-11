"""Unit tests for :mod:`teams_simulator.sync` (controller orchestration)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from teams_simulator.devices import AudioDevice, DeviceNotFoundError
from teams_simulator.sync import SimulatorController, State


@pytest.fixture
def sample_assets(tmp_path: Path):
    """Tiny WAV + PNG so the controller has something to load."""
    audio = tmp_path / "a.wav"
    sf.write(str(audio), np.zeros((4800, 2), dtype=np.float32), 48000, subtype="PCM_16")

    import cv2
    image = tmp_path / "i.png"
    cv2.imwrite(str(image), np.full((480, 640, 3), 100, dtype=np.uint8))

    return str(audio), str(image)


def _fake_cable() -> AudioDevice:
    return AudioDevice(
        index=7, name="CABLE Input (VB-Audio Virtual Cable)",
        max_input_channels=0, max_output_channels=2, default_samplerate=48000.0,
    )


def test_start_then_stop_transitions_state(sample_assets):
    audio_path, image_path = sample_assets

    fake_audio = MagicMock()
    fake_audio.get_position.return_value = 0
    fake_audio.sample_rate = 48000
    fake_audio.duration = 0.1
    fake_audio.get_current_level.return_value = 0.0

    fake_video = MagicMock()
    fake_video.is_running = True

    with patch("teams_simulator.sync.find_cable_input", return_value=_fake_cable()), \
         patch("teams_simulator.sync.check_obs_virtual_camera", return_value="OBS Virtual Camera"), \
         patch("teams_simulator.sync.AudioPlayer", return_value=fake_audio), \
         patch("teams_simulator.sync.VideoStreamer", return_value=fake_video):

        c = SimulatorController.from_paths(audio_path, image_path, loop=True)
        c.start()
        assert c.get_status().state == State.RUNNING
        fake_audio.start.assert_called_once()
        fake_video.start.assert_called_once()

        c.pause()
        assert c.get_status().state == State.PAUSED
        fake_audio.pause.assert_called_once()

        c.resume()
        assert c.get_status().state == State.RUNNING

        c.stop()
        assert c.get_status().state == State.IDLE
        fake_audio.stop.assert_called_once()
        fake_video.stop.assert_called_once()


def test_start_propagates_device_error_and_cleans_up(sample_assets):
    audio_path, image_path = sample_assets

    with patch("teams_simulator.sync.find_cable_input",
               side_effect=DeviceNotFoundError("CABLE Input not found")):
        c = SimulatorController.from_paths(audio_path, image_path)
        with pytest.raises(DeviceNotFoundError):
            c.start()
        assert c.get_status().state == State.ERROR
        assert "CABLE Input" in c.get_status().message


def test_video_start_failure_stops_audio(sample_assets):
    audio_path, image_path = sample_assets
    fake_audio = MagicMock()
    # VideoStreamer constructor succeeds, but its .start() raises -- by which
    # point AudioPlayer.start() has already run, so it must be cleaned up.
    fake_video = MagicMock()
    fake_video.start.side_effect = RuntimeError("boom")

    with patch("teams_simulator.sync.find_cable_input", return_value=_fake_cable()), \
         patch("teams_simulator.sync.check_obs_virtual_camera", return_value="OBS Virtual Camera"), \
         patch("teams_simulator.sync.AudioPlayer", return_value=fake_audio), \
         patch("teams_simulator.sync.VideoStreamer", return_value=fake_video):

        c = SimulatorController.from_paths(audio_path, image_path)
        with pytest.raises(RuntimeError):
            c.start()
        fake_audio.start.assert_called_once()
        fake_audio.stop.assert_called_once()
        assert c.get_status().state == State.ERROR


def test_listeners_are_notified_on_state_changes(sample_assets):
    audio_path, image_path = sample_assets

    fake_audio = MagicMock()
    fake_audio.get_position.return_value = 0
    fake_audio.sample_rate = 48000
    fake_audio.duration = 0.0
    fake_audio.get_current_level.return_value = 0.0
    fake_video = MagicMock()

    seen_states: list[State] = []
    cv = threading.Condition()

    def listener(status):
        with cv:
            seen_states.append(status.state)
            cv.notify_all()

    with patch("teams_simulator.sync.find_cable_input", return_value=_fake_cable()), \
         patch("teams_simulator.sync.check_obs_virtual_camera", return_value="OBS Virtual Camera"), \
         patch("teams_simulator.sync.AudioPlayer", return_value=fake_audio), \
         patch("teams_simulator.sync.VideoStreamer", return_value=fake_video):

        c = SimulatorController.from_paths(audio_path, image_path)
        c.add_listener(listener)
        c.start()
        c.stop()

    assert State.RUNNING in seen_states
    assert State.IDLE in seen_states
