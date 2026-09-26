from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Callable

from media_probe import (
    PROBE_TIMEOUT_SECONDS,
    ProbeError,
    StreamInfo,
    probe_audio,
    probe_video,
    require_tools,
)


LogFn = Callable[[str], None]
ProgressFn = Callable[[float], None]
VIDEO_CRF = 20
VIDEO_MAXRATE = "8000k"
VIDEO_BUFSIZE = "64000k"
VIDEO_PRESET = "veryslow"
GOP_SECONDS = 4
CANCEL_KILL_TIMEOUT = 5.0
FINALIZING_PROGRESS = 0.999
LOSSLESS_AUDIO_CODECS = {
    "alac", "als", "ape", "flac", "mlp", "shorten", "tak", "truehd",
    "tta", "wavpack", "wmalossless",
}


class RenderError(RuntimeError):
    pass


class RenderCancelled(RenderError):
    pass


class RenderJob:
    def __init__(self, cancel_error: LogFn | None = None) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False
        self._lock = threading.Lock()
        self._cancel_error = cancel_error

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            process = self._process
        if process and process.poll() is None:
            kill_delay = CANCEL_KILL_TIMEOUT
            try:
                process.terminate()
            except OSError:
                if process.poll() is not None:
                    return
                kill_delay = 0.0
            watchdog = threading.Timer(
                kill_delay,
                _kill_if_running,
                args=(process, self._cancel_error),
            )
            watchdog.daemon = True
            watchdog.start()

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
        audio = Path(audio_path).expanduser().resolve()
        intro = Path(intro_path).expanduser().resolve() if intro_path else None
        loop = Path(loop_path).expanduser().resolve() if loop_path else None
        outro = Path(outro_path).expanduser().resolve() if outro_path else None
        output_dir = Path(output_dir).expanduser().resolve() if output_dir else None

        ffmpeg, ffprobe = require_tools()
        log(f"ffmpeg: {ffmpeg}")
        log(f"ffprobe: {ffprobe}")

        audio_info = probe_audio(audio, ffprobe, runner=self._run_probe)
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

        intro_info = probe_video(intro, "INTRO", ffprobe, runner=self._run_probe) if intro else None
        loop_info = probe_video(loop, "LOOP", ffprobe, runner=self._run_probe) if loop else None
        outro_info = probe_video(outro, "OUTRO", ffprobe, runner=self._run_probe) if outro else None
        if not loop_info:
            raise ProbeError("LOOP has zero duration")

        video_infos = [info for info in (intro_info, loop_info, outro_info) if info]
        target_width, target_height, target_fps = choose_video_target(video_infos)
        target_fps_text = _format_frame_rate(target_fps)
        audio_codec_args, audio_decision = _audio_output_args(audio_info)

        intro_duration = intro_info.duration if intro_info else 0.0
        outro_duration = outro_info.duration if outro_info else 0.0
        middle_duration = audio_info.duration - intro_duration - outro_duration
        if middle_duration <= 0:
            raise RenderError("Audio is too short for selected intro/outro")

        partial_output = _partial_output_path(audio, output_dir)

        log(f"AUDIO duration: {audio_info.duration:.3f}s")
        if intro_info:
            log(f"INTRO duration: {intro_info.duration:.3f}s")
        log(f"LOOP middle duration: {middle_duration:.3f}s")
        if outro_info:
            log(f"OUTRO duration: {outro_info.duration:.3f}s")
        log(f"Output video: {target_width}x{target_height} at {target_fps_text} fps")
        log(f"Video rate control: CRF {VIDEO_CRF}, maxrate {VIDEO_MAXRATE}, "
            f"bufsize {VIDEO_BUFSIZE}")
        log(f"Video encoder: libx264 {VIDEO_PRESET}, closed GOP every {GOP_SECONDS}s")
        log(f"Audio: {audio_decision}")
        log(f"Output folder: {partial_output.parent}")
        video_filter = (
            f"setpts=PTS-STARTPTS,{_video_filter(target_width, target_height, target_fps_text)},"
            f"setpts=N/({target_fps_text}*TB)"
        )
        video_options = [
            "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", video_filter,
            "-r", target_fps_text, "-fps_mode", "cfr",
        ]
        encoder_options = [
            *_video_encoder_args(
                target_fps,
                ["-crf", str(VIDEO_CRF), "-maxrate", VIDEO_MAXRATE,
                 "-bufsize", VIDEO_BUFSIZE],
            ),
            "-progress", "pipe:1", "-nostats",
        ]

        def stage(start: float, end: float) -> ProgressFn | None:
            return (lambda value: progress(start + (end - start) * value)) if progress else None

        def encode(source: Path, destination: Path, duration: float,
                   start: float, end: float, frames: int | None = None) -> int:
            cmd = [ffmpeg, "-n", "-nostdin", "-hide_banner", "-i", str(source),
                   *video_options]
            if frames is not None:
                cmd.extend(["-frames:v", str(frames)])
            cmd.extend([*encoder_options, str(destination)])
            count = self._run(cmd, duration, log, stage(start, end))
            if count <= 0 or (frames is not None and count != frames):
                raise RenderError(f"Unexpected frame count while encoding {source}: {count}")
            if progress:
                progress(end)
            return count

        try:
            with tempfile.TemporaryDirectory(prefix="podcast-renderer-") as temporary:
                work = Path(temporary)
                assert loop is not None
                log("Step 1: measuring one loop period")
                count_cmd = [
                    ffmpeg, "-n", "-nostdin", "-hide_banner", "-i", str(loop),
                    *video_options, "-progress", "pipe:1", "-nostats", "-f", "null", "-",
                ]
                period_frames = self._run(count_cmd, loop_info.duration, log, stage(0.0, 0.08))
                if period_frames <= 0:
                    raise RenderError("LOOP has no frames after video conversion")
                if progress:
                    progress(0.08)

                parts: list[tuple[str, int]] = []
                intro_frames = 0
                if intro and intro_info:
                    log("Step 2: encoding intro")
                    intro_frames = encode(intro, work / "intro.mp4", intro_info.duration, 0.08, 0.22)
                    parts.append(("intro.mp4", intro_frames))
                outro_frames = 0
                if outro and outro_info:
                    log("Step 3: encoding outro")
                    outro_frames = encode(outro, work / "outro.mp4", outro_info.duration, 0.22, 0.36)
                if progress:
                    progress(0.36)

                total_frames = math.ceil(Fraction(str(audio_info.duration)) * target_fps)
                middle_frames = total_frames - intro_frames - outro_frames
                if middle_frames <= 0:
                    raise RenderError("Audio is too short for selected intro/outro")
                repeats, remainder = divmod(middle_frames, period_frames)
                log(f"Loop period: {period_frames} frames; middle: {middle_frames} frames")
                log(f"Loop copies: {repeats}; tail: {remainder} frames")

                if repeats:
                    log("Step 4: encoding one loop period")
                    encode(loop, work / "period.mp4", loop_info.duration,
                           0.36, 0.64, period_frames)
                    parts.extend([("period.mp4", period_frames)] * repeats)
                if remainder:
                    log("Step 5: encoding partial loop tail")
                    encode(loop, work / "tail.mp4", remainder / target_fps,
                           0.64, 0.76, remainder)
                    parts.append(("tail.mp4", remainder))
                if outro_frames:
                    parts.append(("outro.mp4", outro_frames))
                if progress:
                    progress(0.76)

                listing = work / "concat.txt"
                listing.write_text(
                    "ffconcat version 1.0\n" + "".join(
                        f"file '{name}'\nduration {frames / target_fps:.9f}\n"
                        for name, frames in parts
                    ),
                    encoding="utf-8",
                )
                log("Step 6: copying video and muxing audio")
                cmd = [
                    ffmpeg, "-n", "-nostdin", "-hide_banner", "-f", "concat", "-i", str(listing),
                    "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                    "-t", f"{audio_info.duration:.6f}", "-c:v", "copy",
                    *audio_codec_args, "-movflags", "+faststart",
                    "-progress", "pipe:1", "-nostats", str(partial_output),
                ]
                final_frames = self._run(cmd, audio_info.duration, log, stage(0.76, FINALIZING_PROGRESS))
                if final_frames != total_frames:
                    raise RenderError(
                        f"Final video has {final_frames} frames; expected {total_frames}"
                    )
                if self._cancelled:
                    raise RenderCancelled("Render cancelled")
            output = _publish_output(partial_output, audio, output_dir)
        except BaseException:
            partial_output.unlink(missing_ok=True)
            raise
        if progress:
            progress(1.0)
        log(f"Output: {output}")
        return output

    def _run_probe(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        with self._lock:
            if self._cancelled:
                raise RenderCancelled("Render cancelled")
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            process = self._process

        try:
            try:
                stdout, stderr = process.communicate(timeout=PROBE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    if process.poll() is None:
                        raise
                process.communicate()
                raise
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None

        if self._cancelled:
            raise RenderCancelled("Render cancelled")
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)

    def _run(
        self,
        cmd: list[str],
        duration: float,
        log: LogFn,
        progress: ProgressFn | None,
    ) -> int:
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
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            process = self._process

        assert process.stdout is not None
        frame_count = 0
        try:
            for line in process.stdout:
                line = line.rstrip()
                if line.startswith("frame="):
                    try:
                        frame_count = int(line.split("=", 1)[1])
                    except ValueError:
                        pass
                if _handle_progress_line(line, duration, progress):
                    continue
                if line:
                    log(line)
            code = process.wait()
        finally:
            process.stdout.close()
            with self._lock:
                self._process = None

        if self._cancelled:
            raise RenderCancelled("Render cancelled")
        if code != 0:
            raise RenderError(f"ffmpeg failed with exit code {code}")
        return frame_count


def _output_folder(audio_path: str | Path, output_dir: str | Path | None) -> Path:
    audio = Path(audio_path)
    folder = Path(output_dir) if output_dir else audio.parent
    if not folder.exists():
        raise RenderError(f"Output folder does not exist: {folder}")
    if not folder.is_dir():
        raise RenderError(f"Output path is not a folder: {folder}")
    return folder


def _partial_output_path(audio_path: str | Path, output_dir: str | Path | None) -> Path:
    audio = Path(audio_path)
    folder = _output_folder(audio, output_dir)
    return folder / f".{audio.stem}_video.{uuid.uuid4().hex}.partial.mp4"


def _publish_output(partial: Path, audio_path: str | Path, output_dir: str | Path | None) -> Path:
    audio = Path(audio_path)
    folder = _output_folder(audio, output_dir)
    candidates = [folder / f"{audio.stem}_video.mp4"]
    candidates.extend(folder / f"{audio.stem}_video_{index}.mp4" for index in range(1, 1000))

    for candidate in candidates:
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(descriptor)
        try:
            os.replace(partial, candidate)
        except BaseException:
            candidate.unlink(missing_ok=True)
            raise
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
    return RenderJob().render(
        audio_path, intro_path, loop_path, outro_path, output_dir, log, progress
    )


def _audio_output_args(info: StreamInfo) -> tuple[list[str], str]:
    codec = (info.audio_codec or "").lower()
    rate = info.audio_sample_rate
    source = f"{codec.upper() or 'unknown codec'} {rate or 'unknown'} Hz"
    if codec in {"aac", "alac"}:
        return ["-c:a", "copy"], f"{source} copied unchanged"

    resampling = f"; resampled from {rate or 'unknown'} Hz" if rate != 48000 else ""
    if codec in LOSSLESS_AUDIO_CODECS or codec.startswith("pcm_"):
        return ["-c:a", "alac"], (
            f"{source} -> ALAC, source sample rate and channels preserved"
        )
    return ["-c:a", "aac", "-q:a", "10", "-ar", "48000"], (
        f"{source} -> AAC 48000 Hz, VBR q=10, channels preserved{resampling}"
    )


def choose_video_target(infos: list[StreamInfo]) -> tuple[int, int, Fraction]:
    if not infos:
        raise RenderError("No video stream information available")
    if any(not info.width or not info.height or not info.frame_rate for info in infos):
        raise RenderError("Could not determine video resolution or frame rate")

    weakest = min(infos, key=lambda info: (info.width or 0) * (info.height or 0))
    width = weakest.width or 0
    height = weakest.height or 0
    width -= width % 2
    height -= height % 2
    frame_rate = min(info.frame_rate for info in infos if info.frame_rate is not None)
    return width, height, frame_rate


def _video_filter(width: int, height: int, frame_rate: str) -> str:
    return (
        f"scale='min(iw,{width})':'min(ih,{height})':force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={frame_rate},format=yuv420p,setsar=1"
    )


def _video_encoder_args(frame_rate: Fraction, rate_control: list[str]) -> list[str]:
    gop = max(1, round(GOP_SECONDS * frame_rate))
    return [
        "-c:v", "libx264", "-preset", VIDEO_PRESET,
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        *rate_control,
        "-x264-params",
        f"bframes=3:b-pyramid=normal:open-gop=0:scenecut=0:"
        f"keyint={gop}:min-keyint={gop}:repeat-headers=1",
        "-video_track_timescale", str(frame_rate.numerator),
    ]


def _format_frame_rate(frame_rate: Fraction) -> str:
    if frame_rate.denominator == 1:
        return str(frame_rate.numerator)
    return f"{frame_rate.numerator}/{frame_rate.denominator}"


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
            progress(max(0.0, min(seconds / duration, FINALIZING_PROGRESS)))
        return True
    return key in {
        "bitrate",
        "dup_frames",
        "drop_frames",
        "fps",
        "frame",
        "out_time",
        "progress",
        "speed",
        "stream_0_0_q",
        "total_size",
    }


def _quote_cmd(cmd: list[str]) -> str:
    return " ".join(_quote_part(part) for part in cmd)


def _kill_if_running(process: subprocess.Popen[str], cancel_error: LogFn | None = None) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except OSError as exc:
            if process.poll() is not None:
                return
            message = f"Could not stop media process: {exc}"
            if cancel_error:
                cancel_error(message)
                return
            raise RenderError(message) from exc


def _quote_part(part: str) -> str:
    if not part or any(char.isspace() for char in part):
        return '"' + part.replace('"', '\\"') + '"'
    return part
