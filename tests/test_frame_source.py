"""Unit tests for :mod:`teams_simulator.video.frame_source`."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from teams_simulator.video.frame_source import (
    FrameSourceError,
    load_image,
    make_placeholder,
)


def _write_solid(path: Path, w: int, h: int, color=(20, 80, 160)) -> None:
    img = np.full((h, w, 3), color, dtype=np.uint8)
    assert cv2.imwrite(str(path), img)


def test_load_image_exact_size(tmp_path: Path):
    src = tmp_path / "p.png"
    _write_solid(src, 1280, 720)
    out = load_image(src, 1280, 720)
    assert out.shape == (720, 1280, 3)
    assert out.dtype == np.uint8


def test_load_image_letterboxes_to_target(tmp_path: Path):
    src = tmp_path / "wide.png"
    _write_solid(src, 1920, 480)  # very wide source
    out = load_image(src, 1280, 720)
    assert out.shape == (720, 1280, 3)
    # The borders should be the default background (16,16,16).
    top_row = out[0, :, :]
    assert (top_row == 16).all()


def test_load_image_pillarboxes_tall_source(tmp_path: Path):
    src = tmp_path / "tall.png"
    _write_solid(src, 480, 1920)
    out = load_image(src, 1280, 720)
    assert out.shape == (720, 1280, 3)
    left_col = out[:, 0, :]
    assert (left_col == 16).all()


def test_load_image_missing_raises(tmp_path: Path):
    with pytest.raises(FrameSourceError):
        load_image(tmp_path / "missing.png", 640, 480)


def test_load_image_corrupt_raises(tmp_path: Path):
    src = tmp_path / "broken.png"
    src.write_bytes(b"not a real png")
    with pytest.raises(FrameSourceError):
        load_image(src, 640, 480)


def test_make_placeholder_has_correct_shape():
    img = make_placeholder(800, 600, "Hello")
    assert img.shape == (600, 800, 3)
    assert img.dtype == np.uint8
    # Background colour applied at corners.
    assert tuple(int(c) for c in img[0, 0, :]) == (32, 32, 48)


def test_load_grayscale_image_promotes_to_bgr(tmp_path: Path):
    src = tmp_path / "gray.png"
    img = np.full((100, 100), 128, dtype=np.uint8)  # 1-channel
    cv2.imwrite(str(src), img)
    out = load_image(src, 200, 200)
    assert out.ndim == 3 and out.shape[2] == 3
