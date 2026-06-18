from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class StreamInfo:
    duration: float
    video_bitrate: int | None = None
    has_video: bool = False
    has_audio: bool = False
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    audio_codec: str | None = None


def find_tool(name: str) -> str | None:
    here = Path(__file__).resolve().parent
    suffix = ".exe" if name.lower() in {"ffmpeg", "ffprobe"} else ""
    executable_name = f"{name}{suffix}"
    roots = [here, here / "vendor" / "windows", here / "vendor" / "macos"]
    if getattr(sys, "frozen", False):
        roots += [
            Path(getattr(sys, "_MEIPASS", "")),
            Path(sys.executable).resolve().parent,
            Path(sys.executable).resolve().parent.parent / "Resources",
            Path(sys.executable).resolve().parent.parent / "Frameworks",
        ]
    for root in roots:
        if not root:
            continue
        for local in (root / executable_name, root / "bin" / executable_name):
            if local.exists():
                return str(local)
    return shutil.which(name)


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


def probe(path: str | Path, ffprobe: str | None = None) -> StreamInfo:
    media_path = Path(path)
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
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
    duration = _duration(data, streams)
    bitrate = _video_bitrate(data, streams)
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    width, height = _display_dimensions(video_stream)
    frame_rate = _frame_rate(video_stream)
    return StreamInfo(
        duration=duration,
        video_bitrate=bitrate,
        has_video=has_video,
        has_audio=has_audio,
        width=width,
        height=height,
        frame_rate=frame_rate,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
    )


def probe_audio(path: str | Path, ffprobe: str | None = None) -> StreamInfo:
    info = probe(path, ffprobe)
    if not info.has_audio:
        raise ProbeError(f"AUDIO has no readable audio stream: {path}")
    if info.duration <= 0:
        raise ProbeError(f"AUDIO duration is invalid: {path}")
    return info


def probe_video(path: str | Path, label: str, ffprobe: str | None = None) -> StreamInfo:
    info = probe(path, ffprobe)
    if not info.has_video:
        raise ProbeError(f"{label} has no readable video stream: {path}")
    if info.duration <= 0:
        raise ProbeError(f"{label} duration is invalid: {path}")
    if not info.width or not info.height:
        raise ProbeError(f"{label} resolution is invalid: {path}")
    if not info.frame_rate or info.frame_rate <= 0:
        raise ProbeError(f"{label} frame rate is invalid: {path}")
    return info


def choose_video_bitrate(*bitrates: int | None) -> str:
    found = [value for value in bitrates if value]
    if not found:
        return "2048k"
    return f"{max(max(found), 2_048_000) // 1000}k"


def _duration(data: dict, streams: list[dict]) -> float:
    candidates = [data.get("format", {}).get("duration")]
    candidates += [stream.get("duration") for stream in streams]
    for value in candidates:
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            return duration
    return 0.0


def _video_bitrate(data: dict, streams: list[dict]) -> int | None:
    for stream in streams:
        if stream.get("codec_type") != "video":
            continue
        bitrate = _to_int(stream.get("bit_rate"))
        if bitrate:
            return bitrate
    return _to_int(data.get("format", {}).get("bit_rate"))


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
    rotation = _rotation(stream)
    if rotation % 180:
        width, height = height, width
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


def _frame_rate(stream: dict | None) -> float | None:
    if not stream:
        return None
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            rate = float(Fraction(str(stream.get(key))))
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            return rate
    return None
