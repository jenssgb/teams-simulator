"""Animated equalizer-style waveform overlay for the camera frame.

The overlay is a row of vertical bars at the bottom of the frame whose
height is driven by the current audio RMS level. We keep a short rolling
history so the bars look like a real spectrum analyser rather than all
moving in lockstep.

The overlay is intentionally subtle: a translucent strip across the
bottom plus the bars, so the avatar image stays readable.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class WaveformAnimator:
    """Stateful bar-graph animator.

    The state (a small deque of recent levels) means each instance produces
    smooth animation across calls; create one per video stream.
    """

    bar_count: int = 24
    history_seconds: float = 1.5
    fps: int = 30
    bar_color: tuple[int, int, int] = (0, 200, 255)  # BGR — warm amber
    strip_color: tuple[int, int, int] = (0, 0, 0)
    strip_alpha: float = 0.45
    height_fraction: float = 0.18  # how much of the frame the strip takes
    min_bar_height_fraction: float = 0.05  # always show a tiny floor

    _history: deque[float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        history_len = max(self.bar_count, int(self.history_seconds * self.fps))
        self._history = deque([0.0] * history_len, maxlen=history_len)

    def push_level(self, rms: float) -> None:
        """Record one RMS sample. Should be called once per video frame."""
        self._history.append(max(0.0, min(1.0, float(rms))))

    def draw(self, frame: np.ndarray) -> np.ndarray:
        """Draw the bars onto ``frame`` in place and return it.

        ``frame`` must be a contiguous BGR uint8 image of arbitrary size.
        """
        h, w = frame.shape[:2]
        strip_h = max(40, int(round(h * self.height_fraction)))
        strip_y0 = h - strip_h
        strip_y1 = h

        # Translucent black strip behind the bars.
        if self.strip_alpha > 0:
            overlay = frame[strip_y0:strip_y1].copy()
            overlay[:] = self.strip_color
            cv2.addWeighted(
                overlay,
                self.strip_alpha,
                frame[strip_y0:strip_y1],
                1.0 - self.strip_alpha,
                0,
                dst=frame[strip_y0:strip_y1],
            )

        # Map history onto bars: take the last bar_count samples and emphasise
        # higher frequencies (later samples) by a perceptual sqrt curve.
        recent = list(self._history)[-self.bar_count :]
        if len(recent) < self.bar_count:
            recent = [0.0] * (self.bar_count - len(recent)) + recent

        bar_area_h = int(strip_h * 0.78)
        bar_baseline = strip_y0 + strip_h - int(strip_h * 0.12)
        floor = int(bar_area_h * self.min_bar_height_fraction)

        gap = max(2, int(w / (self.bar_count * 6)))
        bar_w = max(2, (w - gap * (self.bar_count + 1)) // self.bar_count)
        x = gap

        for level in recent:
            # Perceptual scale; sqrt makes quiet speech still visible.
            visual = float(np.sqrt(level))
            bar_h = max(floor, int(bar_area_h * min(1.0, visual * 1.6)))
            y0 = bar_baseline - bar_h
            y1 = bar_baseline
            cv2.rectangle(frame, (x, y0), (x + bar_w, y1), self.bar_color, thickness=-1)
            x += bar_w + gap

        return frame
