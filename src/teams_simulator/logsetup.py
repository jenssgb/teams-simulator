"""Centralised log-directory + file-handler setup.

Every Teams Simulator entry point (UI, CLI, helper scripts) routes its
log output to the SAME directory:

    1. ``$TEAMS_SIMULATOR_LOG_DIR``  (escape hatch)
    2. ``<UserDesktop>/TeamsSimulatorLogs``       (preferred)
    3. ``<PublicDesktop>/TeamsSimulatorLogs``     (per-machine fallback)
    4. ``<RepoRoot>/setup/_logs``                 (dev fallback)

so that a user can find every log file in one place on the Desktop,
even if a terminal window closes after a crash.
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
import tempfile
from pathlib import Path

ENV_VAR = "TEAMS_SIMULATOR_LOG_DIR"


def _candidate_dirs() -> list[Path]:
    out: list[Path] = []

    env_override = os.environ.get(ENV_VAR)
    if env_override:
        out.append(Path(env_override))

    # Per-user Desktop. On Windows we can ask SHGetFolderPath via ctypes
    # but Path.home() / 'Desktop' covers 99% of cases including OneDrive
    # rerouting (because OneDrive moves the literal Desktop folder).
    home = Path.home()
    user_desktop_candidates = [home / "Desktop"]
    # OneDrive-redirected Desktop: scan for any "OneDrive*\Desktop"
    for entry in home.iterdir() if home.is_dir() else []:
        try:
            if entry.is_dir() and entry.name.lower().startswith("onedrive"):
                cand = entry / "Desktop"
                if cand.is_dir():
                    user_desktop_candidates.insert(0, cand)
        except OSError:
            continue
    for desktop in user_desktop_candidates:
        out.append(desktop / "TeamsSimulatorLogs")

    # Public Desktop (visible to every user on the box).
    public = os.environ.get("PUBLIC")
    if public:
        out.append(Path(public) / "Desktop" / "TeamsSimulatorLogs")

    # Repo-root fallback (only useful when running from a checkout).
    here = Path(__file__).resolve()
    out.append(here.parent.parent.parent / "setup" / "_logs")

    # Last resort.
    out.append(Path(tempfile.gettempdir()) / "TeamsSimulatorLogs")

    return out


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / f".write-probe-{os.getpid()}"
        probe.write_text("ok", encoding="ascii")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def get_log_dir() -> Path:
    """Return the resolved log directory, creating it if necessary."""
    for cand in _candidate_dirs():
        if _writable(cand):
            return cand
    # If absolutely nothing worked, return the first candidate so callers
    # at least have *some* path to report.
    return _candidate_dirs()[0]


def install_file_logging(component: str,
                         level: int = logging.INFO) -> Path:
    """Attach a rotating-friendly FileHandler to the ``teams_simulator``
    logger and return the log-file path.

    Safe to call multiple times - duplicate handlers are detected by
    file path and skipped.
    """
    log_dir = get_log_dir()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"app-{component}-{stamp}-pid{os.getpid()}.log"

    root = logging.getLogger("teams_simulator")
    root.setLevel(min(root.level or level, level))

    # Skip if a handler for this exact file already exists.
    for h in root.handlers:
        if isinstance(h, logging.FileHandler) and \
           Path(getattr(h, "baseFilename", "")).resolve() == log_path.resolve():
            return log_path

    try:
        handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError as exc:
        # Don't crash the app over a logging glitch.
        sys.stderr.write(f"[logsetup] could not open {log_path}: {exc}\n")
        return log_path

    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(handler)
    root.info("file logging started: %s", log_path)
    return log_path


def install_crash_handler(component: str) -> Path | None:
    """Install Python `faulthandler` writing to the log directory so
    even hard interpreter crashes (segfaults, fatal threads) leave a
    trace on disk. Returns the dump-file path (or None if unavailable).
    """
    try:
        import faulthandler
    except ImportError:
        return None

    log_dir = get_log_dir()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dump_path = log_dir / f"crash-{component}-{stamp}-pid{os.getpid()}.log"
    try:
        # Keep the file open for the lifetime of the process.
        fh = open(dump_path, "w", encoding="utf-8")
        faulthandler.enable(fh)
    except OSError as exc:
        sys.stderr.write(f"[logsetup] faulthandler unavailable: {exc}\n")
        return None
    return dump_path


def write_startup_error(component: str, exc: BaseException) -> Path | None:
    """Last-resort: dump an unhandled exception during process startup
    to the log directory so the user still has something to look at if
    the GUI never came up.
    """
    import traceback
    log_dir = get_log_dir()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = log_dir / f"startup-error-{component}-{stamp}-pid{os.getpid()}.log"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Teams Simulator startup error ({component})\n")
            f.write(f"timestamp: {datetime.datetime.now().isoformat()}\n")
            f.write(f"python:    {sys.version}\n")
            f.write(f"executable:{sys.executable}\n\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except OSError:
        return None
    return path
