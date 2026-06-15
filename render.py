from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable

from media_probe import ProbeError, probe_audio, probe_video, require_tools


LogFn = Callable[[str], None]
ProgressFn = Callable[[float], None]
VIDEO_BITRATE = "2048k"


class RenderError(RuntimeError):
    pass


class RenderCancelled(RenderError):
    pass


class RenderJob:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            process = self._process
        if process and process.poll() is None:
            process.terminate()

    def render(
        self,
        audio_path: str | Path,
        intro_path: str | Path | None,
        loop_path: str | Path | None,
        outro_path: str | Path | None,
        output_dir: str | Path | None = None,
        log: LogFn = print,
        progress: ProgressFn | None = None,
    ) -> Path:
        audio = Path(audio_path)
        intro = Path(intro_path) if intro_path else None
        loop = Path(loop_path) if loop_path else None
        outro = Path(outro_path) if outro_path else None

        ffmpeg, ffprobe = require_tools()
        log(f"ffmpeg: {ffmpeg}")
        log(f"ffprobe: {ffprobe}")

        audio_info = probe_audio(audio, ffprobe)
        videos = {"INTRO": intro, "LOOP": loop, "OUTRO": outro}
        selected = {label: path for label, path in videos.items() if path}
        if not selected:
            raise RenderError("Choose at least one video file")
        if len(selected) == 1:
            only_label, only_path = next(iter(selected.items()))
            loop = only_path
            intro = None
            outro = None
            log(f"Single video mode: using {only_label} as LOOP for the full audio duration")
        elif not loop:
            raise RenderError("LOOP is required when using INTRO or OUTRO with multiple video files")

        intro_info = probe_video(intro, "INTRO", ffprobe) if intro else None
        loop_info = probe_video(loop, "LOOP", ffprobe) if loop else None
        outro_info = probe_video(outro, "OUTRO", ffprobe) if outro else None
        if not loop_info or loop_info.duration <= 0:
            raise ProbeError("LOOP has zero duration")

        intro_duration = intro_info.duration if intro_info else 0.0
        outro_duration = outro_info.duration if outro_info else 0.0
        middle_duration = audio_info.duration - intro_duration - outro_duration
        if middle_duration <= 0:
            raise RenderError("Audio is too short for selected intro/outro")

        output = unique_output_path(audio, output_dir)

        log(f"AUDIO duration: {audio_info.duration:.3f}s")
        if intro_info:
            log(f"INTRO duration: {intro_info.duration:.3f}s")
        log(f"LOOP middle duration: {middle_duration:.3f}s")
        if outro_info:
            log(f"OUTRO duration: {outro_info.duration:.3f}s")
        log(f"Video bitrate: {VIDEO_BITRATE}")
        log(f"Output: {output}")
        log("Step 1/1: rendering final MP4")

        input_args: list[str] = []
        filters: list[str] = []
        labels: list[str] = []
        audio_input_index = 0

        def add_video_input(path: Path, label: str, duration: float, stream_loop: bool = False) -> None:
            nonlocal audio_input_index
            if stream_loop:
                input_args.extend(["-stream_loop", "-1"])
            input_index = audio_input_index
            audio_input_index += 1
            input_args.extend(["-i", str(path)])
            out_label = f"v{len(labels)}"
            filters.append(
                f"[{input_index}:v]{_video_filter()},trim=duration={duration:.6f},"
                f"setpts=PTS-STARTPTS[{out_label}]"
            )
            labels.append(f"[{out_label}]")

        if intro and intro_info:
            add_video_input(intro, "INTRO", intro_info.duration)
        assert loop is not None
        add_video_input(loop, "LOOP", middle_duration, stream_loop=True)
        if outro and outro_info:
            add_video_input(outro, "OUTRO", outro_info.duration)

        audio_index = audio_input_index
        input_args.extend(["-i", str(audio)])
        if len(labels) == 1:
            video_output = labels[0]
            filter_complex = ";".join(filters)
        else:
            video_output = "[v]"
            concat = "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[v]"
            filter_complex = ";".join(filters + [concat])

        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            *input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            video_output,
            "-map",
            f"{audio_index}:a:0",
            "-t",
            f"{audio_info.duration:.6f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            VIDEO_BITRATE,
            "-maxrate",
            VIDEO_BITRATE,
            "-bufsize",
            "4096k",
            "-r",
            "30",
            "-fps_mode",
            "cfr",
            "-c:a",
            "aac",
            "-b:a",
            "320k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output),
        ]
        self._run(cmd, audio_info.duration, log, progress)
        if progress:
            progress(1.0)
        return output

    def _run(
        self,
        cmd: list[str],
        duration: float,
        log: LogFn,
        progress: ProgressFn | None,
    ) -> None:
        log("")
        log("Running:")
        log(_quote_cmd(cmd))
        with self._lock:
            if self._cancelled:
                raise RenderCancelled("Render cancelled")
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            process = self._process

        assert process.stdout is not None
        try:
            for line in process.stdout:
                line = line.rstrip()
                if _handle_progress_line(line, duration, progress):
                    continue
                if line:
                    log(line)
            code = process.wait()
        finally:
            with self._lock:
                self._process = None

        if self._cancelled:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise RenderCancelled("Render cancelled")
        if code != 0:
            raise RenderError(f"ffmpeg failed with exit code {code}")


def unique_output_path(audio_path: str | Path, output_dir: str | Path | None = None) -> Path:
    audio = Path(audio_path)
    folder = Path(output_dir) if output_dir else audio.parent
    if not folder.exists():
        raise RenderError(f"Output folder does not exist: {folder}")
    if not folder.is_dir():
        raise RenderError(f"Output path is not a folder: {folder}")
    base = folder / f"{audio.stem}_video.mp4"
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = folder / f"{audio.stem}_video_{index}.mp4"
        if not candidate.exists():
            return candidate
    raise RenderError("Could not choose an output name. Too many existing files.")


def render_video(
    audio_path: str | Path,
    intro_path: str | Path | None,
    loop_path: str | Path | None,
    outro_path: str | Path | None,
    output_dir: str | Path | None = None,
    log: LogFn = print,
    progress: ProgressFn | None = None,
) -> Path:
    return RenderJob().render(audio_path, intro_path, loop_path, outro_path, output_dir, log, progress)


def _video_filter() -> str:
    return "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p,setsar=1"


def _handle_progress_line(line: str, duration: float, progress: ProgressFn | None) -> bool:
    if "=" not in line:
        return False
    key, value = line.split("=", 1)
    if key in {"out_time_ms", "out_time_us"}:
        try:
            seconds = int(value) / 1_000_000
        except ValueError:
            return True
        if progress and duration > 0:
            progress(max(0.0, min(seconds / duration, 1.0)))
        return True
    return key in {
        "bitrate",
        "dup_frames",
        "drop_frames",
        "fps",
        "frame",
        "out_time",
        "out_time_us",
        "progress",
        "speed",
        "stream_0_0_q",
        "total_size",
    }


def _quote_cmd(cmd: list[str]) -> str:
    return " ".join(_quote_part(part) for part in cmd)


def _quote_part(part: str) -> str:
    if not part or any(char.isspace() for char in part):
        return '"' + part.replace('"', '\\"') + '"'
    return part
