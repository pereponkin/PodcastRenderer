import json
import os
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from media_probe import ProbeError, find_tool, probe_audio, probe_video


class MediaProbeTests(unittest.TestCase):
    def test_audio_duration_comes_from_first_audio_stream(self) -> None:
        payload = {
            "format": {"duration": "20.0"},
            "streams": [
                {"codec_type": "video", "duration": "20.0"},
                {"codec_type": "audio", "duration": "10.0", "codec_name": "aac"},
            ],
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")

        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "source with spaces.mp4"
            media.touch()
            with patch("media_probe.subprocess.run", return_value=completed):
                info = probe_audio(media, "ffprobe")

        self.assertEqual(info.duration, 10.0)

    def test_video_frame_rate_preserves_ffprobe_fraction(self) -> None:
        payload = {
            "format": {"duration": "5.0"},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "5.0",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                    "r_frame_rate": "30/1",
                }
            ],
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")

        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "video.mp4"
            media.touch()
            with patch("media_probe.subprocess.run", return_value=completed):
                info = probe_video(media, "LOOP", "ffprobe")

        self.assertEqual(info.frame_rate, Fraction(30_000, 1_001))

    def test_ffprobe_receives_an_absolute_media_path(self) -> None:
        payload = {
            "format": {"duration": "1.0"},
            "streams": [
                {"codec_type": "audio", "duration": "1.0", "codec_name": "aac"}
            ],
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        original_cwd = Path.cwd()

        with tempfile.TemporaryDirectory() as folder:
            try:
                os.chdir(folder)
                relative = Path("- unusual audio.mp4")
                relative.touch()
                with patch("media_probe.subprocess.run", return_value=completed) as run:
                    probe_audio(relative, "ffprobe")
            finally:
                os.chdir(original_cwd)

        command = run.call_args.args[0]
        self.assertTrue(Path(command[-1]).is_absolute())
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_tool_path_fallback_does_not_search_current_directory_implicitly(self) -> None:
        with patch("media_probe.shutil.which", return_value=None) as which:
            find_tool("tool-that-does-not-exist")

        which.assert_called_once_with(
            "tool-that-does-not-exist",
            path=os.environ.get("PATH", os.defpath),
        )

    def test_ffprobe_timeout_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder) / "audio.wav"
            media.touch()
            with patch(
                "media_probe.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["ffprobe"], 15),
            ):
                with self.assertRaisesRegex(ProbeError, "ffprobe timed out"):
                    probe_audio(media, "ffprobe")


if __name__ == "__main__":
    unittest.main()
