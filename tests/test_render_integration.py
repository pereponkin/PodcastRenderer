import json
import math
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from media_probe import probe_audio, probe_video, require_tools
from render import RenderJob


class RenderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.ffmpeg, cls.ffprobe = require_tools()
        except RuntimeError as exc:
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

            output = RenderJob().render(audio, intro, loop, outro, folder,
                                        log=lambda _line: None)
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
            else:
                self.assertTrue(any("VBR q=10" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
