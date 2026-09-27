from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


class ProbeError(RuntimeError):
    pass


PROBE_TIMEOUT_SECONDS = 15.0
ProbeRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class StreamInfo:
    duration: float
    has_video: bool = False
    has_audio: bool = False
    width: int | None = None
    height: int | None = None
    frame_rate: Fraction | None = None
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    audio_bitrate: int | None = None
    audio_start_offset: float = 0.0
    audio_sample_format: str | None = None
    audio_bits_per_sample: int | None = None


def find_tool(name: str) -> str | None:
    here = Path(__file__).resolve().parent
    executable_name = _tool_executable_name(name, sys.platform)
    roots = [here]
    vendor_dir = _platform_vendor_dir(sys.platform)
    if vendor_dir:
        roots.append(here / "vendor" / vendor_dir)
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            roots.append(Path(bundle_root))
        roots += [
            Path(sys.executable).resolve().parent,
            Path(sys.executable).resolve().parent.parent / "Resources",
            Path(sys.executable).resolve().parent.parent / "Frameworks",
        ]
    for root in roots:
        for local in (root / executable_name, root / "bin" / executable_name):
            if local.exists():
                return str(local)
    return shutil.which(name, path=os.environ.get("PATH", os.defpath))


def _tool_executable_name(name: str, platform: str) -> str:
    return f"{name}.exe" if platform == "win32" else name


def _platform_vendor_dir(platform: str) -> str | None:
    if platform == "win32":
        return "windows"
    if platform == "darwin":
        return "macos"
    return None


def require_tools() -> tuple[str, str]:
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    missing = [name for name, value in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not value]
    if missing:
        raise ProbeError(
            "Missing ffmpeg/ffprobe. Install FFmpeg and add it to PATH, "
            "or put ffmpeg and ffprobe next to this application."
        )
    return ffmpeg, ffprobe


def probe(
    path: str | Path,
    ffprobe: str | None = None,
    *,
    runner: ProbeRunner | None = None,
) -> StreamInfo:
    return _probe(path, ffprobe, preferred_stream_type=None, runner=runner)


def _probe(
    path: str | Path,
    ffprobe: str | None,
    preferred_stream_type: str | None,
    runner: ProbeRunner | None,
) -> StreamInfo:
    media_path = Path(path).expanduser().resolve()
    if not media_path.exists():
        raise ProbeError(f"File does not exist: {media_path}")
    ffprobe = ffprobe or require_tools()[1]
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media_path),
    ]
    try:
        result = runner(cmd) if runner else subprocess.run(
            cmd,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"ffprobe timed out after {PROBE_TIMEOUT_SECONDS:.0f}s: {media_path}") from exc
    except OSError as exc:
        raise ProbeError(f"Could not run ffprobe: {exc}") from exc
    if result.returncode != 0:
        raise ProbeError(f"ffprobe could not read {media_path}:\n{result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON for {media_path}") from exc

    streams = data.get("streams", [])
    has_video = any(stream.get("codec_type") == "video" for stream in streams)
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    duration = _duration(data, streams, preferred_stream_type)
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    format_start = _to_float(data.get("format", {}).get("start_time")) or 0.0
    audio_start = _to_float(audio_stream.get("start_time")) if audio_stream else None
    width, height = _display_dimensions(video_stream)
    frame_rate = _frame_rate(video_stream)
    return StreamInfo(
        duration=duration,
        has_video=has_video,
        has_audio=has_audio,
        width=width,
        height=height,
        frame_rate=frame_rate,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        audio_sample_rate=_to_int(audio_stream.get("sample_rate")) if audio_stream else None,
        audio_channels=_to_int(audio_stream.get("channels")) if audio_stream else None,
        audio_bitrate=_to_int(audio_stream.get("bit_rate")) if audio_stream else None,
        # FFmpeg normally subtracts the container start time from input timestamps.
        audio_start_offset=(audio_start - format_start) if audio_start is not None else 0.0,
        audio_sample_format=audio_stream.get("sample_fmt") if audio_stream else None,
        audio_bits_per_sample=(
            _to_int(audio_stream.get("bits_per_raw_sample"))
            or _to_int(audio_stream.get("bits_per_sample"))
        ) if audio_stream else None,
    )


