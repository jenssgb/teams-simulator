"""Unit tests for :mod:`teams_simulator.audio.loader`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from teams_simulator.audio.loader import AudioLoadError, load_audio


def _write_sine_wav(path: Path, sr: int, duration: float, channels: int = 1, freq: float = 440.0):
    n = int(round(sr * duration))
    t = np.linspace(0.0, duration, n, endpoint=False, dtype=np.float32)
    mono = 0.3 * np.sin(2 * np.pi * freq * t)
    if channels == 1:
        data = mono[:, None]
    else:
        data = np.stack([mono] * channels, axis=1)
    sf.write(str(path), data, sr, subtype="PCM_16")


def test_load_wav_native_no_resample(tmp_path: Path):
    src = tmp_path / "tone.wav"
    _write_sine_wav(src, sr=48000, duration=0.5, channels=2)

    data, sr = load_audio(src, target_sample_rate=48000, target_channels=2)

    assert sr == 48000
    assert data.dtype == np.float32
    assert data.ndim == 2
    assert data.shape[1] == 2
    assert data.shape[0] == 24000  # 0.5s * 48kHz
    assert -1.0 <= float(data.min()) and float(data.max()) <= 1.0


def test_load_wav_resamples_to_target_rate(tmp_path: Path):
    src = tmp_path / "tone.wav"
    _write_sine_wav(src, sr=22050, duration=0.5, channels=1)

    data, sr = load_audio(src, target_sample_rate=48000, target_channels=2)

    assert sr == 48000
    assert data.shape[1] == 2
    # ~0.5s at 48kHz = 24000 samples (poly resample may be off by a handful).
    assert abs(data.shape[0] - 24000) < 16


def test_load_wav_mono_to_stereo(tmp_path: Path):
    src = tmp_path / "mono.wav"
    _write_sine_wav(src, sr=48000, duration=0.25, channels=1)

    data, _ = load_audio(src, target_sample_rate=48000, target_channels=2)

    assert data.shape[1] == 2
    # Mono duplicated -> both channels identical.
    np.testing.assert_array_equal(data[:, 0], data[:, 1])


def test_load_wav_stereo_to_mono(tmp_path: Path):
    src = tmp_path / "stereo.wav"
    _write_sine_wav(src, sr=48000, duration=0.25, channels=2)

    data, _ = load_audio(src, target_sample_rate=48000, target_channels=1)

    assert data.shape[1] == 1
    assert data.dtype == np.float32


def test_load_missing_file_raises():
    with pytest.raises(AudioLoadError):
        load_audio("does/not/exist.wav")


def test_load_empty_file_raises(tmp_path: Path):
    src = tmp_path / "empty.wav"
    sf.write(str(src), np.zeros((0, 1), dtype=np.float32), 48000, subtype="PCM_16")
    with pytest.raises(AudioLoadError):
        load_audio(src)


def test_unknown_extension_uses_pydub_path(tmp_path: Path, monkeypatch):
    """If a file isn't a known native format, loader should try pydub."""
    src = tmp_path / "weird.xyz"
    src.write_bytes(b"not really audio")

    # pydub's AudioSegment.from_file will fail; we should get a clean error.
    with pytest.raises(AudioLoadError):
        load_audio(src)
