"""Benchmark the FFmpeg bundled in the macOS app on generated media."""

from __future__ import annotations

import json
import os
import platform
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import render


APP_BIN = Path("dist/PodcastRenderer.app/Contents/Frameworks/bin")
DURATION = 300


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)}\n{result.stderr[-4000:]}")
    return result


def probe(ffprobe: Path, path: Path) -> dict:
    result = run([
        str(ffprobe), "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


def check_audio(data: dict) -> None:
    audio = next(stream for stream in data["streams"] if stream["codec_type"] == "audio")
    assert audio["codec_name"] == "aac", audio
    assert audio["profile"] == "LC", audio
    assert audio["sample_rate"] == "48000", audio
    assert audio["channels"] == 2, audio


def faststart(path: Path) -> bool:
    boxes = []
    length = path.stat().st_size
    with path.open("rb") as file:
        offset = 0
        while offset < length:
            file.seek(offset)
            header = file.read(8)
            if len(header) < 8:
                raise ValueError("Truncated MP4 box header")
            size, kind = struct.unpack(">I4s", header)
            header_size = 8
            if size == 1:
                extended = file.read(8)
                if len(extended) != 8:
                    raise ValueError("Truncated extended MP4 box header")
                size = struct.unpack(">Q", extended)[0]
                header_size = 16
            if size == 0:
                size = length - offset
            if size < header_size or offset + size > length:
                raise ValueError("Invalid MP4 box size")
            boxes.append(kind)
            offset += size
    return b"moov" in boxes and b"mdat" in boxes and boxes.index(b"moov") < boxes.index(b"mdat")


def measure_audio(ffmpeg: Path, ffprobe: Path, source: Path, target: Path,
                  args: list[str]) -> dict:
    start = time.perf_counter()
    run([str(ffmpeg), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-i", str(source), "-map", "0:a:0", "-vn", *args, str(target)])
    seconds = time.perf_counter() - start
    data = probe(ffprobe, target)
    check_audio(data)
    return {"seconds": round(seconds, 2), "bytes": target.stat().st_size,
            "audio": next(s for s in data["streams"] if s["codec_type"] == "audio")}


def measure_render(ffmpeg: Path, ffprobe: Path, source: Path, loop: Path,
                   destination: Path, audio_args: list[str] | None = None) -> dict:
    destination.mkdir()
    start = time.perf_counter()
    with patch.object(render, "require_tools", return_value=(str(ffmpeg), str(ffprobe))):
        if audio_args is None:
            output = render.RenderJob().render(source, None, loop, None, destination,
                                               log=lambda line: None)
        else:
            with patch.object(render, "_audio_output_args",
                              return_value=(audio_args, "benchmark encoder")):
                output = render.RenderJob().render(source, None, loop, None,
                                                   destination, log=lambda line: None)
    seconds = time.perf_counter() - start
    data = probe(ffprobe, output)
    check_audio(data)
    video = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
    assert video["codec_name"] == "h264", video
    assert abs(float(data["format"]["duration"]) - DURATION) < 0.1, data["format"]
    assert faststart(output), "MP4 moov box is not before mdat"
    return {"seconds": round(seconds, 2), "bytes": output.stat().st_size,
            "video_frames": video.get("nb_frames"), "duration": data["format"]["duration"]}


def main() -> None:
    ffmpeg = APP_BIN / "ffmpeg"
    ffprobe = APP_BIN / "ffprobe"
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise RuntimeError(f"Missing bundled FFmpeg tools in {APP_BIN}")
    encoders = run([str(ffmpeg), "-hide_banner", "-encoders"]).stdout
    has_aac_at = any(line.split()[1] == "aac_at" for line in encoders.splitlines()
                        if len(line.split()) > 1)
    result = {"architecture": platform.machine(), "ffmpeg": run([
        str(ffmpeg), "-version"]).stdout.splitlines()[0],
        "source_seconds": DURATION, "aac_at_available": has_aac_at}

    with tempfile.TemporaryDirectory(prefix="podcast-macos-benchmark-") as folder:
        work = Path(folder)
        audio = work / "source.mp3"
        loop = work / "loop.mp4"
        run([str(ffmpeg), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={DURATION}",
             "-af", "pan=stereo|c0=c0|c1=c0", "-c:a", "libmp3lame", "-b:a", "192k",
             str(audio)])
        run([str(ffmpeg), "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
             "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(loop)])

        native = ["-c:a", "aac", "-q:a", "10", "-ar", "48000"]
        result["native_audio"] = measure_audio(ffmpeg, ffprobe, audio,
                                               work / "native.m4a", native)
        result["native_render"] = measure_render(ffmpeg, ffprobe, audio, loop,
                                                 work / "native")
        if has_aac_at:
            candidate = ["-c:a", "aac_at", "-b:a", "320k", "-ar", "48000"]
            try:
                result["aac_at_audio"] = measure_audio(ffmpeg, ffprobe, audio,
                                                       work / "aac_at.m4a", candidate)
                result["aac_at_render"] = measure_render(ffmpeg, ffprobe, audio, loop,
                                                         work / "aac_at", candidate)
            except (RuntimeError, AssertionError, ValueError) as error:
                result["aac_at_error"] = str(error)[-4000:]

    output = Path("benchmark-results") / f"macos-{platform.machine()}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as file:
            file.write(f"### macOS {platform.machine()}\n\n")
            file.write(f"Native AAC audio: {result['native_audio']['seconds']} s; "
                       f"full render: {result['native_render']['seconds']} s.\n\n")
            if "aac_at_render" in result:
                file.write(f"AudioToolbox AAC audio: {result['aac_at_audio']['seconds']} s; "
                           f"full render: {result['aac_at_render']['seconds']} s.\n")
            else:
                file.write(f"AudioToolbox AAC: {'unavailable' if not has_aac_at else 'failed'}\n")


if __name__ == "__main__":
    main()
