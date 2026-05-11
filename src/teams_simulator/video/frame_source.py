"""Load and prepare a static avatar image as a base BGR frame for the camera.

The image is loaded once, scaled to the target camera resolution (with
letterboxing to preserve aspect ratio), and cached. The streamer then
copies that base frame each tick and overlays the audio-level animation on
top of it — see :mod:`teams_simulator.video.waveform`.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np


class FrameSourceError(RuntimeError):
    """Raised when an avatar image cannot be loaded."""


def load_image(
    path: str | os.PathLike[str],
    width: int,
    height: int,
    background: tuple[int, int, int] = (16, 16, 16),
) -> np.ndarray:
    """Load ``path`` and return a ``(height, width, 3)`` BGR uint8 frame.

    The source image is letterboxed (or pillarboxed) onto a solid
    ``background`` colour so the output exactly matches the requested
    resolution without distortion.
    """
    p = Path(path)
    if not p.is_file():
        raise FrameSourceError(f"Image file not found: {p}")

    # cv2.imread doesn't handle non-ASCII paths on Windows -> read bytes first.
    raw = np.fromfile(str(p), dtype=np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if img is None:
        raise FrameSourceError(f"OpenCV could not decode image: {p}")

    return _letterbox(img, width, height, background)


def _letterbox(
    img: np.ndarray,
    target_w: int,
    target_h: int,
    bg: tuple[int, int, int],
) -> np.ndarray:
    """Resize ``img`` to fit inside ``target_w x target_h`` preserving aspect."""
    src_h, src_w = img.shape[:2]
    if src_w == 0 or src_h == 0:
        raise FrameSourceError("Source image has zero dimension")

    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(img, (new_w, new_h), interpolation=interp)

    # Always produce 3-channel BGR even if the source was greyscale or RGBA.
    if resized.ndim == 2:
        resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)
    elif resized.shape[2] == 4:
        resized = cv2.cvtColor(resized, cv2.COLOR_BGRA2BGR)

    canvas = np.full((target_h, target_w, 3), bg, dtype=np.uint8)
    y_off = (target_h - new_h) // 2
    x_off = (target_w - new_w) // 2
    canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
    return canvas


def make_placeholder(
    width: int,
    height: int,
    text: str = "Teams Simulator",
    bg: tuple[int, int, int] = (32, 32, 48),
    fg: tuple[int, int, int] = (220, 220, 220),
) -> np.ndarray:
    """Generate a simple text placeholder frame, used when no image is set."""
    canvas = np.full((height, width, 3), bg, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.5, min(width, height) / 600.0)
    thickness = max(1, int(scale * 2))
    (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
    cv2.putText(
        canvas,
        text,
        ((width - tw) // 2, (height + th) // 2),
        font,
        scale,
        fg,
        thickness,
        cv2.LINE_AA,
    )
    return canvas
