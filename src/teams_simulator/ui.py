"""Tkinter UI for the Teams Simulator.

Run with ``python -m teams_simulator`` (which calls :func:`main`).

The UI is intentionally minimal:

* a top status bar showing the state of the two virtual devices,
* file pickers for the audio and avatar image,
* a row of toggles (loop, fps),
* Start / Pause / Stop buttons,
* a live RMS level meter,
* a scrolling log at the bottom.

All long-running work happens in the :class:`SimulatorController` and its
worker threads; the UI thread only updates widgets via
``root.after(...)``.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Optional

from .avatars import BundledAvatar, default_bundled_avatar, list_bundled_avatars
from .config import DEFAULT_VIDEO_FPS, DEFAULT_VIDEO_HEIGHT, DEFAULT_VIDEO_WIDTH
from .devices import (
    CABLE_OUTPUT_NAME,
    OBS_VIRTUAL_CAMERA_NAME,
    DeviceNotFoundError,
    check_obs_virtual_camera,
    find_cable_input,
    find_cable_output,
)
from .sync import SimulatorController, State, Status

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLES_DIR = REPO_ROOT / "samples"
DEMO_AUDIO = SAMPLES_DIR / "demo_audio.wav"
DEMO_IMAGE = SAMPLES_DIR / "demo_avatar.png"

# Preview thumbnail size for the avatar dropdown (square, kept small so
# the window doesn't grow much).
PREVIEW_SIZE = 96


class _TkLogHandler(logging.Handler):
    """Logging handler that pushes records onto a thread-safe queue."""

    def __init__(self, sink: queue.Queue):
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sink.put_nowait(self.format(record))
        except queue.Full:
            pass


class App:
    POLL_MS = 100  # how often we refresh status & drain the log queue

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Teams Simulator")
        root.geometry("760x620")
        root.minsize(700, 540)

        # State -----------------------------------------------------------
        self.controller: Optional[SimulatorController] = None
        # Bundled English speech samples for one-click testing.
        self._speech_samples: list[tuple[str, Path]] = self._discover_speech_samples()
        default_audio: str
        if self._speech_samples:
            default_audio = str(self._speech_samples[0][1])
        elif DEMO_AUDIO.exists():
            default_audio = str(DEMO_AUDIO)
        else:
            default_audio = ""
        self.audio_path = tk.StringVar(value=default_audio)
        self.sample_var = tk.StringVar(
            value=self._speech_samples[0][0] if self._speech_samples else ""
        )

        # Discover bundled avatars first so we can pre-select one as the
        # default image source.
        self._avatars: tuple[BundledAvatar, ...] = list_bundled_avatars()
        default_av = default_bundled_avatar()
        default_image = (
            str(default_av.path) if default_av is not None
            else (str(DEMO_IMAGE) if DEMO_IMAGE.exists() else "")
        )

        self.image_path = tk.StringVar(value=default_image)
        self.avatar_var = tk.StringVar(
            value=default_av.label if default_av is not None else ""
        )
        self.loop_var = tk.BooleanVar(value=True)
        self.fps_var = tk.IntVar(value=DEFAULT_VIDEO_FPS)
        self.status_text = tk.StringVar(value="Idle")
        self.audio_level = tk.DoubleVar(value=0.0)
        self.position_text = tk.StringVar(value="00:00 / 00:00")

        # Cache for PhotoImage thumbnails so they're not garbage-collected.
        self._preview_cache: dict[str, tk.PhotoImage] = {}
        self._preview_image: tk.PhotoImage | None = None

        self.log_queue: queue.Queue[str] = queue.Queue(maxsize=500)
        self._setup_logging()

        self._build_ui()
        self._refresh_device_status()
        self.root.after(self.POLL_MS, self._poll)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # Device status panel ---------------------------------------------
        dev_frame = ttk.LabelFrame(self.root, text="Virtual devices")
        dev_frame.pack(fill="x", **pad)

        self.dev_mic_label = ttk.Label(dev_frame, text="checking…")
        self.dev_mic_label.pack(anchor="w", padx=8, pady=2)
        self.dev_cam_label = ttk.Label(dev_frame, text="checking…")
        self.dev_cam_label.pack(anchor="w", padx=8, pady=2)
        # Surface the most common gotcha early: RDP sessions hide local
        # virtual audio devices from WASAPI -> Teams cannot see VB-Cable.
        import os as _os
        if (_os.environ.get("SESSIONNAME", "").upper().startswith("RDP")):
            self.dev_rdp_label = ttk.Label(
                dev_frame,
                text=(
                    "⚠ Running inside an RDP session. Windows RDP redirects audio and HIDES "
                    "local virtual cables from Teams. Connect via the console session "
                    "(Hyper-V Connect / Cloud-PC portal) or set 'Play on remote computer' in mstsc."
                ),
                foreground="dark orange",
                wraplength=720,
            )
            self.dev_rdp_label.pack(anchor="w", padx=8, pady=(2, 0))
        self.dev_hint_label = ttk.Label(
            dev_frame,
            text="If a device is missing, run setup\\install.ps1 (as Administrator), or click Diagnostics for details.",
            foreground="gray",
        )
        self.dev_hint_label.pack(anchor="w", padx=8, pady=(0, 4))
        button_row = ttk.Frame(dev_frame)
        button_row.pack(anchor="e", padx=8, pady=4)
        ttk.Button(button_row, text="🩺 Diagnostics", command=self._run_diagnostics).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(button_row, text="Re-check", command=self._refresh_device_status).pack(
            side="left"
        )

        # Files panel ------------------------------------------------------
        files_frame = ttk.LabelFrame(self.root, text="Inputs")
        files_frame.pack(fill="x", **pad)

        # Avatar dropdown + preview. Only built when there is at least one
        # bundled avatar — otherwise the panel collapses cleanly.
        next_row = 0
        if self._avatars:
            self._build_avatar_row(files_frame, row=next_row)
            next_row += 1
        if self._speech_samples:
            self._build_sample_row(files_frame, row=next_row)
            next_row += 1
        audio_row = next_row
        file_row = next_row + 1

        self._build_file_row(files_frame, audio_row, "Audio file:", self.audio_path,
                             ("Audio", "*.wav *.flac *.ogg *.mp3 *.aiff"))
        self._build_file_row(files_frame, file_row, "Custom image:", self.image_path,
                             ("Image", "*.png *.jpg *.jpeg *.bmp"))

        # Options panel ----------------------------------------------------
        opt_frame = ttk.LabelFrame(self.root, text="Options")
        opt_frame.pack(fill="x", **pad)
        ttk.Checkbutton(opt_frame, text="Loop audio", variable=self.loop_var).grid(
            row=0, column=0, padx=8, pady=4, sticky="w"
        )
        ttk.Label(opt_frame, text="FPS:").grid(row=0, column=1, padx=(20, 4), sticky="e")
        ttk.Spinbox(opt_frame, from_=10, to=60, textvariable=self.fps_var, width=5).grid(
            row=0, column=2, padx=(0, 8), sticky="w"
        )

        # Controls + status -----------------------------------------------
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", **pad)
        self.btn_start = ttk.Button(ctrl_frame, text="▶ Start", command=self._on_start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_pause = ttk.Button(ctrl_frame, text="⏸ Pause", command=self._on_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(ctrl_frame, text="⏹ Stop", command=self._on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        ttk.Label(ctrl_frame, textvariable=self.position_text).pack(side="right", padx=8)

        meter_frame = ttk.LabelFrame(self.root, text="Live audio level")
        meter_frame.pack(fill="x", **pad)
        self.level_bar = ttk.Progressbar(
            meter_frame, orient="horizontal", mode="determinate",
            maximum=100.0, variable=self.audio_level,
        )
        self.level_bar.pack(fill="x", padx=8, pady=8)

        ttk.Label(self.root, textvariable=self.status_text, foreground="navy").pack(
            anchor="w", padx=12, pady=(0, 4)
        )

        # Log pane ---------------------------------------------------------
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=8, wrap="word", state="disabled",
                                font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_avatar_row(self, parent: ttk.LabelFrame, row: int) -> None:
        ttk.Label(parent, text="Avatar:").grid(row=row, column=0, padx=8, pady=4, sticky="ne")

        labels = [a.label for a in self._avatars]
        combo = ttk.Combobox(parent, textvariable=self.avatar_var,
                             values=labels, state="readonly", width=20)
        combo.grid(row=row, column=1, padx=4, pady=4, sticky="w")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_avatar_selected())

        # Preview label spans the same column as the file rows below so
        # it lines up nicely.
        self.avatar_preview = ttk.Label(parent, borderwidth=1, relief="solid",
                                        anchor="center")
        self.avatar_preview.grid(row=row, column=2, rowspan=1, padx=8, pady=4,
                                 sticky="e")

        parent.columnconfigure(1, weight=1)
        # Make sure there's a sensible initial selection.
        if self._avatars and not self.avatar_var.get():
            self.avatar_var.set(self._avatars[0].label)
        self._on_avatar_selected()

    def _on_avatar_selected(self) -> None:
        label = self.avatar_var.get()
        match = next((a for a in self._avatars if a.label == label), None)
        if match is None:
            return
        self.image_path.set(str(match.path))
        self._show_preview(match)

    def _show_preview(self, avatar: BundledAvatar) -> None:
        cached = self._preview_cache.get(avatar.id)
        if cached is None:
            try:
                cached = self._make_preview(avatar.path)
            except tk.TclError as exc:
                log.warning("could not load preview for %s: %s", avatar.id, exc)
                self.avatar_preview.configure(image="", text=avatar.label,
                                              width=12)
                return
            self._preview_cache[avatar.id] = cached
        self._preview_image = cached
        self.avatar_preview.configure(image=cached, text="")

    def _make_preview(self, path: Path) -> tk.PhotoImage:
        # Tk's built-in PhotoImage handles PNG natively (Tk 8.6+) but
        # has no resize — we use ``subsample`` for a quick downscale.
        img = tk.PhotoImage(file=str(path))
        # Source is 1024x1024; we want ~PREVIEW_SIZE.
        factor = max(1, img.width() // PREVIEW_SIZE)
        if factor > 1:
            img = img.subsample(factor, factor)
        return img

    def _build_file_row(
        self, parent: ttk.LabelFrame, row: int, label: str,
        var: tk.StringVar, filetypes: tuple[str, str],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=8, pady=4, sticky="e")
        ttk.Entry(parent, textvariable=var, width=60).grid(
            row=row, column=1, padx=4, pady=4, sticky="we"
        )
        ttk.Button(
            parent, text="Browse…",
            command=lambda v=var, f=filetypes: self._pick_file(v, f),
        ).grid(row=row, column=2, padx=4, pady=4)
        parent.columnconfigure(1, weight=1)

    @staticmethod
    def _discover_speech_samples() -> list[tuple[str, Path]]:
        """Return ``[(label, path), ...]`` for every bundled English sample.

        Filenames are expected to look like
        ``sample_<n>_<title-with-underscores>.mp3`` and the human label
        is reconstructed from the filename.
        """
        out: list[tuple[str, Path]] = []
        if not SAMPLES_DIR.exists():
            return out
        for path in sorted(SAMPLES_DIR.glob("sample_*.mp3")):
            stem = path.stem
            parts = stem.split("_", 2)
            if len(parts) >= 3 and parts[0] == "sample":
                label = f"{parts[1]}. {parts[2].replace('_', ' ').title()}"
            else:
                label = stem
            out.append((label, path))
        return out

    def _build_sample_row(self, parent: ttk.LabelFrame, row: int) -> None:
        ttk.Label(parent, text="Bundled sample:").grid(
            row=row, column=0, padx=8, pady=4, sticky="e"
        )
        combo = ttk.Combobox(
            parent,
            textvariable=self.sample_var,
            values=[label for label, _ in self._speech_samples],
            state="readonly",
            width=58,
        )
        combo.grid(row=row, column=1, padx=4, pady=4, sticky="we")
        combo.bind("<<ComboboxSelected>>", self._on_sample_chosen)
        ttk.Label(parent, text="(English TTS)", foreground="gray").grid(
            row=row, column=2, padx=4, pady=4, sticky="w"
        )

    def _on_sample_chosen(self, _event: object = None) -> None:
        label = self.sample_var.get()
        for sample_label, sample_path in self._speech_samples:
            if sample_label == label:
                self.audio_path.set(str(sample_path))
                self._append_log(f"Selected bundled sample: {sample_path.name}")
                break

    def _pick_file(self, var: tk.StringVar, filetypes: tuple[str, str]) -> None:
        initial = Path(var.get()).parent if var.get() else SAMPLES_DIR
        path = filedialog.askopenfilename(
            initialdir=str(initial),
            filetypes=[filetypes, ("All files", "*.*")],
        )
        if path:
            var.set(path)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _setup_logging(self) -> None:
        handler = _TkLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s",
                                              datefmt="%H:%M:%S"))
        root_logger = logging.getLogger("teams_simulator")
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        # Keep last ~2000 lines.
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 2000:
            self.log_text.delete("1.0", f"{line_count - 2000}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Device status
    # ------------------------------------------------------------------
    def _refresh_device_status(self) -> None:
        # Run probes in a worker so the UI never blocks on PortAudio /
        # pyvirtualcam initialisation.
        def probe():
            mic_ok = mic_msg = cam_ok = cam_msg = None
            try:
                cable_in = find_cable_input()
                cable_out = find_cable_output()
                mic_ok = True
                if cable_out is not None:
                    mic_msg = (f"OK  Mic ready (Teams: select '{cable_out.name}'); "
                               f"writing to '{cable_in.name}'")
                else:
                    mic_msg = (f"OK  '{cable_in.name}' present, but no '{CABLE_OUTPUT_NAME}' "
                               "device — Teams won't see a microphone.")
                    mic_ok = False
            except DeviceNotFoundError as exc:
                mic_ok = False
                mic_msg = f"FAIL  {exc}".replace("\n", " ")

            try:
                check_obs_virtual_camera()
                cam_ok = True
                cam_msg = f"OK  Cam ready (Teams: select '{OBS_VIRTUAL_CAMERA_NAME}')"
            except DeviceNotFoundError as exc:
                cam_ok = False
                cam_msg = f"FAIL  {exc}".replace("\n", " ")

            self.root.after(0, self._apply_device_status, mic_ok, mic_msg, cam_ok, cam_msg)

        threading.Thread(target=probe, daemon=True).start()

    def _apply_device_status(self, mic_ok: bool, mic_msg: str, cam_ok: bool, cam_msg: str) -> None:
        self.dev_mic_label.config(text="🎤 " + mic_msg, foreground=("dark green" if mic_ok else "red"))
        self.dev_cam_label.config(text="📷 " + cam_msg, foreground=("dark green" if cam_ok else "red"))

    def _run_diagnostics(self) -> None:
        # Spawn setup\diagnose.ps1 in a NEW PowerShell window. It writes
        # a full report to setup\_logs\diagnose-*.txt AND copies it to
        # the clipboard, so the user can just paste back to support.
        import subprocess

        repo_root = Path(__file__).resolve().parents[2]
        diag = repo_root / "setup" / "diagnose.ps1"
        if not diag.exists():
            self._append_log("ERROR  diagnose.ps1 not found - re-run installer to update")
            return
        self._append_log(f"INFO   running diagnostics: {diag}")
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", str(diag),
                ],
                cwd=str(repo_root),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            self._append_log("INFO   a new console will pop up; the report is also copied to your clipboard.")
        except Exception as exc:
            self._append_log(f"ERROR  could not start diagnostics: {exc}")

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        audio = self.audio_path.get().strip()
        image = self.image_path.get().strip()
        if not audio or not Path(audio).is_file():
            self._append_log(f"ERROR: audio file not found: {audio!r}")
            return
        if not image or not Path(image).is_file():
            self._append_log(f"ERROR: image file not found: {image!r}")
            return

        try:
            self.controller = SimulatorController.from_paths(
                audio_path=audio,
                image_path=image,
                loop=self.loop_var.get(),
                fps=int(self.fps_var.get()),
                width=DEFAULT_VIDEO_WIDTH,
                height=DEFAULT_VIDEO_HEIGHT,
            )
            self.controller.add_listener(self._on_status)
            self.controller.start()
        except Exception as exc:
            self._append_log(f"ERROR: {exc}")
            self.controller = None
            return

        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="⏸ Pause")
        self.btn_stop.configure(state="normal")

    def _on_pause(self) -> None:
        if self.controller is None:
            return
        status = self.controller.get_status()
        if status.state == State.RUNNING:
            self.controller.pause()
            self.btn_pause.configure(text="▶ Resume")
        elif status.state == State.PAUSED:
            self.controller.resume()
            self.btn_pause.configure(text="⏸ Pause")

    def _on_stop(self) -> None:
        if self.controller is None:
            return
        self.controller.stop()
        self.controller = None
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="⏸ Pause")
        self.btn_stop.configure(state="disabled")

    # ------------------------------------------------------------------
    # Periodic refresh
    # ------------------------------------------------------------------
    def _on_status(self, status: Status) -> None:
        self.root.after(0, self._apply_status, status)

    def _apply_status(self, status: Status) -> None:
        self.status_text.set(f"{status.state.value.upper()}: {status.message}")
        if status.state in (State.IDLE, State.ERROR):
            self.btn_start.configure(state="normal")
            self.btn_pause.configure(state="disabled", text="⏸ Pause")
            self.btn_stop.configure(state="disabled")

    def _poll(self) -> None:
        # Drain the log queue.
        for _ in range(50):
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)

        # Live status (level meter + position).
        if self.controller is not None:
            status = self.controller.get_status()
            self.audio_level.set(min(100.0, status.audio_level * 100.0 * 2.0))
            self.position_text.set(
                f"{_fmt_time(status.audio_position_seconds)} / "
                f"{_fmt_time(status.audio_duration_seconds)}"
            )
        else:
            self.audio_level.set(0.0)
            self.position_text.set("00:00 / 00:00")

        self.root.after(self.POLL_MS, self._poll)

    def _on_close(self) -> None:
        if self.controller is not None:
            try:
                self.controller.stop()
            except Exception:
                log.exception("stop on close failed")
        self.root.destroy()


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def main() -> int:
    root = tk.Tk()
    App(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
