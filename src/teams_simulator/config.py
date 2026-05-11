"""Centralised configuration defaults for the Teams simulator."""

from __future__ import annotations

from dataclasses import dataclass

# Audio defaults — VB-Cable's natural format. Teams downsamples internally
# to 16 kHz mono for transport, but we feed it the studio rate so we don't
# introduce artefacts twice.
DEFAULT_SAMPLE_RATE = 48_000
DEFAULT_CHANNELS = 2
DEFAULT_AUDIO_DTYPE = "float32"

# Audio playback callback uses ~20 ms blocks at 48 kHz: smooth and low-latency
# while leaving headroom for Python's GIL.
DEFAULT_BLOCK_SIZE = 960

# Video defaults — 720p30 is the sweet spot for Teams; higher costs CPU
# without visible improvement on the receiver side.
DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 720
DEFAULT_VIDEO_FPS = 30


@dataclass(frozen=True)
class SimulatorConfig:
    """Runtime configuration for one simulator session."""

    audio_path: str
    image_path: str
    loop: bool = True
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    block_size: int = DEFAULT_BLOCK_SIZE
    video_width: int = DEFAULT_VIDEO_WIDTH
    video_height: int = DEFAULT_VIDEO_HEIGHT
    video_fps: int = DEFAULT_VIDEO_FPS
