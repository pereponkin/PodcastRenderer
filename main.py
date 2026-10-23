from __future__ import annotations

import queue
import re
import sys
import threading
import tkinter as tk
import time
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from tkinterdnd2 import DND_FILES, TkinterDnD

from render import (
    FINALIZING_PROGRESS, MUX_START_PROGRESS, AudioConversionRequired, RenderCancelled, RenderJob,
    StageUpdate,
)


APP_NAME = "Podcast Renderer"
APP_VERSION = "1.6.1"
APP_TITLE = f"{APP_NAME} {APP_VERSION}"

UI_BACKGROUND = "#F4F5F0"
UI_SURFACE = "#FFFFFF"
UI_INK = "#182523"
UI_ACCENT = "#007F73"
UI_ACCENT_HOVER = "#006D63"
UI_ACCENT_PRESSED = "#005E55"
UI_MUTED = "#60716B"
UI_BORDER = "#DCE4DF"
UI_TRACK = "#E7EEEA"


class App(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        icon = app_path("assets", "brand", "PodcastRenderer.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass
        window_icon = app_path("assets", "brand", "app-icon.png")
        if window_icon.exists() and sys.platform != "win32":
            self.window_icon = tk.PhotoImage(file=str(window_icon))
            self.iconphoto(True, self.window_icon)
        self.geometry("920x680")
        self.minsize(800, 620)
        self._configure_styles()
        self.log_queue: queue.Queue[tuple[str, str | tuple[str, dict[str, str]] | StageUpdate]] = queue.Queue()
        self.entries: dict[str, tk.StringVar] = {}
        self.input_fields: dict[str, ttk.Entry] = {}
        self.render_button: ttk.Button | None = None
        self.progress_canvas: tk.Canvas | None = None
        self.cancel_button: ttk.Button | None = None
        self.current_job: RenderJob | None = None
        self.render_started_at: float | None = None
        self.progress_value = 0.0
        self.stage_update: StageUpdate | None = None
        self.eta_deadline: float | None = None
        self.mux_started_at: float | None = None
        self._closing = False
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_log)

    def _configure_styles(self) -> None:
        self.configure(background=UI_BACKGROUND)
        families = tkfont.families(self)
        preferred = {"win32": "Segoe UI", "darwin": "Helvetica"}.get(sys.platform, "Ubuntu")
        self.ui_font = preferred if preferred in families else tkfont.nametofont("TkDefaultFont", self).actual("family")
        tkfont.nametofont("TkDefaultFont", self).configure(family=self.ui_font, size=11)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=UI_BACKGROUND)
        style.configure("TLabel", background=UI_BACKGROUND, foreground=UI_INK)
        style.configure("Surface.TFrame", background=UI_SURFACE)
        style.configure("Surface.TLabel", background=UI_SURFACE, foreground=UI_INK)
        style.configure("Title.TLabel", font=(self.ui_font, 24, "bold"))
        style.configure("Tagline.TLabel", foreground=UI_ACCENT, font=(self.ui_font, 11))
        style.configure("Muted.TLabel", foreground=UI_MUTED, font=(self.ui_font, 10))
        style.configure("Section.TLabel", background=UI_SURFACE, font=(self.ui_font, 12, "bold"))
        style.configure("Hint.TLabel", background=UI_SURFACE, foreground=UI_MUTED, font=(self.ui_font, 10))
        style.configure(
            "TEntry", background=UI_SURFACE, fieldbackground=UI_SURFACE, foreground=UI_INK,
            bordercolor=UI_BORDER, lightcolor=UI_BORDER, darkcolor=UI_BORDER,
            padding=(10, 6), insertcolor=UI_INK, selectbackground=UI_ACCENT,
            selectforeground=UI_SURFACE,
        )
        style.map(
            "TEntry", bordercolor=[("focus", UI_ACCENT)],
            lightcolor=[("focus", UI_ACCENT)], darkcolor=[("focus", UI_ACCENT)],
            background=[("readonly", UI_TRACK), ("disabled", UI_TRACK)],
            fieldbackground=[("readonly", UI_TRACK), ("disabled", UI_TRACK)],
            foreground=[("disabled", UI_MUTED)],
        )
        style.configure(
            "TButton", background=UI_SURFACE, foreground=UI_INK,
            bordercolor=UI_BORDER, lightcolor=UI_SURFACE, darkcolor=UI_SURFACE,
            padding=(16, 7), font=(self.ui_font, 10), focusthickness=1,
            focuscolor=UI_ACCENT,
        )
        style.map(
            "TButton", background=[("disabled", UI_TRACK), ("pressed", UI_BORDER), ("active", UI_TRACK)],
            foreground=[("disabled", UI_MUTED)], bordercolor=[("focus", UI_ACCENT)],
            lightcolor=[("pressed", UI_BORDER)], darkcolor=[("pressed", UI_BORDER)],
        )
        style.configure(
            "Accent.TButton", background=UI_ACCENT, foreground=UI_SURFACE,
            bordercolor=UI_ACCENT, lightcolor=UI_ACCENT, darkcolor=UI_ACCENT,
            padding=(18, 11), font=(self.ui_font, 11, "bold"), focuscolor=UI_SURFACE,
        )
        accent_fills = [("disabled", UI_TRACK), ("pressed", UI_ACCENT_PRESSED), ("active", UI_ACCENT_HOVER)]
        style.map(
            "Accent.TButton", background=accent_fills, lightcolor=accent_fills, darkcolor=accent_fills,
            foreground=[("disabled", UI_MUTED), ("!disabled", UI_SURFACE)],
            bordercolor=[("focus", UI_INK), ("!focus", UI_ACCENT)],
        )
        style.configure(
            "Vertical.TScrollbar", background=UI_BORDER, troughcolor=UI_SURFACE,
            bordercolor=UI_SURFACE, lightcolor=UI_SURFACE, darkcolor=UI_SURFACE,
            arrowcolor=UI_MUTED, width=12,
        )
        style.map(
            "Vertical.TScrollbar", background=[("pressed", UI_MUTED), ("active", UI_BORDER)],
            lightcolor=[("pressed", UI_BORDER)], darkcolor=[("pressed", UI_BORDER)],
        )

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = ttk.Frame(self, padding=(24, 18, 24, 14))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        brand = app_path("assets", "brand", "logo.png")
        if brand.exists():
            self.brand_image = tk.PhotoImage(file=str(brand)).subsample(2, 2)
            ttk.Label(header, image=self.brand_image).grid(row=0, column=0, rowspan=2, padx=(0, 18))
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(
            header, text="One loop render. The whole episode.", style="Tagline.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(3, 0))
        ttk.Label(header, text=f"Version {APP_VERSION}", style="Muted.TLabel").grid(row=0, column=2, sticky="e")

        sources = ttk.Frame(self, style="Surface.TFrame", padding=(20, 14))
        sources.grid(row=1, column=0, padx=24, sticky="ew")
        sources.columnconfigure(1, weight=1)
        ttk.Label(sources, text="Source files", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            sources, text="Choose at least one video; Loop is needed when combining clips.\n"
            "Drop files onto their fields. Output defaults to the audio folder.",
            style="Hint.TLabel", justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 10))

        filetypes = {
            "AUDIO": [
                (
                    "Audio files",
                    "*.wav *.mp3 *.flac *.aiff *.aif *.m4a *.aac "
                    "*.mp4 *.mov *.m4v *.mkv *.avi *.webm *.mpeg *.mpg "
                    "*.ts *.mts *.m2ts *.wmv",
                ),
                ("All files", "*.*"),
            ],
            "INTRO": [("Video files", "*.mp4 *.mov *.m4v"), ("All files", "*.*")],
            "LOOP": [("Video files", "*.mp4 *.mov *.m4v"), ("All files", "*.*")],
            "OUTRO": [("Video files", "*.mp4 *.mov *.m4v"), ("All files", "*.*")],
        }
        display_labels = {
            "AUDIO": "Audio (required)",
            "INTRO": "Intro (optional)",
            "LOOP": "Loop",
            "OUTRO": "Outro (optional)",
        }
        for row, label in enumerate(("AUDIO", "INTRO", "LOOP", "OUTRO"), start=2):
            ttk.Label(sources, text=f"{display_labels[label]}:", style="Surface.TLabel").grid(
                row=row, column=0, padx=(0, 16), pady=4, sticky="w",
            )
            value = tk.StringVar()
            self.entries[label] = value
            entry = ttk.Entry(sources, textvariable=value)
            self.input_fields[label] = entry
            entry.grid(row=row, column=1, pady=4, sticky="nsew")
            entry.drop_target_register(DND_FILES)
            entry.dnd_bind("<<Drop>>", lambda event, key=label: self._drop_file(event, key))
            ttk.Button(
                sources,
                text="Choose",
                command=lambda key=label: self._choose(key, filetypes[key]),
            ).grid(row=row, column=2, padx=(12, 0), pady=4)

        ttk.Label(sources, text="Output:", style="Surface.TLabel").grid(row=6, column=0, padx=(0, 16), pady=(12, 0), sticky="w")
        output = tk.StringVar()
        self.entries["OUTPUT"] = output
        self.input_fields["OUTPUT"] = ttk.Entry(sources, textvariable=output)
        self.input_fields["OUTPUT"].grid(row=6, column=1, pady=(12, 0), sticky="nsew")
        ttk.Button(sources, text="Choose", command=self._choose_output).grid(row=6, column=2, padx=(12, 0), pady=(12, 0))

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, padx=24, pady=(12, 12), sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.render_button = ttk.Button(actions, text="Render", command=self._render, style="Accent.TButton")
        self.render_button.grid(row=0, column=0, padx=(0, 12), sticky="ew")

        self.progress_canvas = tk.Canvas(actions, height=46, background=UI_BACKGROUND, highlightthickness=0)
        self.progress_canvas.bind("<Configure>", lambda _event: self._draw_progress())
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self._cancel, state="disabled", width=12)
        self.cancel_button.grid(row=0, column=1, sticky="ew")

        activity = ttk.Frame(self, style="Surface.TFrame", padding=(20, 10))
        activity.grid(row=3, column=0, padx=24, pady=(0, 24), sticky="nsew")
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(1, weight=1)
        ttk.Label(activity, text="Activity", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.log = tk.Text(
            activity, wrap="word", height=6, background=UI_SURFACE, foreground=UI_MUTED,
            font=(self.ui_font, 10), relief="flat", borderwidth=0, highlightthickness=0,
            insertbackground=UI_INK, selectbackground=UI_ACCENT, selectforeground=UI_SURFACE,
        )
        self.log.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(activity, orient="vertical", command=self.log.yview)
        scroll.grid(row=1, column=1, padx=(8, 0), sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self._append("Ready. Render stages and the saved file path will appear here.")

    def _choose(self, key: str, filetypes: list[tuple[str, str]]) -> None:
        selected = filedialog.askopenfilename(title=f"Choose {key}", filetypes=filetypes)
        if selected:
            self._set_source(key, Path(selected))

    def _drop_file(self, event: tk.Event, key: str) -> None:
        paths = self.tk.splitlist(event.data)
        if len(paths) != 1 or not Path(paths[0]).is_file():
            messagebox.showerror("Invalid drop", "Drop one file onto its source field.")
            return
        self._set_source(key, Path(paths[0]))

    def _set_source(self, key: str, selected: Path) -> None:
        self.entries[key].set(str(selected))
        if key == "AUDIO" and not self.entries["OUTPUT"].get().strip():
            self.entries["OUTPUT"].set(str(selected.parent))
        if key in {"INTRO", "LOOP", "OUTRO"}:
            self._autofill_video_siblings(selected, key)

    def _autofill_video_siblings(self, selected: Path, selected_slot: str) -> None:
        for key, path in find_video_siblings(selected, selected_slot).items():
            if key != selected_slot and not self.entries[key].get().strip():
                self.entries[key].set(str(path))

    def _choose_output(self) -> None:
        initial = self.entries["OUTPUT"].get().strip() or None
        selected = filedialog.askdirectory(title="Choose output folder", initialdir=initial)
        if selected:
            self.entries["OUTPUT"].set(selected)

    def _render(self) -> None:
        paths = {key: value.get().strip() for key, value in self.entries.items()}
        if not paths["OUTPUT"] and paths["AUDIO"]:
            paths["OUTPUT"] = str(Path(paths["AUDIO"]).parent)
            self.entries["OUTPUT"].set(paths["OUTPUT"])
        missing = [key for key in ("AUDIO", "OUTPUT") if not paths[key]]
        if missing:
            self._show_input_error(missing[0], "Missing files", "Choose: " + ", ".join(missing))
            return
        video_keys = [key for key in ("INTRO", "LOOP", "OUTRO") if paths[key]]
        if not video_keys:
            self._show_input_error("LOOP", "Missing video", "Choose at least one video file.")
            return
        if len(video_keys) > 1 and "LOOP" not in video_keys:
            self._show_input_error("LOOP", "Missing LOOP", "LOOP is required when using multiple video files.")
            return
        for key, value in paths.items():
            if not value:
                continue
            if key == "OUTPUT":
                continue
            if not Path(value).exists():
                self._show_input_error(key, "File not found", f"{key} file does not exist:\n{value}")
                return
        output = Path(paths["OUTPUT"])
        if not output.exists() or not output.is_dir():
            self._show_input_error("OUTPUT", "Output folder not found", f"OUTPUT folder does not exist:\n{output}")
            return

        self._start_render(paths)

    def _show_input_error(self, key: str, title: str, message: str) -> None:
        messagebox.showerror(title, message)
        self.input_fields[key].focus_set()
        self.input_fields[key].selection_range(0, "end")

    def _start_render(self, paths: dict[str, str], allow_audio_conversion: bool = False) -> None:
        self.log.delete("1.0", "end")
        self._append(APP_TITLE)
        self._set_busy(True)
        self.render_started_at = time.monotonic()
        self.progress_value = 0.0
        self.stage_update = None
        self.eta_deadline = None
        self.mux_started_at = None
        self._draw_progress()
        self.current_job = RenderJob(
            cancel_error=lambda line: self.log_queue.put(("cancel_error", line))
        )
        threading.Thread(target=self._render_worker,
                         args=(paths, allow_audio_conversion), daemon=True).start()

    def _render_worker(self, paths: dict[str, str], allow_audio_conversion: bool = False) -> None:
        try:
            assert self.current_job is not None
            output = self.current_job.render(
                paths["AUDIO"],
                paths["INTRO"],
                paths["LOOP"],
                paths["OUTRO"],
                paths["OUTPUT"],
                log=lambda line: self.log_queue.put(("log", line)),
                progress=lambda value: self.log_queue.put(("progress", str(value))),
                stage_progress=lambda value: self.log_queue.put(("stage", value)),
                allow_audio_conversion=allow_audio_conversion,
            )
        except AudioConversionRequired as exc:
            self.log_queue.put(("audio_conversion", (str(exc), paths)))
        except RenderCancelled as exc:
            self.log_queue.put(("cancelled", str(exc)))
        except Exception as exc:
            self.log_queue.put(("error", str(exc)))
        else:
            self.log_queue.put(("done", str(output)))

    def _cancel(self) -> None:
        if self.current_job:
            self._append("Cancelling…")
            self.current_job.cancel()

    def _on_close(self) -> None:
        if self._closing:
            return
        if not self.current_job:
            self.destroy()
            return
        self._closing = True
        self._append("Closing: cancelling render…")
        if self.cancel_button:
            self.cancel_button.configure(state="disabled")
        self.current_job.cancel()

    def _drain_log(self) -> None:
        try:
            while True:
                kind, text = self.log_queue.get_nowait()
                if kind == "audio_conversion":
                    message, paths = text
                    cancelled = self.current_job is None or self.current_job.cancelled
                    self._set_busy(False)
                    if self._closing:
                        self.destroy()
                        return
                    if not cancelled and messagebox.askokcancel(
                        "Audio precision", message, icon="warning", default="cancel",
                    ):
                        self._start_render(paths, allow_audio_conversion=True)
                elif kind == "log":
                    self._append(text)
                elif kind == "progress":
                    self.progress_value = float(text)
                    self._update_eta()
                elif kind == "stage":
                    self.stage_update = text
                elif kind == "cancelled":
                    self._append("")
                    self._append(text)
                    self._set_busy(False)
                    if self._closing:
                        self.destroy()
                        return
                elif kind == "error":
                    self._append("")
                    self._append("ERROR: " + text)
                    self._set_busy(False)
                    if self._closing:
                        self.destroy()
                        return
                    messagebox.showerror("Render failed", text)
                elif kind == "cancel_error":
                    self._append("")
                    self._append("ERROR: " + text)
                    if self._closing:
                        self._closing = False
                        if self.cancel_button:
                            self.cancel_button.configure(state="normal")
                    messagebox.showerror("Cancel failed", text)
                elif kind == "done":
                    self._append("")
                    self._append("DONE: " + text)
                    if self._closing:
                        self._set_busy(False)
                        self.destroy()
                        return
                    self._draw_progress()
                    messagebox.showinfo("Render complete", f"Saved:\n{text}")
                    self._set_busy(False)
        except queue.Empty:
            pass
        if self.render_started_at is not None:
            self._draw_progress()
        self.after(100, self._drain_log)

    def _update_eta(self) -> None:
        value = self.progress_value
        if self.render_started_at is None or value < MUX_START_PROGRESS:
            return
        now = time.monotonic()
        if self.mux_started_at is None:
            self.mux_started_at = now
        fraction = (value - MUX_START_PROGRESS) / (FINALIZING_PROGRESS - MUX_START_PROGRESS)
        elapsed = now - self.mux_started_at
        if elapsed < 5 or not 0.02 <= fraction < 1.0:
            return
        candidate = self.mux_started_at + elapsed / fraction
        if self.eta_deadline is None:
            self.eta_deadline = candidate
        else:
            self.eta_deadline += 0.2 * (candidate - self.eta_deadline)

    def _append(self, line: str) -> None:
        self.log.insert("end", line + "\n")
        self.log.see("end")

    def _set_busy(self, busy: bool) -> None:
        focused = self.focus_get()
        if self.render_button:
            if busy:
                self.render_button.grid_remove()
            else:
                self.render_button.grid()
        if self.progress_canvas:
            if busy:
                self.progress_canvas.grid(row=0, column=0, padx=(0, 12), sticky="ew")
            else:
                self.progress_canvas.grid_remove()
        if self.cancel_button:
            self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy and focused is self.render_button and self.cancel_button:
            self.cancel_button.focus_set()
        elif not busy and focused is self.cancel_button and self.render_button:
            self.render_button.focus_set()
        if not busy:
            self.current_job = None
            self.render_started_at = None
            self.eta_deadline = None
            self.mux_started_at = None

    def _draw_progress(self) -> None:
        canvas = self.progress_canvas
        if not canvas:
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        value = max(0.0, min(self.progress_value, 1.0))
        canvas.create_rectangle(0, 0, width, height, fill=UI_BACKGROUND, outline="")
        bar_top = max(0, height - 8)
        canvas.create_rectangle(0, bar_top, width, height, fill=UI_TRACK, outline="")
        update = self.stage_update
        if update:
            total_weight = sum(stage.weight for stage in update.stages)
            left = 0.0
            for index, stage in enumerate(update.stages):
                right = left + width * stage.weight / total_weight
                fraction = (1.0 if index < update.index else
                            update.fraction if index == update.index else 0.0)
                if fraction:
                    canvas.create_rectangle(left, bar_top, left + (right - left) * fraction,
                                            height, fill=UI_ACCENT, outline="")
                if index:
                    canvas.create_line(left, bar_top, left, height, fill=UI_BACKGROUND, width=2)
                left = right
        canvas.create_text(width // 2, bar_top // 2, text=self._progress_text(value), fill=UI_INK, font="TkDefaultFont")

    def _progress_text(self, value: float) -> str:
        update = self.stage_update
        stage = (f"{update.stages[update.index].name} "
                 f"({update.index + 1} / {len(update.stages)}) | ") if update else ""
        if not self.render_started_at:
            return stage + "00:00 elapsed / --:-- remaining"
        elapsed = max(0.0, time.monotonic() - self.render_started_at)
        if value >= 1.0:
            return f"{stage}{_format_time(elapsed)} elapsed / complete"
        if FINALIZING_PROGRESS <= value < 1.0:
            return f"{stage}{_format_time(elapsed)} elapsed / finalizing"
        remaining = (max(0.0, self.eta_deadline - time.monotonic())
                     if self.eta_deadline is not None else None)
        return f"{stage}{_format_time(elapsed)} elapsed / {_format_time(remaining)} remaining"


def _format_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def app_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).joinpath(*parts)
    return Path(__file__).resolve().parent.joinpath(*parts)


def find_video_siblings(selected: Path, selected_slot: str | None = None) -> dict[str, Path]:
    markers = {
        "INTRO": ("intro",),
        "LOOP": ("loop",),
        "OUTRO": ("outro", "out"),
    }
    selected_marker = _find_marker(selected.stem, markers)
    if not selected_marker:
        return {}
    if selected_slot and selected_marker[0] != selected_slot:
        return {}

    result: dict[str, Path] = {selected_marker[0]: selected}
    for key, variants in markers.items():
        if key == selected_marker[0]:
            continue
        for variant in variants:
            candidate = _replace_marker(selected, selected_marker[1], variant)
            if candidate.exists():
                result[key] = candidate
                break
    return result


def _find_marker(stem: str, markers: dict[str, tuple[str, ...]]) -> tuple[str, str] | None:
    for key, variants in markers.items():
        for variant in variants:
            if _marker_pattern(variant).search(stem):
                return key, variant
    return None


def _replace_marker(path: Path, old: str, new: str) -> Path:
    stem = _marker_pattern(old).sub(lambda match: _match_case(new, match.group(0)), path.stem, count=1)
    return path.with_name(stem + path.suffix)


def _marker_pattern(marker: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(marker)}(?![A-Za-z0-9])", re.IGNORECASE)


def _match_case(value: str, sample: str) -> str:
    if sample.isupper():
        return value.upper()
    if sample[:1].isupper():
        return value.capitalize()
    return value.lower()


if __name__ == "__main__":
    app = App()
    if sys.argv[1:] == ["--smoke-test"]:
        visible = []

        def finish_smoke_test() -> None:
            visible.append(app.winfo_viewable())
            app.destroy()

        app.after(500, finish_smoke_test)
        app.mainloop()
        if visible != [1]:
            raise SystemExit("Main window did not become visible")
    else:
        app.mainloop()
