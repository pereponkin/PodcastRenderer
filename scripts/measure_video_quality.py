"""Compare the current ABR encoder with CRF on one period of each source."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media_probe import probe_video, require_tools
from render import _format_frame_rate, _video_encoder_args, _video_filter


BASELINE_BITRATE = "2048k"


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}):\n{completed.stderr}")
    return completed.stderr


def measure_psnr(ffmpeg: str, encoded: Path, source: Path, video_filter: str,
                 fps: str, timebase: str, self_check: bool = False) -> float:
    normal = f"setpts=N/({fps}*TB),settb={timebase}"
    reference = normal if self_check else (
        f"setpts=PTS-STARTPTS,{video_filter},{normal}"
    )
    graph = f"[0:v]{normal}[a];[1:v]{reference}[b];[a][b]psnr=shortest=1"
    stderr = run([
        ffmpeg, "-nostdin", "-hide_banner", "-v", "info", "-i", str(encoded),
        "-i", str(encoded if self_check else source), "-filter_complex", graph,
        "-an", "-f", "null", "-",
    ])
    scores = re.findall(r"PSNR .*average:(inf|[0-9.]+)", stderr)
    if not scores:
        raise RuntimeError(f"PSNR summary missing:\n{stderr[-2000:]}")
    return float(scores[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--crfs", nargs="*", type=int, default=[17, 19])
    parser.add_argument("--maxrate", help="Optional VBV cap for CRF runs, e.g. 6000k")
    parser.add_argument("--bufsize", help="VBV buffer, required with --maxrate")
    args = parser.parse_args()
    if bool(args.maxrate) != bool(args.bufsize):
        parser.error("--maxrate and --bufsize must be supplied together")

    ffmpeg, ffprobe = require_tools()
    with tempfile.TemporaryDirectory(prefix="podcast-quality-") as temporary:
        for source in args.sources:
            source = source.resolve()
            info = probe_video(source, "SOURCE", ffprobe)
            fps = _format_frame_rate(info.frame_rate)
            video_filter = _video_filter(info.width, info.height, fps)
            timebase = f"{info.frame_rate.denominator}/{info.frame_rate.numerator}"
            common = [
                ffmpeg, "-n", "-nostdin", "-hide_banner", "-v", "error",
                "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
                "-vf", f"setpts=PTS-STARTPTS,{video_filter},setpts=N/({fps}*TB)",
                "-r", fps, "-fps_mode", "cfr",
            ]
            print(f"SOURCE {source} ({info.width}x{info.height}, {fps} fps)", flush=True)
            profiles = [
                ("abr", ["-b:v", BASELINE_BITRATE, "-maxrate", BASELINE_BITRATE,
                         "-bufsize", "4096k"]),
                *[(f"crf{crf}", ["-crf", str(crf)]) for crf in args.crfs],
            ]
            if args.maxrate:
                profiles.extend(
                    (f"crf{crf}-capped", ["-crf", str(crf), "-maxrate", args.maxrate,
                                           "-bufsize", args.bufsize]) for crf in args.crfs
                )
            for label, rate_control in profiles:
                output = Path(temporary) / f"{label}.mp4"
                print(f"  encoding {label}...", flush=True)
                run([*common, *_video_encoder_args(info.frame_rate, rate_control), str(output)])
                if label == "abr":
                    self_psnr = measure_psnr(ffmpeg, output, source, video_filter,
                                             fps, timebase, self_check=True)
                    if self_psnr != float("inf"):
                        raise RuntimeError(f"PSNR self-check failed: {self_psnr}")
                psnr = measure_psnr(ffmpeg, output, source, video_filter, fps, timebase)
                duration = probe_video(output, "OUTPUT", ffprobe).duration
                size = output.stat().st_size
                kbps = size * 8 / duration / 1000
                print(f"  {label}: {psnr:.3f} dB, {kbps:.0f} kb/s, "
                      f"{size / 1048576:.2f} MiB, {duration:.3f} s", flush=True)
                output.unlink()


if __name__ == "__main__":
    main()