def probe_audio(
    path: str | Path,
    ffprobe: str | None = None,
    *,
    runner: ProbeRunner | None = None,
) -> StreamInfo:
    info = _probe(path, ffprobe, preferred_stream_type="audio", runner=runner)
    if not info.has_audio:
        raise ProbeError(f"AUDIO has no readable audio stream: {path}")
    if info.duration <= 0:
        raise ProbeError(f"AUDIO duration is invalid: {path}")
    return info


def probe_video(
    path: str | Path,
    label: str,
    ffprobe: str | None = None,
    *,
    runner: ProbeRunner | None = None,
) -> StreamInfo:
    info = _probe(path, ffprobe, preferred_stream_type="video", runner=runner)
    if not info.has_video:
        raise ProbeError(f"{label} has no readable video stream: {path}")
    if info.duration <= 0:
        raise ProbeError(f"{label} duration is invalid: {path}")
    if not info.width or not info.height:
        raise ProbeError(f"{label} resolution is invalid: {path}")
    if not info.frame_rate or info.frame_rate <= 0:
        raise ProbeError(f"{label} frame rate is invalid: {path}")
    return info


def _duration(data: dict, streams: list[dict], preferred_stream_type: str | None) -> float:
    preferred = None
    if preferred_stream_type:
        preferred = next(
            (stream for stream in streams if stream.get("codec_type") == preferred_stream_type),
            None,
        )
    candidates = [preferred.get("duration") if preferred else None]
    if preferred:
        try:
            candidates.append(float(Fraction(str(preferred["duration_ts"]))
                                    * Fraction(str(preferred["time_base"]))))
        except (KeyError, ValueError, ZeroDivisionError, OverflowError):
            pass
        tag = next((value for key, value in preferred.get("tags", {}).items()
                    if key.upper() == "DURATION"), None)
        if isinstance(tag, str):
            try:
                hours, minutes, seconds = tag.split(":")
                # Matroska's DURATION tag includes the stream's starting offset.
                candidates.append(int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                                  - (_to_float(preferred.get("start_time")) or 0.0))
            except ValueError:
                pass
    candidates += [data.get("format", {}).get("duration")]
    candidates += [stream.get("duration") for stream in streams]
    for value in candidates:
        duration = _to_float(value)
        if duration is not None and duration > 0:
            return duration
    return 0.0


def _to_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _to_int(value: object) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _display_dimensions(stream: dict | None) -> tuple[int | None, int | None]:
    if not stream:
        return None, None
    width = _to_int(stream.get("width"))
    height = _to_int(stream.get("height"))
    if not width or not height:
        return None, None
    try:
        sar = Fraction(str(stream.get("sample_aspect_ratio", "1:1")).replace(":", "/"))
    except (ValueError, ZeroDivisionError):
        sar = Fraction(1)
    if sar <= 0:
        sar = Fraction(1)
    rotation = _rotation(stream)
    if rotation % 180:
        width, height = height, width
        sar = 1 / sar
    width = max(1, int(width * sar))
    return width, height


def _rotation(stream: dict) -> int:
    candidates = [stream.get("tags", {}).get("rotate")]
    candidates += [item.get("rotation") for item in stream.get("side_data_list", [])]
    for value in candidates:
        try:
            return int(round(float(value))) % 360
        except (TypeError, ValueError):
            continue
    return 0


def _frame_rate(stream: dict | None) -> Fraction | None:
    if not stream:
        return None
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            rate = Fraction(str(stream.get(key)))
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            return rate
    return None
