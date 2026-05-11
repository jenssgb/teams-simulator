"""Stream a pre-loaded audio buffer into the VB-Cable input device.

The player runs in PortAudio's audio thread via a callback, with a tiny
read pointer protected by a lock. This keeps timing rock-solid without
needing extra threads on the Python side.

Usage::

    data, sr = load_audio("meeting.wav")
    player = AudioPlayer(data, sr, device="CABLE Input", loop=True)
    player.start()
    ...
    player.stop()

While the stream runs, :meth:`AudioPlayer.get_current_level` returns the
RMS level of the last block sent — the video streamer uses that to drive
the waveform overlay.
"""

from __future__ import annotations

import math
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from ..config import DEFAULT_BLOCK_SIZE, DEFAULT_CHANNELS, DEFAULT_SAMPLE_RATE


class AudioPlayer:
    """Stream a numpy buffer into a sounddevice output device.

    Args:
        data: ``(frames, channels)`` float32 array.
        sample_rate: sample rate of ``data`` (Hz).
        device: device name substring or PortAudio index.
        loop: if True, restart from the beginning when the buffer ends.
        block_size: callback block size in frames; lower = lower latency.
        on_finished: optional callback invoked when playback ends naturally
            (i.e. ``loop=False`` and end-of-buffer reached). Always called
            from a background thread.
    """

    def __init__(
        self,
        data: np.ndarray,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        device: Optional[str | int] = "CABLE Input",
        loop: bool = True,
        block_size: int = DEFAULT_BLOCK_SIZE,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        if data.ndim != 2:
            raise ValueError(f"data must be 2D (frames, channels), got shape {data.shape}")
        if data.dtype != np.float32:
            data = data.astype(np.float32)
        if not data.flags["C_CONTIGUOUS"]:
            data = np.ascontiguousarray(data)

        self._data = data
        self._channels = data.shape[1]
        self._sample_rate = sample_rate
        self._device = device
        self._loop = loop
        self._block_size = block_size
        self._on_finished = on_finished

        self._lock = threading.Lock()
        self._position = 0
        self._paused = False
        self._stream: Optional[sd.OutputStream] = None
        self._current_level = 0.0
        self._finished_signaled = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def total_frames(self) -> int:
        return self._data.shape[0]

    @property
    def duration(self) -> float:
        return self.total_frames / float(self._sample_rate)

    def is_running(self) -> bool:
        return self._stream is not None and self._stream.active

    def get_current_level(self) -> float:
        """Last block's RMS, in ``[0.0, 1.0]``. 0 when paused or stopped."""
        return self._current_level

    def get_position(self) -> int:
        with self._lock:
            return self._position

    def seek(self, seconds: float) -> None:
        target = int(round(max(0.0, seconds) * self._sample_rate))
        with self._lock:
            self._position = min(target, self.total_frames)

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def start(self) -> None:
        if self._stream is not None:
            return
        self._finished_signaled = False
        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            device=self._device,
            blocksize=self._block_size,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._current_level = 0.0

    # ------------------------------------------------------------------
    # PortAudio callback (runs in audio thread!)
    # ------------------------------------------------------------------
    def _callback(self, outdata: np.ndarray, frames: int, time_info, status):  # noqa: ANN001
        # status carries underflow/overflow flags; we keep going on either.
        if self._paused:
            outdata.fill(0.0)
            self._current_level = 0.0
            return

        with self._lock:
            pos = self._position
            data = self._data
            total = data.shape[0]

            written = 0
            while written < frames:
                remaining = total - pos
                if remaining <= 0:
                    if self._loop:
                        pos = 0
                        remaining = total
                    else:
                        # End of buffer, no loop: pad with silence and stop.
                        outdata[written:].fill(0.0)
                        self._position = total
                        self._fire_finished_async()
                        self._current_level = 0.0
                        return

                take = min(frames - written, remaining)
                outdata[written : written + take] = data[pos : pos + take]
                pos += take
                written += take

            self._position = pos

        # RMS over the block we just produced.
        self._current_level = float(np.sqrt(np.mean(outdata.astype(np.float32) ** 2)))
        if math.isnan(self._current_level):
            self._current_level = 0.0

    def _fire_finished_async(self) -> None:
        if self._finished_signaled or self._on_finished is None:
            return
        self._finished_signaled = True
        cb = self._on_finished
        threading.Thread(target=cb, daemon=True).start()

    # ------------------------------------------------------------------
    # Context manager sugar
    # ------------------------------------------------------------------
    def __enter__(self) -> "AudioPlayer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


def resolve_device(name_or_index: str | int) -> int:
    """Resolve a device substring or index to a concrete PortAudio index.

    Mirrors sounddevice's resolution but raises a clearer error.
    """
    if isinstance(name_or_index, int):
        return name_or_index
    needle = name_or_index.lower()
    for i, info in enumerate(sd.query_devices()):
        if needle in info["name"].lower() and info["max_output_channels"] > 0:
            return i
    raise RuntimeError(f"No output device matching '{name_or_index}'")
