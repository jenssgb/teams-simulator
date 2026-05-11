"""Unit tests for :mod:`teams_simulator.audio.player` (no real device)."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from teams_simulator.audio.player import AudioPlayer


def _make_buffer(seconds: float = 0.1, sr: int = 48000, channels: int = 2) -> np.ndarray:
    n = int(round(sr * seconds))
    t = np.linspace(0.0, seconds, n, endpoint=False, dtype=np.float32)
    mono = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    if channels == 1:
        return mono[:, None]
    return np.stack([mono] * channels, axis=1)


def test_player_validates_2d_input():
    with pytest.raises(ValueError):
        AudioPlayer(data=np.zeros(100, dtype=np.float32))


def test_callback_writes_block_and_advances_position():
    data = _make_buffer(seconds=0.05)
    player = AudioPlayer(data=data, sample_rate=48000, device=None, loop=False)

    out = np.zeros((512, 2), dtype=np.float32)
    player._callback(out, 512, None, None)

    assert player.get_position() == 512
    # Should not be all zeros - we wrote real samples.
    assert np.any(out != 0)
    # RMS is reported.
    assert player.get_current_level() > 0.0


def test_callback_loops_when_loop_true():
    data = _make_buffer(seconds=0.01)  # 480 samples
    player = AudioPlayer(data=data, sample_rate=48000, device=None, loop=True)
    total = data.shape[0]

    out = np.zeros((total + 100, 2), dtype=np.float32)
    player._callback(out, total + 100, None, None)

    # Position wraps to 100 because we overshot by 100 frames.
    assert player.get_position() == 100


def test_callback_pads_silence_and_fires_finished_when_loop_false():
    data = _make_buffer(seconds=0.01)  # 480 samples
    finished = threading.Event()
    player = AudioPlayer(
        data=data, sample_rate=48000, device=None, loop=False,
        on_finished=lambda: finished.set(),
    )
    total = data.shape[0]

    out = np.full((total + 200, 2), 99.0, dtype=np.float32)
    player._callback(out, total + 200, None, None)

    # Tail beyond data length must be zero-filled.
    assert np.all(out[total:] == 0.0)
    assert player.get_position() == total
    assert finished.wait(timeout=1.0)


def test_pause_emits_silence_and_zero_level():
    data = _make_buffer()
    player = AudioPlayer(data=data, sample_rate=48000, device=None)
    player.pause()

    out = np.full((256, 2), 7.0, dtype=np.float32)
    player._callback(out, 256, None, None)

    assert np.all(out == 0.0)
    assert player.get_current_level() == 0.0
    # Position is unchanged.
    assert player.get_position() == 0


def test_seek_clamps_to_buffer():
    data = _make_buffer(seconds=0.1)
    player = AudioPlayer(data=data, sample_rate=48000, device=None)
    player.seek(99.0)
    assert player.get_position() == data.shape[0]
    player.seek(-3.0)
    assert player.get_position() == 0


def test_start_opens_outputstream_with_resolved_index():
    data = _make_buffer()
    fake_stream = MagicMock()
    with patch("sounddevice.OutputStream", return_value=fake_stream) as ctor:
        player = AudioPlayer(data=data, sample_rate=48000, device=42, block_size=960)
        player.start()
    ctor.assert_called_once()
    # Confirm device index was forwarded.
    assert ctor.call_args.kwargs["device"] == 42
    assert ctor.call_args.kwargs["samplerate"] == 48000
    fake_stream.start.assert_called_once()
