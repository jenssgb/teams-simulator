"""Generate the bundled sample audio + image assets.

Re-run this whenever ``samples/demo_audio.wav`` or ``samples/demo_avatar.png``
needs to be refreshed. Output is fully deterministic.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parent.parent
SAMPLES = REPO / "samples"


def make_audio(path: Path, sample_rate: int = 48_000, duration: float = 6.0) -> None:
    n = int(round(sample_rate * duration))
    t = np.linspace(0.0, duration, n, endpoint=False, dtype=np.float32)

    carrier_freq = 200 + 250 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.15 * t))
    phase = 2 * np.pi * np.cumsum(carrier_freq) / sample_rate
    carrier = np.sin(phase)

    syllable = 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)

    silence_mask = np.ones_like(t)
    for start, end in [(1.7, 2.0), (3.9, 4.3)]:
        silence_mask[(t >= start) & (t < end)] = 0.0

    envelope = syllable * silence_mask
    mono = 0.4 * carrier * envelope
    stereo = np.stack([mono, mono], axis=1).astype(np.float32)

    sf.write(str(path), stereo, sample_rate, subtype="PCM_16")
    print(f"wrote {path} ({duration:.1f}s @ {sample_rate} Hz, stereo)")


def make_image(path: Path, width: int = 1280, height: int = 720) -> None:
    img = np.zeros((height, width, 3), dtype=np.uint8)

    top = np.array([60, 35, 20], dtype=np.float32)
    bot = np.array([90, 70, 40], dtype=np.float32)
    for y in range(height):
        a = y / max(1, height - 1)
        img[y, :] = (top * (1 - a) + bot * a).astype(np.uint8)

    cx = width // 2
    cy_head = int(height * 0.42)
    head_r = int(min(width, height) * 0.16)

    cv2.ellipse(
        img,
        (cx, height + int(head_r * 1.2)),
        (int(head_r * 2.6), int(head_r * 2.6)),
        0, 0, 360,
        (190, 170, 150), -1, lineType=cv2.LINE_AA,
    )
    cv2.circle(img, (cx, cy_head), head_r, (220, 200, 180), -1, lineType=cv2.LINE_AA)

    label = "Teams Simulator (sample avatar)"
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.9
    thickness = 2
    (tw, th), _ = cv2.getTextSize(label, font, scale, thickness)
    cv2.putText(
        img, label,
        ((width - tw) // 2, int(height * 0.92)),
        font, scale, (240, 240, 240), thickness, cv2.LINE_AA,
    )

    ok = cv2.imwrite(str(path), img)
    if not ok:
        raise RuntimeError(f"cv2.imwrite failed for {path}")
    print(f"wrote {path} ({width}x{height})")


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    make_audio(SAMPLES / "demo_audio.wav")
    make_image(SAMPLES / "demo_avatar.png")


if __name__ == "__main__":
    main()
