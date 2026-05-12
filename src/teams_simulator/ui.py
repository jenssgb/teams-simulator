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
import re
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
        # Tall enough that the controls + banner are visible without
        # scrolling; log is collapsed by default so we don't need a huge
        # window.
        root.geometry("760x620")
        root.minsize(720, 560)

        # State -----------------------------------------------------------
        self.controller: Optional[SimulatorController] = None
        # Bundled English speech samples for one-click testing.
        self._speech_samples: list[tuple[str, Path]] = self._discover_speech_samples()
        # Default to the FIRST modern business monologue if any have been
        # generated (most relevant for transcript testing); else the first
        # LibriVox classic; else the first short clip; else legacy demo.wav.
        default_audio: str
        default_label: str = ""
        def _pick(prefix: str) -> tuple[str, Path] | None:
            for label, path in self._speech_samples:
                if label.startswith(prefix):
                    return label, path
            return None
        chosen = _pick("💼") or _pick("📚") or _pick("🔬")
        if chosen is not None:
            default_label, default_path = chosen
            default_audio = str(default_path)
        elif DEMO_AUDIO.exists():
            default_audio = str(DEMO_AUDIO)
        else:
            default_audio = ""
        self.audio_path = tk.StringVar(value=default_audio)
        self.sample_var = tk.StringVar(value=default_label)

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
        # Big-status-banner state (UI-side, derived from controller status).
        self.banner_text = tk.StringVar(value="● IDLE")
        self.banner_detail = tk.StringVar(value="Click ▶ Start to begin streaming.")
        # Audio progress (0..100) + countdown ("12:34 remaining" / "Looping").
        self.audio_progress = tk.DoubleVar(value=0.0)
        self.time_remaining = tk.StringVar(value="—")
        # When True the UI is mid-transition (start/stop) and ALL playback
        # buttons are disabled to avoid double-clicks freezing the UI.
        self._busy: bool = False

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
        outer_pad = {"padx": 12, "pady": 6}

        # ── Compact device strip + diagnostics buttons ───────────────────
        dev_row = ttk.Frame(self.root)
        dev_row.pack(fill="x", padx=12, pady=(10, 4))
        self.dev_mic_label = ttk.Label(dev_row, text="🎙 checking…",
                                       font=("Segoe UI", 10))
        self.dev_mic_label.pack(side="left", padx=(0, 16))
        self.dev_cam_label = ttk.Label(dev_row, text="📷 checking…",
                                       font=("Segoe UI", 10))
        self.dev_cam_label.pack(side="left")
        ttk.Button(dev_row, text="⟳", width=3, command=self._refresh_device_status).pack(
            side="right", padx=(2, 0)
        )
        ttk.Button(dev_row, text="🩺", width=3, command=self._run_diagnostics).pack(
            side="right"
        )

        # ── RDP warning (only when actually inside an RDP session) ───────
        import os as _os
        if _os.environ.get("SESSIONNAME", "").upper().startswith("RDP"):
            rdp_strip = tk.Frame(self.root, bg="#fff3cd", bd=0)
            rdp_strip.pack(fill="x", padx=12, pady=(0, 4))
            tk.Label(
                rdp_strip, bg="#fff3cd", fg="#856404",
                text=("⚠  RDP session detected — set 'Play on this computer' "
                      "in your RDP client, or Teams won't see audio."),
                font=("Segoe UI", 9), padx=8, pady=4, anchor="w",
                wraplength=720, justify="left",
            ).pack(fill="x")

        # ── Inputs ───────────────────────────────────────────────────────
        inp_outer = ttk.Frame(self.root)
        inp_outer.pack(fill="x", **outer_pad)

        # Avatar preview pinned right.
        if self._avatars:
            self.avatar_preview = ttk.Label(inp_outer, borderwidth=1,
                                            relief="solid", anchor="center")
            self.avatar_preview.pack(side="right", padx=(12, 0))

        inp = ttk.Frame(inp_outer)
        inp.pack(side="left", fill="x", expand=True)

        bold = ("Segoe UI", 9, "bold")

        # Avatar row
        if self._avatars:
            ttk.Label(inp, text="Avatar", font=bold).grid(
                row=0, column=0, sticky="w", padx=(0, 12), pady=4
            )
            avatar_combo = ttk.Combobox(
                inp, textvariable=self.avatar_var,
                values=[a.label for a in self._avatars],
                state="readonly", width=24,
            )
            avatar_combo.grid(row=0, column=1, sticky="w", pady=4)
            avatar_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_avatar_selected())
            ttk.Button(inp, text="📁", width=3,
                       command=self._pick_image).grid(row=0, column=2, padx=(8, 0), pady=4)
            if not self.avatar_var.get():
                self.avatar_var.set(self._avatars[0].label)
            self._on_avatar_selected()

        # Audio row
        ttk.Label(inp, text="Audio", font=bold).grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=4
        )
        if self._speech_samples:
            sample_combo = ttk.Combobox(
                inp, textvariable=self.sample_var,
                values=[label for label, _ in self._speech_samples],
                state="readonly",
            )
            sample_combo.grid(row=1, column=1, sticky="we", pady=4)
            sample_combo.bind("<<ComboboxSelected>>", self._on_sample_chosen)
        else:
            ttk.Label(inp, text="(no bundled samples found)",
                      foreground="#888888").grid(row=1, column=1, sticky="w", pady=4)
        ttk.Button(inp, text="📁", width=3,
                   command=self._pick_audio).grid(row=1, column=2, padx=(8, 0), pady=4)

        # Muted path under the audio dropdown — keeps the path visible
        # for power-users without screaming an editable Entry at everyone.
        self.audio_path_display = tk.StringVar()
        self._update_audio_display()
        self.audio_path.trace_add("write", lambda *_: self._update_audio_display())
        ttk.Label(inp, textvariable=self.audio_path_display,
                  foreground="#888888", font=("Segoe UI", 8)).grid(
            row=2, column=1, columnspan=2, sticky="w", pady=(0, 4)
        )

        # Loop-audio inline (no dedicated Options panel for ONE checkbox).
        ttk.Checkbutton(inp, text="Loop audio", variable=self.loop_var).grid(
            row=3, column=1, sticky="w", pady=(2, 4)
        )

        inp.columnconfigure(1, weight=1)

        # ── Playback panel ───────────────────────────────────────────────
        pb = ttk.Frame(self.root)
        pb.pack(fill="x", **outer_pad)

        # Slimmer color-coded status banner.
        self.banner_frame = tk.Frame(pb, bg="#e0e0e0", bd=0,
                                     relief="flat", height=52)
        self.banner_frame.pack(fill="x", pady=(0, 6))
        self.banner_frame.pack_propagate(False)
        self.banner_label = tk.Label(
            self.banner_frame, textvariable=self.banner_text,
            bg="#e0e0e0", fg="#333333",
            font=("Segoe UI", 14, "bold"), anchor="w", padx=12,
        )
        self.banner_label.pack(side="top", fill="x", pady=(4, 0))
        self.banner_detail_label = tk.Label(
            self.banner_frame, textvariable=self.banner_detail,
            bg="#e0e0e0", fg="#555555",
            font=("Segoe UI", 9), anchor="w", padx=12, justify="left",
        )
        self.banner_detail_label.pack(side="top", fill="x", pady=(0, 4))

        # Buttons
        btn_row = ttk.Frame(pb)
        btn_row.pack(fill="x", pady=(2, 6))
        self.btn_start = ttk.Button(btn_row, text="▶  Start",
                                    command=self._on_start, width=12)
        self.btn_start.pack(side="left", padx=(0, 4))
        self.btn_pause = ttk.Button(btn_row, text="⏸  Pause",
                                    command=self._on_pause,
                                    state="disabled", width=12)
        self.btn_pause.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(btn_row, text="⏹  Stop",
                                   command=self._on_stop,
                                   state="disabled", width=12)
        self.btn_stop.pack(side="left", padx=4)

        # Progress + position + countdown — three signals, one row each
        # but no labelled sub-headers (the bars speak for themselves).
        prog_row = ttk.Frame(pb)
        prog_row.pack(fill="x", pady=(4, 0))
        self.audio_progress_bar = ttk.Progressbar(
            prog_row, orient="horizontal", mode="determinate",
            maximum=100.0, variable=self.audio_progress,
        )
        self.audio_progress_bar.pack(side="left", fill="x", expand=True)
        self.position_label = ttk.Label(prog_row, textvariable=self.position_text,
                                        font=("Consolas", 10), width=14, anchor="e")
        self.position_label.pack(side="right", padx=(8, 0))
        self.remaining_label = ttk.Label(pb, textvariable=self.time_remaining,
                                         font=("Segoe UI", 9), foreground="#666666")
        self.remaining_label.pack(anchor="e", pady=(2, 0))

        # Live audio level — slim bar, no header.
        self.level_bar = ttk.Progressbar(
            pb, orient="horizontal", mode="determinate",
            maximum=100.0, variable=self.audio_level,
        )
        self.level_bar.pack(fill="x", pady=(8, 0))

        # ── Collapsible log ──────────────────────────────────────────────
        log_outer = ttk.Frame(self.root)
        log_outer.pack(fill="both", expand=True, padx=12, pady=(8, 10))
        toggle_row = ttk.Frame(log_outer)
        toggle_row.pack(fill="x")
        self.log_visible = False
        self._log_lines = 0
        self.log_toggle_text = tk.StringVar(value="▶  Show log")
        self.log_toggle_btn = ttk.Button(
            toggle_row, textvariable=self.log_toggle_text,
            command=self._toggle_log, width=18,
        )
        self.log_toggle_btn.pack(side="left")
        if hasattr(self, "_log_file_path") and self._log_file_path:
            ttk.Label(toggle_row,
                      text=f"  →  {Path(self._log_file_path).name}",
                      foreground="#888888", font=("Segoe UI", 8)).pack(
                side="left", padx=(8, 0)
            )

        self.log_container = ttk.Frame(log_outer)
        self.log_text = tk.Text(self.log_container, height=10, wrap="word",
                                state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(self.log_container, orient="vertical",
                               command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        # log_container intentionally NOT packed yet — collapsed by default.

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Small UI helpers
    # ------------------------------------------------------------------
    def _toggle_log(self) -> None:
        if self.log_visible:
            self.log_container.pack_forget()
            self.log_visible = False
            self._update_log_toggle_text()
        else:
            self.log_container.pack(fill="both", expand=True, pady=(4, 0))
            self.log_visible = True
            self._update_log_toggle_text()

    def _update_log_toggle_text(self) -> None:
        arrow = "▼" if self.log_visible else "▶"
        action = "Hide log" if self.log_visible else "Show log"
        suffix = f"  ({self._log_lines})" if self._log_lines else ""
        self.log_toggle_text.set(f"{arrow}  {action}{suffix}")

    def _update_audio_display(self) -> None:
        p = self.audio_path.get()
        if not p:
            self.audio_path_display.set("(no file selected)")
            return
        try:
            parts = Path(p).parts
            short = "/".join(parts[-2:]) if len(parts) >= 2 else p
        except Exception:
            short = p
        self.audio_path_display.set(short)

    def _pick_audio(self) -> None:
        self._pick_file(self.audio_path,
                        ("Audio", "*.wav *.flac *.ogg *.mp3 *.aiff"))
        # Custom file -> drop the dropdown selection so it doesn't
        # mislead the user about what's actually loaded.
        if self.audio_path.get():
            self.sample_var.set("")

    def _pick_image(self) -> None:
        self._pick_file(self.image_path,
                        ("Image", "*.png *.jpg *.jpeg *.bmp"))

    def _build_avatar_row(self, parent: ttk.LabelFrame, row: int) -> None:
        # Legacy helper kept for backward-compatibility. The new compact
        # _build_ui inlines avatar wiring; this method is unused but
        # remains so external callers (tests, etc.) don't break.
        ttk.Label(parent, text="Avatar:").grid(row=row, column=0, padx=8, pady=4, sticky="ne")
        labels = [a.label for a in self._avatars]
        combo = ttk.Combobox(parent, textvariable=self.avatar_var,
                             values=labels, state="readonly", width=20)
        combo.grid(row=row, column=1, padx=4, pady=4, sticky="w")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_avatar_selected())
        if not hasattr(self, "avatar_preview"):
            self.avatar_preview = ttk.Label(parent, borderwidth=1, relief="solid",
                                            anchor="center")
            self.avatar_preview.grid(row=row, column=2, rowspan=1, padx=8, pady=4,
                                     sticky="e")
        parent.columnconfigure(1, weight=1)
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

        Looks for three things in ``samples/``:

        1. Modern business-context monologues (``samples/long/business_*.mp3``)
           bundled with the repo. Manifest:
           ``samples/long/business_samples.json``.
        2. Long PD audiobooks (``samples/long/*.mp3``) downloaded on demand.
           Manifest: ``samples/long/long_samples.json``.
        3. Short bundled MP3s (``samples/sample_*.mp3``) - committed to git;
           useful for a quick "is the pipeline alive" pipeline check, NOT
           for transcript demos.

        Order in the dropdown:
          💼 Business  (default - transcript-relevant, ~13 min each)
          📚 Classic   (LibriVox public-domain, only if downloaded)
          🔬 Quick test (~10 s pipeline checks, last)
        """
        out: list[tuple[str, Path]] = []
        if not SAMPLES_DIR.exists():
            return out

        long_dir = SAMPLES_DIR / "long"

        def _load_manifest(name: str) -> dict[str, str]:
            path = long_dir / name
            if not path.exists():
                return {}
            try:
                import json
                entries = json.loads(path.read_text(encoding="utf-8"))
                return {
                    str(e["file"]): str(e["label"])
                    for e in entries
                    if isinstance(e, dict) and e.get("file") and e.get("label")
                }
            except (ValueError, OSError):
                return {}

        # 1. Business / modern monologues first (default for transcript demos).
        # Hand-curated pretty titles keep the dropdown narrow regardless
        # of how verbose the manifest label is.
        business_titles = {
            "business_01_ai_in_software_engineering": "AI in software engineering",
            "business_02_cloud_architecture_lessons": "Cloud architecture lessons",
        }
        if long_dir.exists():
            business_labels = _load_manifest("business_samples.json")
            for path in sorted(long_dir.glob("business_*.mp3")):
                title = business_titles.get(path.stem)
                duration = ""
                if title is None:
                    raw = business_labels.get(path.name,
                                              path.stem.replace("_", " ").title())
                    m = re.search(r"\(~?\s*(\d+)\s*min\)", raw)
                    if m:
                        duration = f"(~{m.group(1)} min)"
                        raw = raw[: m.start()]
                    title = raw.split(",")[0].strip(" -·—")
                else:
                    raw = business_labels.get(path.name, "")
                    m = re.search(r"\(~?\s*(\d+)\s*min\)", raw)
                    duration = f"(~{m.group(1)} min)" if m else ""
                label = f"💼  Business — {title}"
                if duration:
                    label = f"{label}   {duration}"
                out.append((label, path))

        # 2. Classics next (LibriVox PD), only if actually downloaded.
        classic_titles = {
            "02_holmes_the_red_headed_league": "Sherlock Holmes — Red-Headed League",
            "03_walden_economy_part1": "Walden — Economy, part 1",
        }
        if long_dir.exists():
            long_labels = _load_manifest("long_samples.json")
            for path in sorted(long_dir.glob("*.mp3")):
                if path.name.startswith("business_"):
                    continue
                title = classic_titles.get(path.stem)
                duration = ""
                if title is None:
                    raw = long_labels.get(path.name,
                                          path.stem.replace("_", " ").title())
                    m = re.search(r"\(~?\s*(\d+)\s*min\)", raw)
                    if m:
                        duration = f"(~{m.group(1)} min)"
                        raw = raw[: m.start()]
                    # Strip any remaining parentheticals like "(Thoreau, ...)".
                    raw = re.sub(r"\s*\([^)]*\)?\s*$", "", raw).rstrip(", -·—")
                    title = raw
                else:
                    raw = long_labels.get(path.name, "")
                    m = re.search(r"~?\s*(\d+)\s*min", raw)
                    duration = f"(~{m.group(1)} min)" if m else ""
                label = f"📚  Classic — {title}"
                if duration:
                    label = f"{label}   {duration}"
                out.append((label, path))

        # 3. Quick-test snippets last. These are ~10 s and only useful for
        # verifying the pipeline (mic → Teams), NOT for transcript demos.
        # We hide the underlying TTS voice name (Guy/Aria/Ryan) — users
        # don't need to know the engine details.
        quick_titles = {
            "sample_1_welcome_guy": "Welcome",
            "sample_2_ted_talk_aria": "TED-style snippet",
            "sample_3_storytelling_ryan": "Storytelling",
        }
        for path in sorted(SAMPLES_DIR.glob("sample_*.mp3")):
            title = quick_titles.get(path.stem)
            if title is None:
                # Fallback: drop trailing voice name "_guy" / "_aria" / "_ryan".
                stem = re.sub(r"_(guy|aria|ryan)$", "", path.stem,
                              flags=re.IGNORECASE)
                parts = stem.split("_", 2)
                title = parts[2].replace("_", " ").title() if len(parts) >= 3 else stem
            duration = _approx_short_duration(path)
            label = f"🔬  Quick test — {title}"
            if duration:
                label = f"{label}   {duration}"
            out.append((label, path))

        return out

    def _build_sample_row(self, parent: ttk.LabelFrame, row: int) -> None:
        ttk.Label(parent, text="Audio sample:").grid(
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
        # Hint that classics are downloaded on demand; business + quick
        # tests ship with the repo.
        hint = "💼 Business + 🔬 Quick test bundled  ·  📚 Classic on demand"
        ttk.Label(parent, text=hint, foreground="gray").grid(
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

        # Mirror everything to a file under Desktop\TeamsSimulatorLogs
        # so the user keeps the log even after the GUI window closes.
        # We enqueue the "Log file: ..." message into the same queue the
        # poll loop drains - log_text doesn't exist yet at this point.
        try:
            from .logsetup import install_file_logging
            log_path = install_file_logging("ui")
            self._log_file_path = log_path
            self.log_queue.put_nowait(f"Log file: {log_path}")
        except Exception as exc:  # pragma: no cover - defensive
            self._log_file_path = None
            log.warning("could not install file logging: %s", exc)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        # Keep last ~2000 lines.
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 2000:
            self.log_text.delete("1.0", f"{line_count - 2000}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        # Update the collapsible-log toggle counter so users notice when
        # there's something new to look at.
        self._log_lines += 1
        if hasattr(self, "log_toggle_text"):
            self._update_log_toggle_text()

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
        # Compact one-liners for the new minimal device strip; full
        # diagnostic message goes to the log so power-users can still
        # see the underlying detail.
        if mic_ok:
            self.dev_mic_label.config(text="🎙 CABLE Output  ✓",
                                      foreground="#0a6f10")
        else:
            self.dev_mic_label.config(text="🎙 mic missing  ✗  · click 🩺",
                                      foreground="#922b21")
        if cam_ok:
            self.dev_cam_label.config(text="📷 OBS Virtual Camera  ✓",
                                      foreground="#0a6f10")
        else:
            self.dev_cam_label.config(text="📷 cam missing  ✗  · click 🩺",
                                      foreground="#922b21")
        # Mirror the verbose status to the log for support / debugging.
        self._append_log(f"DEV    {'OK ' if mic_ok else 'FAIL'}  {mic_msg}")
        self._append_log(f"DEV    {'OK ' if cam_ok else 'FAIL'}  {cam_msg}")

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
    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        if busy:
            self.btn_start.configure(state="disabled")
            self.btn_pause.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            if label:
                self._set_banner("starting", label, "Please wait — audio + virtual devices are coming online.")

    def _set_banner(self, kind: str, text: str, detail: str = "") -> None:
        # Five visual states; colors hand-picked to be calm but unambiguous.
        palette = {
            "idle":     ("● IDLE",        "#e0e0e0", "#333333", "#555555"),
            "starting": ("⏳ STARTING…",  "#fff4cc", "#7a5a00", "#7a5a00"),
            "running":  ("● STREAMING",  "#d4f4d4", "#0a6f10", "#0a6f10"),
            "paused":   ("⏸ PAUSED",     "#fde7b1", "#8a5a00", "#8a5a00"),
            "stopping": ("⏳ STOPPING…",  "#fff4cc", "#7a5a00", "#7a5a00"),
            "error":    ("✖ ERROR",      "#fadbd8", "#922b21", "#922b21"),
        }
        prefix, bg, fg, fg_detail = palette.get(kind, palette["idle"])
        # If caller passed a custom text use it raw; otherwise prepend prefix.
        if not text:
            text = prefix
        elif not text.startswith(prefix.split(" ", 1)[0]):
            text = f"{prefix}   {text}"
        self.banner_text.set(text)
        self.banner_detail.set(detail)
        self.banner_frame.configure(bg=bg)
        self.banner_label.configure(bg=bg, fg=fg)
        self.banner_detail_label.configure(bg=bg, fg=fg_detail)

    def _on_start(self) -> None:
        if self._busy:
            return
        audio = self.audio_path.get().strip()
        image = self.image_path.get().strip()
        if not audio or not Path(audio).is_file():
            self._append_log(f"ERROR: audio file not found: {audio!r}")
            self._set_banner("error", "", f"Audio file not found: {audio or '(empty)'}")
            return
        if not image or not Path(image).is_file():
            self._append_log(f"ERROR: image file not found: {image!r}")
            self._set_banner("error", "", f"Image file not found: {image or '(empty)'}")
            return

        # Heavy lifting (file load + virtual-device probe) MUST happen off
        # the UI thread, otherwise Tk freezes for 1-3 seconds and the
        # window goes "(Not responding)" - exactly what the user reported.
        self._set_busy(True, label=f"Loading {Path(audio).name}…")
        self._append_log(f"INFO   starting: audio={Path(audio).name} image={Path(image).name}")

        loop = self.loop_var.get()
        fps = int(self.fps_var.get())

        def worker():
            try:
                controller = SimulatorController.from_paths(
                    audio_path=audio,
                    image_path=image,
                    loop=loop,
                    fps=fps,
                    width=DEFAULT_VIDEO_WIDTH,
                    height=DEFAULT_VIDEO_HEIGHT,
                )
                controller.add_listener(self._on_status)
                controller.start()
            except Exception as exc:
                log.exception("start failed")
                self.root.after(0, self._on_start_failed, exc)
                return
            self.root.after(0, self._on_start_succeeded, controller, Path(audio).name)

        threading.Thread(target=worker, daemon=True, name="ts-start").start()

    def _on_start_succeeded(self, controller: SimulatorController, audio_name: str) -> None:
        self.controller = controller
        self._busy = False
        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="⏸ Pause")
        self.btn_stop.configure(state="normal")
        loop_hint = "looping" if self.loop_var.get() else "single play"
        self._set_banner("running", "", f"Now streaming: {audio_name}  ·  {loop_hint}")
        self._append_log(f"OK     streaming started ({audio_name})")

    def _on_start_failed(self, exc: Exception) -> None:
        self.controller = None
        self._busy = False
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="⏸ Pause")
        self.btn_stop.configure(state="disabled")
        msg = str(exc)
        # Trim the typical multi-line traceback noise to a single useful line.
        first_line = msg.strip().split("\n")[0][:200]
        self._set_banner("error", "", f"Could not start: {first_line}")
        self._append_log(f"ERROR  start failed: {first_line}")

    def _on_pause(self) -> None:
        if self.controller is None or self._busy:
            return
        status = self.controller.get_status()
        if status.state == State.RUNNING:
            self.controller.pause()
            self.btn_pause.configure(text="▶ Resume")
            self._set_banner("paused", "", "Paused — Teams is still receiving silence + the avatar frame.")
        elif status.state == State.PAUSED:
            self.controller.resume()
            self.btn_pause.configure(text="⏸ Pause")
            audio_name = Path(self.audio_path.get()).name
            self._set_banner("running", "", f"Resumed: {audio_name}")

    def _on_stop(self) -> None:
        if self.controller is None or self._busy:
            return
        self._set_busy(True, label="Stopping…")
        self._set_banner("stopping", "", "Closing virtual mic and camera…")
        controller = self.controller

        def worker():
            try:
                controller.stop()
            except Exception:
                log.exception("stop failed")
            self.root.after(0, self._on_stop_done)

        threading.Thread(target=worker, daemon=True, name="ts-stop").start()

    def _on_stop_done(self) -> None:
        self.controller = None
        self._busy = False
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="⏸ Pause")
        self.btn_stop.configure(state="disabled")
        self.audio_progress.set(0.0)
        self.audio_level.set(0.0)
        self.position_text.set("00:00 / 00:00")
        self.time_remaining.set("—")
        self._set_banner("idle", "", "Click ▶ Start to begin streaming.")
        self._append_log("OK     stopped")

    # ------------------------------------------------------------------
    # Periodic refresh
    # ------------------------------------------------------------------
    def _on_status(self, status: Status) -> None:
        self.root.after(0, self._apply_status, status)

    def _apply_status(self, status: Status) -> None:
        # Be defensive: a single bad listener payload must not kill the UI.
        try:
            self.status_text.set(f"{status.state.value.upper()}: {status.message}")
            if status.state == State.ERROR:
                # Controller flipped to ERROR (e.g. audio device died mid-stream).
                self.controller = None
                self._busy = False
                self.btn_start.configure(state="normal")
                self.btn_pause.configure(state="disabled", text="⏸ Pause")
                self.btn_stop.configure(state="disabled")
                self._set_banner("error", "", status.message or "Stream ended unexpectedly.")
            elif status.state == State.IDLE and not self._busy:
                self.btn_start.configure(state="normal")
                self.btn_pause.configure(state="disabled", text="⏸ Pause")
                self.btn_stop.configure(state="disabled")
        except Exception:
            log.exception("apply_status failed")

    def _poll(self) -> None:
        # Drain the log queue.
        for _ in range(50):
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)

        # Live status (level meter + position + countdown).
        if self.controller is not None and not self._busy:
            try:
                status = self.controller.get_status()
            except Exception:
                log.exception("get_status failed")
                status = None
            if status is not None:
                self.audio_level.set(min(100.0, status.audio_level * 100.0 * 2.0))
                pos = max(0.0, status.audio_position_seconds)
                dur = max(0.0, status.audio_duration_seconds)
                self.position_text.set(f"{_fmt_time(pos)} / {_fmt_time(dur)}")
                if dur > 0.0:
                    pct = min(100.0, (pos / dur) * 100.0)
                    self.audio_progress.set(pct)
                    remaining = max(0.0, dur - pos)
                    if self.loop_var.get():
                        self.time_remaining.set(
                            f"🔁 Looping  ·  {_fmt_time(remaining)} until next loop"
                        )
                    else:
                        self.time_remaining.set(f"⏳ {_fmt_time(remaining)} remaining")
                else:
                    self.audio_progress.set(0.0)
                    self.time_remaining.set("—")
        elif not self._busy:
            self.audio_level.set(0.0)
            # leave audio_progress / position / remaining where stop() left them

        self.root.after(self.POLL_MS, self._poll)

    def _on_close(self) -> None:
        # Don't block the UI thread waiting for stop() to finish — give it
        # a worker + a short grace period, then destroy regardless.
        if self.controller is not None:
            ctrl = self.controller
            self.controller = None
            done = threading.Event()

            def stopper():
                try:
                    ctrl.stop()
                except Exception:
                    log.exception("stop on close failed")
                finally:
                    done.set()

            threading.Thread(target=stopper, daemon=True, name="ts-close").start()
            done.wait(timeout=3.0)
        self.root.destroy()


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _approx_short_duration(path: Path) -> str:
    """Cheap, dependency-free duration estimate for the short MP3 samples.

    For our quick-test snippets we don't want to pull pydub/ffprobe on
    every UI launch just to render a label. The bundled clips are 64
    kbit/s mono Edge-TTS output, so size / bitrate gives a usable hint.
    Returns ``"(~Ns)"`` or ``""`` if the file is missing.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    # Edge-TTS default = 24 kHz mono ~24 KB/s. Empirically: 9-15 s clips
    # land at ~140-225 KB. Using 16 KB/s gives a slight over-estimate
    # which is fine for a hint.
    seconds = max(1, round(size / 16000))
    return f"(~{seconds}s)"


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
