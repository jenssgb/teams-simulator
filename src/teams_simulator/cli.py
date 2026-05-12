"""Headless / scripted CLI for the Teams Simulator.

Example::

    teams-sim --audio meeting.wav --image avatar.png --loop --fps 30

If you want the GUI instead, see :mod:`teams_simulator.ui`
(``python -m teams_simulator``).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from .config import (
    DEFAULT_VIDEO_FPS,
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_VIDEO_WIDTH,
)
from .devices import DeviceNotFoundError
from .sync import SimulatorController, State

log = logging.getLogger("teams_simulator.cli")


def _parse_resolution(value: str) -> tuple[int, int]:
    if "x" not in value:
        raise argparse.ArgumentTypeError(f"resolution must be WIDTHxHEIGHT, got '{value}'")
    w, h = value.lower().split("x", 1)
    return int(w), int(h)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="teams-sim",
        description="Stream a prepared audio file + avatar image into Microsoft Teams "
        "as a virtual microphone and camera.",
    )
    p.add_argument(
        "-a", "--audio", required=True,
        help="Path to the audio file (WAV/FLAC/OGG; MP3 if ffmpeg is installed).",
    )
    p.add_argument(
        "-i", "--image", required=True,
        help="Path to the avatar image (PNG/JPG).",
    )
    p.add_argument(
        "--loop", action=argparse.BooleanOptionalAction, default=True,
        help="Loop the audio (default: --loop).",
    )
    p.add_argument(
        "--fps", type=int, default=DEFAULT_VIDEO_FPS,
        help=f"Video frames per second (default: {DEFAULT_VIDEO_FPS}).",
    )
    p.add_argument(
        "--resolution", type=_parse_resolution,
        default=(DEFAULT_VIDEO_WIDTH, DEFAULT_VIDEO_HEIGHT),
        help=f"Video resolution WIDTHxHEIGHT (default: {DEFAULT_VIDEO_WIDTH}x{DEFAULT_VIDEO_HEIGHT}).",
    )
    p.add_argument(
        "--duration", type=float, default=None,
        help="Stop automatically after N seconds (default: run until Ctrl+C).",
    )
    p.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="-v for INFO, -vv for DEBUG.",
    )
    return p


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Mirror to file under Desktop\TeamsSimulatorLogs.
    try:
        from .logsetup import install_file_logging
        log_path = install_file_logging("cli", level=level)
        logging.getLogger("teams_simulator.cli").info("log file: %s", log_path)
    except Exception as exc:  # pragma: no cover
        logging.getLogger("teams_simulator.cli").warning(
            "could not install file logging: %s", exc)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _setup_logging(args.verbose)

    audio_path = Path(args.audio).resolve()
    image_path = Path(args.image).resolve()
    width, height = args.resolution

    if not audio_path.is_file():
        print(f"error: audio file not found: {audio_path}", file=sys.stderr)
        return 2
    if not image_path.is_file():
        print(f"error: image file not found: {image_path}", file=sys.stderr)
        return 2

    controller = SimulatorController.from_paths(
        audio_path=str(audio_path),
        image_path=str(image_path),
        loop=args.loop,
        fps=args.fps,
        width=width,
        height=height,
    )

    # Print compact status updates when state changes.
    last_state: State | None = None

    def on_status(status):
        nonlocal last_state
        if status.state != last_state:
            log.info("state -> %s (%s)", status.state.value, status.message)
            last_state = status.state

    controller.add_listener(on_status)

    # Graceful Ctrl+C / SIGTERM.
    stop_requested = {"flag": False}

    def _handle_signal(signum, _frame):
        log.info("Received signal %s, stopping...", signum)
        stop_requested["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    try:
        controller.start()
    except DeviceNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Streaming. Press Ctrl+C to stop.")
    print(f"  Audio : {audio_path.name}")
    print(f"  Image : {image_path.name}  ({width}x{height} @ {args.fps} fps)")
    print(f"  Loop  : {args.loop}")
    print("Pick the following devices in Teams:")
    print("  Microphone : 'CABLE Output (VB-Audio Virtual Cable)'")
    print("  Camera     : 'OBS Virtual Camera'")

    started_at = time.monotonic()
    try:
        while not stop_requested["flag"]:
            time.sleep(0.25)
            status = controller.get_status()
            if status.state in (State.IDLE, State.ERROR):
                break
            if args.duration is not None and (time.monotonic() - started_at) >= args.duration:
                log.info("Duration reached (%.1fs)", args.duration)
                break
    finally:
        controller.stop()

    final = controller.get_status()
    if final.state == State.ERROR:
        print(f"error: {final.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
