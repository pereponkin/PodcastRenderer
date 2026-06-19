from __future__ import annotations

import queue
import re
import sys
import threading
import tkinter as tk
import time
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from render import RenderCancelled, RenderJob


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Podcast Renderer")
        icon = app_path("assets", "Podcast Renderer.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self.geometry("820x500")
        self.minsize(720, 420)
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.entries: dict[str, tk.StringVar] = {}
        self.render_button: ttk.Button | None = None
        self.progress_canvas: tk.Canvas | None = None
        self.cancel_button: ttk.Button | None = None
        self.current_job: RenderJob | None = None
        self.render_started_at: float | None = None
        self.progress_value = 0.0
        self._build()
        self.after(100, self._drain_log)

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(6, weight=1)

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
            "AUDIO": "Audio",
            "INTRO": "Intro",
            "LOOP": "Loop",
            "OUTRO": "Outro",
        }
        for row, label in enumerate(("AUDIO", "INTRO", "LOOP", "OUTRO")):
            ttk.Label(self, text=f"{display_labels[label]}:").grid(row=row, column=0, padx=10, pady=6, sticky="w")
            value = tk.StringVar()
            self.entries[label] = value
            ttk.Entry(self, textvariable=value).grid(row=row, column=1, padx=6, pady=6, sticky="ew")
            ttk.Button(
                self,
                text="Choose",
                command=lambda key=label: self._choose(key, filetypes[key]),
            ).grid(row=row, column=2, padx=10, pady=6)

        ttk.Label(self, text="OUTPUT:").grid(row=4, column=0, padx=10, pady=6, sticky="w")
        output = tk.StringVar()
        self.entries["OUTPUT"] = output
        ttk.Entry(self, textvariable=output).grid(row=4, column=1, padx=6, pady=6, sticky="ew")
        ttk.Button(self, text="Choose", command=self._choose_output).grid(row=4, column=2, padx=10, pady=6)

        self.render_button = ttk.Button(self, text="Render", command=self._render)
        self.render_button.grid(row=5, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        self.progress_canvas = tk.Canvas(self, height=26, highlightthickness=1, highlightbackground="#9a9a9a")
        self.progress_canvas.bind("<Configure>", lambda _event: self._draw_progress())
        self.cancel_button = ttk.Button(self, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.grid(row=5, column=2, padx=10, pady=10, sticky="ew")

        self.log = tk.Text(self, wrap="word", height=14)
        self.log.grid(row=6, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="nsew")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.log.yview)
        scroll.grid(row=6, column=3, pady=(0, 10), sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    def _choose(self, key: str, filetypes: list[tuple[str, str]]) -> None:
        selected = filedialog.askopenfilename(title=f"Choose {key}", filetypes=filetypes)
        if selected:
            self.entries[key].set(selected)
            if key == "AUDIO" and not self.entries["OUTPUT"].get().strip():
                self.entries["OUTPUT"].set(str(Path(selected).parent))
            if key in {"INTRO", "LOOP", "OUTRO"}:
                self._autofill_video_siblings(Path(selected))

    def _autofill_video_siblings(self, selected: Path) -> None:
        for key, path in find_video_siblings(selected).items():
            if not self.entries[key].get().strip():
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
            messagebox.showerror("Missing files", "Choose: " + ", ".join(missing))
            return
        video_keys = [key for key in ("INTRO", "LOOP", "OUTRO") if paths[key]]
        if not video_keys:
            messagebox.showerror("Missing video", "Choose at least one video file.")
            return
        if len(video_keys) > 1 and "LOOP" not in video_keys:
            messagebox.showerror("Missing LOOP", "LOOP is required when using multiple video files.")
            return
        for key, value in paths.items():
            if not value:
                continue
            if key == "OUTPUT":
                continue
            if not Path(value).exists():
                messagebox.showerror("File not found", f"{key} file does not exist:\n{value}")
                return
        output = Path(paths["OUTPUT"])
        if not output.exists() or not output.is_dir():
            messagebox.showerror("Output folder not found", f"OUTPUT folder does not exist:\n{output}")
            return

        self.log.delete("1.0", "end")
        self._set_busy(True)
        self.render_started_at = time.monotonic()
        self.progress_value = 0.0
        self._draw_progress()
        self.current_job = RenderJob()
        thread = threading.Thread(target=self._render_worker, args=(paths,), daemon=True)
        thread.start()

    def _render_worker(self, paths: dict[str, str]) -> None:
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
            )
        except RenderCancelled as exc:
            self.log_queue.put(("cancelled", str(exc)))
        except Exception as exc:
            self.log_queue.put(("error", str(exc)))
        else:
            self.log_queue.put(("done", str(output)))

    def _cancel(self) -> None:
        if self.current_job:
            self._append("Cancelling...")
            self.current_job.cancel()

    def _drain_log(self) -> None:
        try:
            while True:
                kind, text = self.log_queue.get_nowait()
                if kind == "log":
                    self._append(text)
                elif kind == "progress":
                    self.progress_value = float(text)
                    self._draw_progress()
                elif kind == "cancelled":
                    self._append("")
                    self._append(text)
                    self._set_busy(False)
                elif kind == "error":
                    self._append("")
                    self._append("ERROR: " + text)
                    self._set_busy(False)
                    messagebox.showerror("Render failed", text)
                elif kind == "done":
                    self._append("")
                    self._append("DONE: " + text)
                    self._set_busy(False)
                    messagebox.showinfo("Render complete", f"Saved:\n{text}")
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _append(self, line: str) -> None:
        self.log.insert("end", line + "\n")
        self.log.see("end")

    def _set_busy(self, busy: bool) -> None:
        if self.render_button:
            if busy:
                self.render_button.grid_remove()
            else:
                self.render_button.grid()
        if self.progress_canvas:
            if busy:
                self.progress_canvas.grid(row=5, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
            else:
                self.progress_canvas.grid_remove()
        if self.cancel_button:
            self.cancel_button.configure(state="normal" if busy else "disabled")
        if not busy:
            self.current_job = None
            self.render_started_at = None

    def _draw_progress(self) -> None:
        canvas = self.progress_canvas
        if not canvas:
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        value = max(0.0, min(self.progress_value, 1.0))
        fill_width = int(width * value)
        canvas.create_rectangle(0, 0, width, height, fill="#f3f3f3", outline="")
        if fill_width > 0:
            canvas.create_rectangle(0, 0, fill_width, height, fill="#4f8bd6", outline="")
        canvas.create_text(width // 2, height // 2, text=self._progress_text(value), fill="#111111")

    def _progress_text(self, value: float) -> str:
        if not self.render_started_at:
            return "00:00 elapsed / --:-- remaining"
        elapsed = max(0.0, time.monotonic() - self.render_started_at)
        if value <= 0:
            remaining = None
        else:
            remaining = max(0.0, elapsed * (1.0 - value) / value)
        return f"{_format_time(elapsed)} elapsed / {_format_time(remaining)} remaining"


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


def find_video_siblings(selected: Path) -> dict[str, Path]:
    markers = {
        "INTRO": ("intro",),
        "LOOP": ("loop",),
        "OUTRO": ("outro", "out"),
    }
    selected_marker = _find_marker(selected.stem, markers)
    if not selected_marker:
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
    App().mainloop()
