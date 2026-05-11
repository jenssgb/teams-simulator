"""Drive the OBS Virtual Camera with a static avatar + waveform animation.

A background thread copies the prepared avatar frame each tick, asks the
:class:`AudioLevelSource` for the current RMS, lets the
:class:`WaveformAnimator` overlay the bars, and pushes the frame to
``pyvirtualcam``. ``sleep_until_next_frame()`` keeps the FPS stable.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Protocol

import numpy as np
import pyvirtualcam
from pyvirtualcam import PixelFormat

from ..config import DEFAULT_VIDEO_FPS, DEFAULT_VIDEO_HEIGHT, DEFAULT_VIDEO_WIDTH
from .frame_source import load_image, make_placeholder
from .waveform import WaveformAnimator


class AudioLevelSource(Protocol):
    """Anything that can report a current RMS level in ``[0.0, 1.0]``."""

    def get_current_level(self) -> float: ...


class _ZeroLevelSource:
    def get_current_level(self) -> float:
        return 0.0


class VideoStreamer:
    """Background-thread video loop that pushes frames to OBS Virtual Camera.

    Args:
        image_path: Path to the avatar image. ``None`` → placeholder card.
        width, height, fps: Video format. 720p30 by default.
        level_source: Object whose ``get_current_level()`` drives the bars.
        backend: pyvirtualcam backend; ``"obs"`` is the only one we support
            on Windows out of the box.
    """

    def __init__(
        self,
        image_path: Optional[str] = None,
        width: int = DEFAULT_VIDEO_WIDTH,
        height: int = DEFAULT_VIDEO_HEIGHT,
        fps: int = DEFAULT_VIDEO_FPS,
        level_source: Optional[AudioLevelSource] = None,
        backend: str = "obs",
        animator: Optional[WaveformAnimator] = None,
    ):
        self._width = width
        self._height = height
        self._fps = fps
        self._backend = backend
        self._level_source: AudioLevelSource = level_source or _ZeroLevelSource()
        self._animator = animator or WaveformAnimator(fps=fps)

        if image_path:
            self._base_frame = load_image(image_path, width, height)
        else:
            self._base_frame = make_placeholder(width, height)

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._error: Optional[BaseException] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> Optional[BaseException]:
        return self._error

    def set_image(self, image_path: Optional[str]) -> None:
        """Replace the avatar mid-stream."""
        if image_path:
            self._base_frame = load_image(image_path, self._width, self._height)
        else:
            self._base_frame = make_placeholder(self._width, self._height)

    def set_level_source(self, source: AudioLevelSource) -> None:
        self._level_source = source

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="VideoStreamer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            with pyvirtualcam.Camera(
                width=self._width,
                height=self._height,
                fps=self._fps,
                fmt=PixelFormat.BGR,
                backend=self._backend,
            ) as cam:
                # We allocate one working buffer and reuse it.
                frame = np.empty_like(self._base_frame)
                while not self._stop_event.is_set():
                    np.copyto(frame, self._base_frame)
                    self._animator.push_level(self._level_source.get_current_level())
                    self._animator.draw(frame)
                    cam.send(frame)
                    cam.sleep_until_next_frame()
        except BaseException as exc:
            self._error = exc
            # We don't re-raise — the thread is daemon, the controller
            # checks ``last_error`` to surface the failure to the UI.


# ---------------------------------------------------------------------------
# Convenience helper for headless testing without a real OBS install.
# ---------------------------------------------------------------------------
def run_test_pattern(
    width: int = DEFAULT_VIDEO_WIDTH,
    height: int = DEFAULT_VIDEO_HEIGHT,
    fps: int = DEFAULT_VIDEO_FPS,
    duration_seconds: float = 5.0,
    on_frame: Optional[Callable[[np.ndarray], None]] = None,
) -> None:
    """Render frames in-process for ``duration_seconds`` without using OBS.

    Used by tests and demos. ``on_frame`` is called for every frame.
    """
    base = make_placeholder(width, height, "Test pattern")
    animator = WaveformAnimator(fps=fps)
    end = time.monotonic() + duration_seconds
    period = 1.0 / fps
    next_t = time.monotonic()
    n = 0
    while time.monotonic() < end:
        frame = base.copy()
        animator.push_level(0.5 + 0.5 * np.sin(n / 20.0))
        animator.draw(frame)
        if on_frame is not None:
            on_frame(frame)
        n += 1
        next_t += period
        sleep_for = next_t - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
