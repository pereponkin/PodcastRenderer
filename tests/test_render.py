import io
import subprocess
import tempfile
import threading
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import render
from media_probe import StreamInfo
from render import RenderError, RenderJob, _handle_progress_line, choose_video_target


class RenderJobTests(unittest.TestCase):
    def test_success_publishes_output_only_after_partial_file_is_complete(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac")
        video_info = StreamInfo(
            duration=2.0,
            has_video=True,
            width=1920,
            height=1080,
            frame_rate=Fraction(30, 1),
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "episode.wav"
            video = root / "loop.mp4"
            audio.touch()
            video.touch()
            job = RenderJob()

            def complete_render(cmd, _duration, _log, _progress) -> None:
                partial = Path(cmd[-1])
                self.assertIn(".partial.", partial.name)
                self.assertFalse((root / "episode_video.mp4").exists())
                partial.write_bytes(b"complete mp4")

            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                output = job.render(audio, None, video, None, root, log=lambda _line: None)

            self.assertEqual(output, root / "episode_video.mp4")
            self.assertEqual(output.read_bytes(), b"complete mp4")
            self.assertEqual(list(root.glob("*.partial.*")), [])

    def test_failed_render_removes_partial_output(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac")
        video_info = StreamInfo(
            duration=2.0,
            has_video=True,
            width=1920,
            height=1080,
            frame_rate=Fraction(30, 1),
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "episode.wav"
            video = root / "loop.mp4"
            audio.touch()
            video.touch()
            job = RenderJob()

            def fail_render(cmd, _duration, _log, _progress) -> None:
                Path(cmd[-1]).write_bytes(b"broken mp4")
                raise RenderError("test failure")

            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=fail_render),
                self.assertRaises(RenderError),
            ):
                job.render(audio, None, video, None, root, log=lambda _line: None)

            self.assertFalse((root / "episode_video.mp4").exists())
            self.assertEqual(list(root.glob("*.partial.*")), [])

    def test_existing_output_is_preserved_and_next_suffix_is_used(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac")
        video_info = StreamInfo(
            duration=2.0,
            has_video=True,
            width=1920,
            height=1080,
            frame_rate=Fraction(30, 1),
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "episode.wav"
            video = root / "loop.mp4"
            existing = root / "episode_video.mp4"
            audio.touch()
            video.touch()
            existing.write_bytes(b"original mp4")
            job = RenderJob()

            def complete_render(cmd, _duration, _log, _progress) -> None:
                Path(cmd[-1]).write_bytes(b"new mp4")

            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                output = job.render(audio, None, video, None, root, log=lambda _line: None)

            self.assertEqual(existing.read_bytes(), b"original mp4")
            self.assertEqual(output, root / "episode_video_1.mp4")
            self.assertEqual(output.read_bytes(), b"new mp4")

    def test_ffmpeg_does_not_read_stdin_or_overwrite_output(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac")
        video_info = StreamInfo(
            duration=2.0,
            has_video=True,
            width=1920,
            height=1080,
            frame_rate=Fraction(30, 1),
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "episode.wav"
            video = root / "loop.mp4"
            audio.touch()
            video.touch()
            commands: list[list[str]] = []

            def complete_render(cmd, _duration, _log, _progress) -> None:
                commands.append(cmd)
                Path(cmd[-1]).write_bytes(b"complete mp4")

            job = RenderJob()
            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                job.render(audio, None, video, None, root, log=lambda _line: None)

        self.assertIn("-nostdin", commands[0])
        self.assertIn("-n", commands[0])
        self.assertNotIn("-y", commands[0])

    def test_ffmpeg_receives_exact_fractional_frame_rate(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac")
        video_info = StreamInfo(
            duration=2.0,
            has_video=True,
            width=1920,
            height=1080,
            frame_rate=Fraction(30_000, 1_001),
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "episode.wav"
            video = root / "loop.mp4"
            audio.touch()
            video.touch()
            commands: list[list[str]] = []

            def complete_render(cmd, _duration, _log, _progress) -> None:
                commands.append(cmd)
                Path(cmd[-1]).write_bytes(b"complete mp4")

            job = RenderJob()
            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                job.render(audio, None, video, None, root, log=lambda _line: None)

        command = commands[0]
        self.assertEqual(command[command.index("-r") + 1], "30000/1001")
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("fps=30000/1001", filter_complex)

    def test_ffmpeg_process_is_hidden_on_windows(self) -> None:
        class CompletedProcess:
            stdout = io.StringIO("")

            @staticmethod
            def wait(timeout=None) -> int:
                return 0

        with (
            patch("render.subprocess.Popen", return_value=CompletedProcess()) as popen,
            patch("render.sys.platform", "win32"),
            patch.object(render.subprocess, "CREATE_NO_WINDOW", 123, create=True),
        ):
            RenderJob()._run(["ffmpeg"], 1.0, lambda _line: None, None)

        self.assertEqual(
            popen.call_args.kwargs.get("creationflags"),
            123,
        )

    def test_cancel_kills_ffmpeg_when_terminate_is_ignored(self) -> None:
        killed = threading.Event()

        class StubbornProcess:
            terminated = False

            def poll(self):
                return None if not killed.is_set() else 1

            def terminate(self) -> None:
                self.terminated = True

            @staticmethod
            def wait(timeout=None):
                if killed.is_set():
                    return 1
                raise subprocess.TimeoutExpired("ffmpeg", timeout)

            @staticmethod
            def kill() -> None:
                killed.set()

        process = StubbornProcess()
        job = RenderJob()
        job._process = process

        with patch("render.CANCEL_KILL_TIMEOUT", 0.01, create=True):
            job.cancel()

        self.assertTrue(process.terminated)
        self.assertTrue(killed.wait(0.5), "ffmpeg was not killed after the cancel timeout")

    def test_progress_waits_below_complete_while_ffmpeg_finalizes(self) -> None:
        updates: list[float] = []

        handled = _handle_progress_line("out_time_us=10000000", 10.0, updates.append)

        self.assertTrue(handled)
        self.assertEqual(updates, [0.999])

    def test_video_target_uses_exact_lowest_source_frame_rate(self) -> None:
        infos = [
            StreamInfo(
                duration=2.0,
                has_video=True,
                width=1920,
                height=1080,
                frame_rate=Fraction(30_000, 1_001),
            ),
            StreamInfo(
                duration=2.0,
                has_video=True,
                width=1280,
                height=720,
                frame_rate=Fraction(24_000, 1_001),
            ),
        ]

        width, height, frame_rate = choose_video_target(infos)

        self.assertEqual((width, height), (1280, 720))
        self.assertEqual(frame_rate, Fraction(24_000, 1_001))


if __name__ == "__main__":
    unittest.main()
