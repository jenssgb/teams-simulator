"""Unit tests for :mod:`teams_simulator.video.waveform`."""

from __future__ import annotations

import numpy as np

from teams_simulator.video.waveform import WaveformAnimator


def _blank(h=720, w=1280) -> np.ndarray:
    return np.full((h, w, 3), 80, dtype=np.uint8)


def test_animator_default_history_is_zero_filled():
    a = WaveformAnimator()
    frame = _blank()
    out = a.draw(frame)
    # Same buffer returned (in-place draw).
    assert out is frame
    assert frame.shape == (720, 1280, 3)


def test_push_level_clamps_to_unit_range():
    a = WaveformAnimator(bar_count=4, fps=30)
    a.push_level(99.0)
    a.push_level(-5.0)
    levels = list(a._history)
    assert max(levels) <= 1.0
    assert min(levels) >= 0.0


def test_high_level_changes_pixels_in_strip_region():
    a = WaveformAnimator(bar_count=12, fps=30)
    frame_silent = _blank()
    frame_loud = _blank()

    # Build state for the loud frame with full-amplitude history.
    for _ in range(60):
        a.push_level(1.0)
    a.draw(frame_loud)

    # Silent reference: a fresh animator, all-zero history.
    a2 = WaveformAnimator(bar_count=12, fps=30)
    a2.draw(frame_silent)

    h = frame_silent.shape[0]
    strip_start = int(h * (1 - 0.18))
    diff = np.abs(frame_loud[strip_start:].astype(int) - frame_silent[strip_start:].astype(int))
    # The loud version must light up significantly more pixels in the strip.
    assert diff.sum() > 0
    # And the loud version's bar-region mean must be brighter (amber bars).
    assert frame_loud[strip_start:].mean() > frame_silent[strip_start:].mean()


def test_top_of_frame_untouched_by_overlay():
    a = WaveformAnimator(bar_count=8, fps=30)
    for _ in range(30):
        a.push_level(0.8)
    frame = _blank()
    before = frame[: int(frame.shape[0] * 0.7)].copy()
    a.draw(frame)
    after = frame[: int(frame.shape[0] * 0.7)]
    np.testing.assert_array_equal(before, after)
