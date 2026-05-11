"""High-level controller that ties the audio player and video streamer together.

The controller is the public API used by both the CLI and the Tkinter UI.
It is responsible for:

* loading audio + image,
* starting / pausing / stopping both subsystems atomically,
* wiring the audio player's RMS level into the video streamer's overlay,
* surfacing errors and status in a UI-friendly way.

It is thread-safe: ``start``/``stop``/``pause``/``resume`` may be called
from the UI thread while the audio + video threads run in the background.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .audio.loader import load_audio
from .audio.player import AudioPlayer
from .config import (
    DEFAULT_BLOCK_SIZE,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_VIDEO_FPS,
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_VIDEO_WIDTH,
    SimulatorConfig,
)
from .devices import (
    CABLE_INPUT_NAME,
    DeviceNotFoundError,
    check_obs_virtual_camera,
    find_cable_input,
)
from .video.streamer import VideoStreamer

log = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class Status:
    state: State
    message: str = ""
    audio_position_seconds: float = 0.0
    audio_duration_seconds: float = 0.0
    audio_level: float = 0.0


StatusListener = Callable[[Status], None]


class SimulatorController:
    """Coordinates ``AudioPlayer`` and ``VideoStreamer``."""

    def __init__(self, config: SimulatorConfig):
        self._config = config
        self._lock = threading.RLock()
        self._state: State = State.IDLE
        self._message: str = "Ready."
        self._listeners: list[StatusListener] = []

        self._audio: Optional[AudioPlayer] = None
        self._video: Optional[VideoStreamer] = None

    # ------------------------------------------------------------------
    # Listeners (UI subscribes here for status updates)
    # ------------------------------------------------------------------
    def add_listener(self, listener: StatusListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: StatusListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def get_status(self) -> Status:
        with self._lock:
            audio = self._audio
            return Status(
                state=self._state,
                message=self._message,
                audio_position_seconds=(audio.get_position() / audio.sample_rate) if audio else 0.0,
                audio_duration_seconds=audio.duration if audio else 0.0,
                audio_level=audio.get_current_level() if audio else 0.0,
            )

    def _emit(self) -> None:
        # Snapshot listeners under the lock, fire outside it.
        with self._lock:
            listeners = list(self._listeners)
        status = self.get_status()
        for cb in listeners:
            try:
                cb(status)
            except Exception:
                log.exception("Status listener raised")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._state in (State.RUNNING, State.PAUSED):
                return
            try:
                self._do_start_locked()
                self._state = State.RUNNING
                self._message = "Streaming to Teams."
            except Exception as exc:
                self._state = State.ERROR
                self._message = f"Failed to start: {exc}"
                self._cleanup_locked()
                self._emit()
                raise
        self._emit()

    def stop(self) -> None:
        with self._lock:
            self._cleanup_locked()
            if self._state != State.ERROR:
                self._state = State.IDLE
                self._message = "Stopped."
        self._emit()

    def pause(self) -> None:
        with self._lock:
            if self._state != State.RUNNING:
                return
            if self._audio is not None:
                self._audio.pause()
            self._state = State.PAUSED
            self._message = "Paused."
        self._emit()

    def resume(self) -> None:
        with self._lock:
            if self._state != State.PAUSED:
                return
            if self._audio is not None:
                self._audio.resume()
            self._state = State.RUNNING
            self._message = "Streaming to Teams."
        self._emit()

    # ------------------------------------------------------------------
    # Setup + teardown (callers hold the lock)
    # ------------------------------------------------------------------
    def _do_start_locked(self) -> None:
        cfg = self._config

        log.info("Loading audio: %s", cfg.audio_path)
        data, sr = load_audio(
            cfg.audio_path,
            target_sample_rate=cfg.sample_rate,
            target_channels=cfg.channels,
        )

        log.info("Resolving virtual microphone (%s)", CABLE_INPUT_NAME)
        cable = find_cable_input()  # raises DeviceNotFoundError

        log.info("Resolving OBS Virtual Camera")
        check_obs_virtual_camera()  # raises DeviceNotFoundError

        # ------------------------------------------------------------------
        # Build the players. They aren't started yet — we start audio first
        # so its callback is producing levels by the time video opens its
        # camera (avoids the first frame having a zero-bar overlay).
        # ------------------------------------------------------------------
        audio = AudioPlayer(
            data=data,
            sample_rate=sr,
            device=cable.index,
            loop=cfg.loop,
            block_size=cfg.block_size,
            on_finished=self._on_audio_finished,
        )

        video = VideoStreamer(
            image_path=cfg.image_path,
            width=cfg.video_width,
            height=cfg.video_height,
            fps=cfg.video_fps,
            level_source=audio,
        )

        audio.start()
        try:
            video.start()
        except Exception:
            audio.stop()
            raise

        self._audio = audio
        self._video = video

    def _cleanup_locked(self) -> None:
        if self._video is not None:
            try:
                self._video.stop()
            except Exception:
                log.exception("Video stop failed")
            self._video = None
        if self._audio is not None:
            try:
                self._audio.stop()
            except Exception:
                log.exception("Audio stop failed")
            self._audio = None

    def _on_audio_finished(self) -> None:
        # Called from the audio thread when loop=False and EOF is reached.
        log.info("Audio finished naturally")
        with self._lock:
            self._cleanup_locked()
            self._state = State.IDLE
            self._message = "Audio playback finished."
        self._emit()

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------
    @classmethod
    def from_paths(
        cls,
        audio_path: str,
        image_path: str,
        loop: bool = True,
        fps: int = DEFAULT_VIDEO_FPS,
        width: int = DEFAULT_VIDEO_WIDTH,
        height: int = DEFAULT_VIDEO_HEIGHT,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        block_size: int = DEFAULT_BLOCK_SIZE,
    ) -> "SimulatorController":
        return cls(
            SimulatorConfig(
                audio_path=audio_path,
                image_path=image_path,
                loop=loop,
                video_fps=fps,
                video_width=width,
                video_height=height,
                sample_rate=sample_rate,
                channels=channels,
                block_size=block_size,
            )
        )


# Re-export for convenience.
__all__ = ["SimulatorController", "State", "Status", "DeviceNotFoundError"]
