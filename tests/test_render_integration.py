import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from media_probe import probe_audio, probe_video, require_tools
from render import AudioConversionRequired, RenderJob


class RenderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.ffmpeg, cls.ffprobe = require_tools()
        except RuntimeError as exc:
            if os.environ.get("CI", "").lower() == "true":
                raise
            raise unittest.SkipTest(str(exc)) from exc

    def run_media(self, *args: str | Path) -> str:
        result = subprocess.run(
            [self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
             *(str(arg) for arg in args)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=True,
        )
        return result.stdout

    def make_video(self, folder: Path, name: str, source: str, frames: int) -> Path:
        path = folder / name
        self.run_media("-f", "lavfi", "-i", source, "-frames:v", str(frames),
                       "-c:v", "mpeg4", "-q:v", "5", path)
        return path

    def test_delayed_audio_from_video_is_copied_from_zero(self) -> None:
        for codec in ("alac", "aac"):
            with self.subTest(codec=codec), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                loop = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
                audio = folder / "delayed.mp4"
                self.run_media(
                    "-f", "lavfi", "-i", "color=s=64x64:r=30:duration=2",
                    "-itsoffset", "1", "-f", "lavfi", "-i",
                    "sine=sample_rate=48000:duration=0.5",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mpeg4", "-c:a", codec, audio,
                )
                source_info = probe_audio(audio, self.ffprobe)
                self.assertGreater(source_info.audio_start_offset, 0.9)

                output = RenderJob().render(audio, None, loop, None, folder, log=lambda _: None)

                result = probe_audio(output, self.ffprobe)
                self.assertLess(abs(result.audio_start_offset), 0.001)
                self.assertAlmostEqual(result.duration, source_info.duration, delta=0.03)
                self.assertEqual(
                    self.run_media("-i", audio, "-map", "0:a:0", "-c:a", "copy", "-f", "streamhash", "-"),
                    self.run_media("-i", output, "-map", "0:a:0", "-c:a", "copy", "-f", "streamhash", "-"),
                )

    def test_mkv_duration_uses_audio_track_including_nonzero_start(self) -> None:
        for offset in (0, 1):
            with self.subTest(offset=offset), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                loop = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
                audio = folder / "short audio.mkv"
                self.run_media(
                    "-f", "lavfi", "-i", "color=s=64x64:r=30:duration=2",
                    "-itsoffset", str(offset), "-f", "lavfi", "-i",
                    "sine=sample_rate=48000:duration=0.5",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mpeg4", "-c:a", "pcm_s16le", audio,
                )
                self.assertAlmostEqual(probe_audio(audio, self.ffprobe).duration, 0.5, places=3)

                output = RenderJob().render(audio, None, loop, None, folder, log=lambda _: None)

                self.assertAlmostEqual(probe_video(output, "OUTPUT", self.ffprobe).duration,
                                       0.5, delta=1 / 30)
                self.assertAlmostEqual(probe_audio(output, self.ffprobe).duration, 0.5, places=3)

    def test_anamorphic_video_keeps_display_proportions(self) -> None:
        for sar, rotation, dimensions in (("4/3", 0, (160, 90)),
                                           ("1/2", 0, (120, 180)),
                                           ("3/2", 90, (90, 180)),
                                           ("1/1", 0, (120, 90)),
                                           ("1/1", 90, (90, 120))):
            with self.subTest(sar=sar, rotation=rotation), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                source = folder / "source.mp4"
                self.run_media("-f", "lavfi", "-i", "testsrc2=s=120x90:r=30:duration=0.4",
                               "-vf", f"setsar={sar}", "-c:v", "libx264", source)
                if rotation:
                    rotated = folder / "rotated.mp4"
                    self.run_media("-display_rotation", str(rotation), "-i", source,
                                   "-c", "copy", rotated)
                    source = rotated
                audio = folder / "audio.wav"
                self.run_media("-f", "lavfi", "-i", "sine=duration=0.5", audio)

                output = RenderJob().render(audio, None, source, None, folder, log=lambda _: None)

                data = json.loads(subprocess.run(
                    [self.ffprobe, "-v", "error", "-select_streams", "v:0",
                     "-show_streams", "-of", "json", str(output)],
                    capture_output=True, text=True, check=True, timeout=15,
                ).stdout)["streams"][0]
                self.assertEqual((data["width"], data["height"]), dimensions)
                self.assertEqual(data["sample_aspect_ratio"], "1:1")

    def test_mixed_video_keeps_all_edges_and_round_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            sources = []
            for index, (sar, rotation) in enumerate(((Fraction(4, 3), 0),
                                                    (Fraction(1, 2), 0),
                                                    (Fraction(3, 2), 90))):
                # Border reveals cropping; a SAR-corrected circle reveals stretching.
                pixels = bytes(
                    160 if x < 4 or x >= 116 or y < 4 or y >= 86 else
                    255 if ((x - 59.5) * float(sar)) ** 2 + (y - 44.5) ** 2 < 12 ** 2 else 0
                    for y in range(90) for x in range(120)
                )
                picture = folder / f"pattern{index}.pgm"
                picture.write_bytes(b"P5\n120 90\n255\n" + pixels)
                source = folder / f"source{index}.mp4"
                self.run_media("-loop", "1", "-i", picture, "-t", "0.2", "-r", "30",
                               "-vf", f"setsar={sar}", "-c:v", "libx264", "-pix_fmt", "yuv420p", source)
                if rotation:
                    rotated = folder / "rotated.mp4"
                    self.run_media("-display_rotation", str(rotation), "-i", source,
                                   "-c", "copy", rotated)
                    source = rotated
                sources.append(source)
            audio = folder / "audio.wav"
            self.run_media("-f", "lavfi", "-i", "sine=duration=1", audio)

            output = RenderJob().render(audio, *sources, folder, log=lambda _: None)

            info = probe_video(output, "OUTPUT", self.ffprobe)
            self.assertEqual((info.width, info.height), (160, 90))
            for timestamp, expected_width in (("0.1", 160), ("0.3", 60), ("0.9", 46)):
                with self.subTest(timestamp=timestamp):
                    frame = subprocess.run(
                        [self.ffmpeg, "-nostdin", "-v", "error", "-ss", timestamp,
                         "-i", str(output), "-frames:v", "1", "-pix_fmt", "gray",
                         "-f", "rawvideo", "-"], capture_output=True, check=True, timeout=15,
                    ).stdout
                    self.assertEqual(len(frame), 160 * 90)
                    border = [(i % 160, i // 160) for i, value in enumerate(frame) if value > 100]
                    left, right = min(x for x, _ in border), max(x for x, _ in border)
                    top, bottom = min(y for _, y in border), max(y for _, y in border)
                    self.assertAlmostEqual(right - left + 1, expected_width, delta=2)
                    self.assertEqual((top, bottom), (0, 89))
                    for y in (top, bottom):
                        self.assertGreater(sum(frame[y * 160 + x] > 100
                                               for x in range(left, right + 1)), expected_width * 0.8)
                    for x in (left, right):
                        self.assertGreater(sum(frame[y * 160 + x] > 100 for y in range(90)), 72)
                    circle = [(i % 160, i // 160) for i, value in enumerate(frame) if value > 230]
                    circle_width = max(x for x, _ in circle) - min(x for x, _ in circle) + 1
                    circle_height = max(y for _, y in circle) - min(y for _, y in circle) + 1
                    self.assertAlmostEqual(circle_width, circle_height, delta=2)

    def test_high_precision_wav_requires_confirmation_before_conversion(self) -> None:
        for codec in ("pcm_s32le", "pcm_f32le"):
            with self.subTest(codec=codec), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                source = folder / "source.wav"
                loop = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
                self.run_media("-f", "lavfi", "-i", "sine=sample_rate=48000:duration=0.5",
                               "-c:a", codec, source)
                original = source.read_bytes()
                with self.assertRaisesRegex(AudioConversionRequired, "24-bit"):
                    RenderJob().render(source, None, loop, None, folder, log=lambda _: None)
                self.assertFalse((folder / "source_video.mp4").exists())
                self.assertEqual(list(folder.glob("*.partial.mp4")), [])

                output = RenderJob().render(source, None, loop, None, folder, log=lambda _: None,
                                            allow_audio_conversion=True)

                result = probe_audio(output, self.ffprobe)
                self.assertEqual(result.audio_bits_per_sample, 24)
                self.assertEqual(result.audio_sample_rate, 48000)
                self.assertEqual(result.audio_channels, 1)
                self.assertEqual(source.read_bytes(), original)

    def test_repeated_period_is_copied_with_clean_timestamps_and_aac(self) -> None:
        rate = Fraction(30_000, 1_001)
        with tempfile.TemporaryDirectory(prefix="podcast-renderer-test-") as temporary:
            folder = Path(temporary)
            intro = self.make_video(folder, "intro.mp4", "color=c=red:s=64x64:r=30000/1001", 5)
            loop = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30000/1001", 7)
            outro = self.make_video(folder, "outro.mp4", "color=c=blue:s=64x64:r=30000/1001", 5)
            audio = folder / "эпизод #1.m4a"
            self.run_media("-f", "lavfi", "-i", "sine=frequency=440:duration=2.32",
                           "-c:a", "aac", "-ar", "48000", audio)

            stage_updates = []
            output = RenderJob().render(audio, intro, loop, outro, folder,
                                        log=lambda _line: None,
                                        stage_progress=stage_updates.append)
            self.assertEqual(
                [stage.name for stage in stage_updates[-1].stages],
                ["Measuring loop", "Encoding intro", "Encoding outro", "Encoding loop",
                 "Encoding loop tail", "Muxing and finalizing"],
            )
            self.assertEqual(stage_updates[-1].fraction, 1.0)
            self.assertTrue(any(0 < update.fraction < 1 for update in stage_updates))
            expected_frames = math.ceil(Fraction(str(probe_audio(audio, self.ffprobe).duration)) * rate)
            packet_data = json.loads(subprocess.run(
                [self.ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_packets", "-show_entries", "packet=pts_time,dts_time",
                 "-of", "json", str(output)],
                capture_output=True, text=True, encoding="utf-8", check=True,
            ).stdout)["packets"]
            self.assertEqual(len(packet_data), expected_frames)
            dts = [float(packet["dts_time"]) for packet in packet_data]
            self.assertTrue(all(a < b for a, b in zip(dts, dts[1:])))
            pts = sorted(float(packet["pts_time"]) for packet in packet_data)
            self.assertAlmostEqual(pts[0], 0, places=4)
            gaps = [(index, round(b - a, 6)) for index, (a, b) in enumerate(zip(pts, pts[1:]))
                    if abs((b - a) - 1 / rate) >= 0.0001]
            self.assertEqual(gaps, [])
            frame_lines = self.run_media("-i", output, "-map", "0:v:0",
                                         "-f", "framemd5", "-")
            hashes = [line.rsplit(",", 1)[-1].strip() for line in frame_lines.splitlines()
                      if line and not line.startswith("#")]
            self.assertEqual(hashes[5:12], hashes[12:19])
            middle_frames = expected_frames - 10
            repeats, remainder = divmod(middle_frames, 7)
            self.assertGreaterEqual(repeats, 2)
            self.assertGreater(remainder, 0)
            self.assertEqual(len(set(hashes[-5:])), 1)

            def audio_hash(path: Path) -> str:
                return self.run_media("-i", path, "-map", "0:a:0", "-c:a", "copy",
                                      "-f", "streamhash", "-")

            self.assertEqual(audio_hash(audio), audio_hash(output))

    def test_single_video_and_mono_wav_produce_mono_alac(self) -> None:
        with tempfile.TemporaryDirectory(prefix="podcast-renderer-test-") as temporary:
            folder = Path(temporary)
            video = self.make_video(folder, "один loop #1.mp4",
                                    "testsrc2=s=64x64:r=30000/1001", 7)
            audio = folder / "mono audio.wav"
            self.run_media("-f", "lavfi", "-i", "sine=frequency=440:duration=0.55",
                           "-ar", "44100", "-ac", "1", audio)

            output = RenderJob().render(audio, video, None, None, folder,
                                        log=lambda _line: None)
            stream_data = json.loads(subprocess.run(
                [self.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)],
                capture_output=True, text=True, encoding="utf-8", check=True,
            ).stdout)["streams"]
            video_stream = next(stream for stream in stream_data if stream["codec_type"] == "video")
            audio_stream = next(stream for stream in stream_data if stream["codec_type"] == "audio")
            expected_frames = math.ceil(Fraction(str(probe_audio(audio, self.ffprobe).duration))
                                        * Fraction(30_000, 1_001))
            self.assertEqual(int(video_stream["nb_frames"]), expected_frames)
            self.assertEqual(video_stream["avg_frame_rate"], "30000/1001")
            self.assertEqual(audio_stream["codec_name"], "alac")
            self.assertEqual(audio_stream["sample_rate"], "44100")
            self.assertEqual(audio_stream["channels"], 1)

    def test_aac_44100_is_copied_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="podcast-renderer-test-") as temporary:
            folder = Path(temporary)
            video = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
            audio = folder / "master 44100.m4a"
            self.run_media("-f", "lavfi", "-i", "sine=frequency=440:duration=0.55",
                           "-c:a", "aac", "-ar", "44100", audio)
            logs: list[str] = []

            output = RenderJob().render(audio, None, video, None, folder, log=logs.append)

            self.assertEqual(probe_audio(audio, self.ffprobe).audio_sample_rate, 44100)
            output_info = probe_audio(output, self.ffprobe)
            self.assertEqual(output_info.audio_codec, "aac")
            self.assertEqual(output_info.audio_sample_rate, 44100)
            self.assertTrue(any("copied unchanged" in line for line in logs))
            self.assertEqual(
                self.run_media("-i", audio, "-map", "0:a:0", "-c:a", "copy", "-f", "streamhash", "-"),
                self.run_media("-i", output, "-map", "0:a:0", "-c:a", "copy", "-f", "streamhash", "-"),
            )

    def test_alac_preserves_stereo_pcm_samples(self) -> None:
        with tempfile.TemporaryDirectory(prefix="podcast-renderer-test-") as temporary:
            folder = Path(temporary)
            video = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
            audio = folder / "PCM мастер 48k.wav"
            self.run_media("-f", "lavfi", "-i", "sine=frequency=440:duration=0.55",
                           "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", audio)
            logs: list[str] = []

            output = RenderJob().render(audio, None, video, None, folder,
                                        log=logs.append)
            output_info = probe_audio(output, self.ffprobe)
            self.assertEqual(output_info.audio_codec, "alac")
            self.assertEqual(output_info.audio_sample_rate, 48000)

            def pcm_md5(path: Path) -> str:
                return self.run_media("-i", path, "-map", "0:a:0", "-c:a", "pcm_s16le",
                                      "-ar", "48000", "-ac", "2", "-f", "md5", "-")

            self.assertEqual(pcm_md5(audio), pcm_md5(output))
            self.assertTrue(any("source sample rate and channels preserved" in line
                                for line in logs))

            alac_delta = abs(probe_video(output, "OUTPUT", self.ffprobe).duration
                             - output_info.duration)
            self.assertLess(alac_delta, 0.04)

    def test_24_bit_pcm_is_preserved_without_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            video = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
            audio = folder / "24-bit.wav"
            self.run_media("-f", "lavfi", "-i", "aevalsrc=0.123456*sin(2*PI*440*t):d=0.5",
                           "-c:a", "pcm_s24le", audio)

            output = RenderJob().render(audio, None, video, None, folder, log=lambda _: None)

            self.assertEqual(probe_audio(output, self.ffprobe).audio_bits_per_sample, 24)
            self.assertEqual(
                self.run_media("-i", audio, "-c:a", "pcm_s32le", "-f", "md5", "-"),
                self.run_media("-i", output, "-map", "0:a:0", "-c:a", "pcm_s32le", "-f", "md5", "-"),
            )

    def test_flac_44100_keeps_lossless_audio_and_sample_rate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="podcast-renderer-test-") as temporary:
            folder = Path(temporary)
            video = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
            audio = folder / "мастер.flac"
            self.run_media("-f", "lavfi", "-i", "sine=frequency=440:duration=0.55",
                           "-c:a", "flac", "-ar", "44100", "-ac", "1", audio)

            output = RenderJob().render(audio, None, video, None, folder,
                                        log=lambda _line: None)
            info = probe_audio(output, self.ffprobe)
            self.assertEqual(info.audio_codec, "alac")
            self.assertEqual(info.audio_sample_rate, 44100)

            def pcm_md5(path: Path) -> str:
                return self.run_media("-i", path, "-map", "0:a:0", "-c:a", "pcm_s16le",
                                      "-f", "md5", "-")

            self.assertEqual(pcm_md5(audio), pcm_md5(output))

    def test_mono_mp3_is_encoded_as_mono_aac(self) -> None:
        with tempfile.TemporaryDirectory(prefix="podcast-renderer-test-") as temporary:
            folder = Path(temporary)
            video = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
            audio = folder / "mono.mp3"
            self.run_media("-f", "lavfi", "-i", "sine=frequency=440:duration=0.55",
                           "-c:a", "libmp3lame", "-ar", "44100", "-ac", "1", audio)

            output = RenderJob().render(audio, None, video, None, folder,
                                        log=lambda _line: None)
            info = probe_audio(output, self.ffprobe)
            self.assertEqual(info.audio_codec, "aac")
            self.assertEqual(info.audio_sample_rate, 48000)
            streams = json.loads(subprocess.run(
                [self.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)],
                capture_output=True, text=True, encoding="utf-8", check=True,
            ).stdout)["streams"]
            audio_stream = next(s for s in streams if s["codec_type"] == "audio")
            self.assertEqual(audio_stream["channels"], 1)
            self.assertEqual(audio_stream["profile"], "LC")

    def test_stereo_mp3_with_repeated_loop_produces_faststart_aac(self) -> None:
        with tempfile.TemporaryDirectory(prefix="podcast-renderer-test-") as temporary:
            folder = Path(temporary)
            video = self.make_video(folder, "loop.mp4", "testsrc2=s=64x64:r=30", 7)
            audio = folder / "stereo #1.mp3"
            self.run_media("-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                           "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000",
                           "-ac", "2", audio)
            logs: list[str] = []

            output = RenderJob().render(audio, None, video, None, folder, log=logs.append)

            info = probe_audio(output, self.ffprobe)
            self.assertEqual(info.audio_codec, "aac")
            self.assertEqual(info.audio_sample_rate, 48000)
            self.assertEqual(info.audio_channels, 2)
            stream_data = json.loads(subprocess.run(
                [self.ffprobe, "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=profile", "-of", "json", str(output)],
                capture_output=True, text=True, encoding="utf-8", check=True,
            ).stdout)["streams"]
            self.assertEqual(stream_data[0]["profile"], "LC")
            self.assertLess(abs(probe_video(output, "OUTPUT", self.ffprobe).duration
                                - info.duration), 0.05)
            data = output.read_bytes()
            self.assertLess(data.index(b"moov"), data.index(b"mdat"))
            if sys.platform == "win32":
                self.assertTrue(any("Windows Media Foundation" in line for line in logs))
            elif sys.platform == "darwin" and platform.machine() == "x86_64":
                self.assertTrue(any("Apple AudioToolbox" in line for line in logs))
            else:
                self.assertTrue(any("VBR q=10" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
