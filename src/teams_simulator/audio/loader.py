"""Load audio files into a normalised numpy array suitable for playback.

The output of :func:`load_audio` is always:

* dtype ``float32``
* shape ``(n_samples, channels)``  (always 2D, even for mono-1-channel)
* sample rate equal to the requested ``target_sample_rate``
* channel count equal to the requested ``target_channels`` (1 or 2)
* values in roughly ``[-1.0, 1.0]``

This makes the downstream ``AudioPlayer`` trivial: just stream blocks into
the VB-Cable output device.
"""

from __future__ import annotations

import io
import os
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from ..config import DEFAULT_CHANNELS, DEFAULT_SAMPLE_RATE

# Formats that ``soundfile`` (libsndfile) handles natively without needing
# ffmpeg. Anything else (notably MP3) goes through pydub.
NATIVE_EXTENSIONS = {".wav", ".flac", ".ogg", ".aiff", ".aif"}


class AudioLoadError(RuntimeError):
    """Raised when an audio file cannot be decoded."""


def _load_via_soundfile(path: Path) -> tuple[np.ndarray, int]:
    """Decode WAV/FLAC/OGG/AIFF directly via libsndfile."""
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:
        raise AudioLoadError(f"soundfile could not read {path}: {exc}") from exc
    return data, int(sr)


def _load_via_pydub(path: Path) -> tuple[np.ndarray, int]:
    """Decode MP3 (and other ffmpeg-backed formats) via pydub.

    Requires the `ffmpeg` binary on PATH. The setup script installs it.
    """
    try:
        from pydub import AudioSegment  # imported lazily; needs audioop on 3.13
    except Exception as exc:
        raise AudioLoadError(f"pydub is unavailable: {exc}") from exc

    try:
        seg = AudioSegment.from_file(str(path))
    except Exception as exc:
        raise AudioLoadError(
            f"pydub/ffmpeg could not decode {path}: {exc}.\n"
            f"Make sure ffmpeg is installed and on PATH (setup\\install.ps1 installs it)."
        ) from exc

    # Pydub gives us interleaved int samples. Convert to (frames, channels) float32.
    sr = seg.frame_rate
    channels = seg.channels
    sample_width = seg.sample_width  # bytes per sample

    raw = np.frombuffer(seg.raw_data, dtype=_int_dtype_for_width(sample_width))
    if channels > 1:
        raw = raw.reshape(-1, channels)
    else:
        raw = raw.reshape(-1, 1)

    # Normalise to [-1.0, 1.0]
    max_int = float(2 ** (8 * sample_width - 1))
    data = (raw.astype(np.float32) / max_int).copy()
    return data, sr


def _int_dtype_for_width(width: int) -> type[np.integer]:
    return {1: np.int8, 2: np.int16, 4: np.int32}[width]


def _resample_if_needed(data: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
    """Polyphase-resample multi-channel audio to ``target_sr``."""
    if source_sr == target_sr:
        return data
    g = gcd(source_sr, target_sr)
    up = target_sr // g
    down = source_sr // g
    # Resample each channel independently to keep memory low.
    resampled = np.stack(
        [resample_poly(data[:, ch], up, down).astype(np.float32) for ch in range(data.shape[1])],
        axis=1,
    )
    return resampled


def _conform_channels(data: np.ndarray, target_channels: int) -> np.ndarray:
    """Up-/downmix to ``target_channels`` (1 or 2)."""
    n_in = data.shape[1]
    if n_in == target_channels:
        return data
    if target_channels == 1:
        # Average all source channels to mono.
        return data.mean(axis=1, keepdims=True).astype(np.float32)
    if target_channels == 2:
        if n_in == 1:
            # Duplicate mono to L/R.
            return np.repeat(data, 2, axis=1)
        # Mix down to stereo by averaging extra channels into L and R alternately.
        left = data[:, 0::2].mean(axis=1)
        right = data[:, 1::2].mean(axis=1)
        return np.stack([left, right], axis=1).astype(np.float32)
    raise ValueError(f"Unsupported target_channels={target_channels} (must be 1 or 2)")


def load_audio(
    path: str | os.PathLike[str],
    target_sample_rate: int = DEFAULT_SAMPLE_RATE,
    target_channels: int = DEFAULT_CHANNELS,
) -> tuple[np.ndarray, int]:
    """Load and normalise an audio file.

    Args:
        path: WAV/FLAC/OGG/AIFF/MP3 file. Other formats work iff ffmpeg can
            decode them (pydub falls back to ffmpeg).
        target_sample_rate: Output sample rate (Hz). Default 48000.
        target_channels: 1 (mono) or 2 (stereo). Default 2.

    Returns:
        ``(data, sample_rate)`` where ``data`` is a ``float32`` array of
        shape ``(n_samples, target_channels)`` and ``sample_rate ==
        target_sample_rate``.

    Raises:
        AudioLoadError: file missing or undecodable.
    """
    p = Path(path)
    if not p.is_file():
        raise AudioLoadError(f"Audio file not found: {p}")

    ext = p.suffix.lower()
    if ext in NATIVE_EXTENSIONS:
        data, sr = _load_via_soundfile(p)
    else:
        data, sr = _load_via_pydub(p)

    if data.size == 0:
        raise AudioLoadError(f"Audio file {p} is empty")

    data = _resample_if_needed(data, sr, target_sample_rate)
    data = _conform_channels(data, target_channels)

    # Final safety: ensure dtype + contiguity for sounddevice.
    if data.dtype != np.float32:
        data = data.astype(np.float32)
    if not data.flags["C_CONTIGUOUS"]:
        data = np.ascontiguousarray(data)

    return data, target_sample_rate


def write_wav(
    path: str | os.PathLike[str],
    data: np.ndarray,
    sample_rate: int,
) -> None:
    """Convenience helper used by tests and the verify script."""
    sf.write(str(path), data, sample_rate, subtype="PCM_16")


# ---------------------------------------------------------------------------
# Internal: in-memory WAV decode (used by tests).
# ---------------------------------------------------------------------------
def _load_from_bytes(buffer: bytes) -> tuple[np.ndarray, int]:
    data, sr = sf.read(io.BytesIO(buffer), dtype="float32", always_2d=True)
    return data, int(sr)
