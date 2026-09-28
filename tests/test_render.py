import io
import subprocess
import tempfile
import threading
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import render
from media_probe import ProbeError, StreamInfo
from render import (
    RenderCancelled, RenderError, RenderJob, _audio_output_args,
    _handle_progress_line, choose_video_target,
)


class RenderJobTests(unittest.TestCase):
    def test_stage_plan_follows_actual_video_operations(self) -> None:
        cases = [
            (False, False, 10, 2, ["Measuring loop", "Encoding loop", "Muxing and finalizing"]),
            (True, False, 10, 2, ["Measuring loop", "Encoding intro", "Encoding loop",
                               "Muxing and finalizing"]),
            (False, True, 10, 2, ["Measuring loop", "Encoding outro", "Encoding loop",
                               "Muxing and finalizing"]),
            (True, True, 10, 2, ["Measuring loop", "Encoding intro", "Encoding outro",
                              "Encoding loop", "Muxing and finalizing"]),
            (True, True, 11, 2, ["Measuring loop", "Encoding intro", "Encoding outro",
                              "Encoding loop", "Encoding loop tail", "Muxing and finalizing"]),
            (False, False, 1, 2, ["Measuring loop", "Encoding loop tail",
                               "Muxing and finalizing"]),
            (False, False, 10, 2.1, ["Measuring loop", "Encoding loop",
                                         "Muxing and finalizing"]),
        ]
        for use_intro, use_outro, seconds, loop_duration, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                audio = root / "audio.m4a"
                intro = root / "intro.mp4" if use_intro else None
                loop = root / "loop.mp4"
                outro = root / "outro.mp4" if use_outro else None
                updates = []
                progress = []
                commands = []
                job = RenderJob()

                def complete(cmd, _duration, _log, callback) -> int:
                    commands.append(cmd)
                    if callback:
                        callback(render.FINALIZING_PROGRESS * 0.5)
                    count = self._complete_stage(cmd, _duration, _log, callback)
                    if cmd[-1].endswith(".partial.mp4"):
                        if callback:
                            callback(render.FINALIZING_PROGRESS)
                        return seconds * 30
                    if cmd[-1].endswith("tail.mp4"):
                        return 30
                    return count

                with (
                    patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                    patch("render.probe_audio", return_value=StreamInfo(
                        duration=seconds, has_audio=True, audio_codec="aac")),
                    patch("render.probe_video", return_value=StreamInfo(
                        duration=loop_duration, has_video=True, width=64, height=64,
                        frame_rate=Fraction(30))),
                    patch.object(job, "_run", side_effect=complete),
                ):
                    job.render(audio, intro, loop, outro, root, log=lambda _: None,
                               progress=progress.append, stage_progress=updates.append)

                self.assertEqual(
                    [stage.name for stage in updates[0].stages],
                    ["Measuring loop", *(["Encoding intro"] if use_intro else []),
                     *(["Encoding outro"] if use_outro else []),
                     "Encoding middle", "Muxing and finalizing"],
                )
                self.assertEqual([stage.name for stage in updates[-1].stages], expected)
                self.assertEqual(updates[-1].index, len(expected) - 1)
                self.assertEqual(updates[-1].fraction, 1.0)
                self.assertEqual(updates[-2].fraction, render.FINALIZING_PROGRESS)
                self.assertEqual(progress[-2:], [render.FINALIZING_PROGRESS, 1.0])
                for index, name in enumerate(expected):
                    midpoint = (0.5 * render.FINALIZING_PROGRESS
                                if name == "Muxing and finalizing" else 0.5)
                    self.assertTrue(any(update.index == index and update.fraction == midpoint
                                        and update.stages[index].name == name
                                        for update in updates), name)
                self.assertEqual(len(commands), len(expected))

    def test_missing_or_truncated_output_audio_is_not_published(self) -> None:
        source = StreamInfo(duration=10, has_audio=True, audio_codec="aac")
        video = StreamInfo(duration=2, has_video=True, width=64, height=64,
                           frame_rate=Fraction(30))
        for result in (ProbeError("AUDIO has no readable audio stream"),
                       StreamInfo(duration=1, has_audio=True, audio_codec="aac")):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                job = RenderJob()
                with (patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                      patch("render.probe_audio", side_effect=[source, result]),
                      patch("render.probe_video", return_value=video),
                      patch.object(job, "_run", side_effect=self._complete_stage)):
                    with self.assertRaises((ProbeError, RenderError)):
                        job.render(folder / "audio.m4a", None, folder / "loop.mp4", None,
                                   folder, log=lambda _: None)
                self.assertFalse((folder / "audio_video.mp4").exists())
                self.assertEqual(list(folder.glob("*.partial.mp4")), [])

    def test_audio_output_policy_follows_source_codec(self) -> None:
        aac_48 = StreamInfo(duration=1.0, audio_codec="aac", audio_sample_rate=48000)
        aac_44 = StreamInfo(duration=1.0, audio_codec="aac", audio_sample_rate=44100)
        alac_48 = StreamInfo(duration=1.0, audio_codec="alac", audio_sample_rate=48000)
        alac_44 = StreamInfo(duration=1.0, audio_codec="alac", audio_sample_rate=44100)
        pcm_44 = StreamInfo(duration=1.0, audio_codec="pcm_s16le", audio_sample_rate=44100)
        flac_48 = StreamInfo(duration=1.0, audio_codec="flac", audio_sample_rate=48000)
        mp3_44 = StreamInfo(duration=1.0, audio_codec="mp3", audio_sample_rate=44100)

        for info in (aac_48, aac_44, alac_48, alac_44):
            self.assertEqual(_audio_output_args(info)[0], ["-c:a", "copy"])
        for info in (pcm_44, flac_48):
            self.assertEqual(_audio_output_args(info)[0], ["-c:a", "alac"])
        self.assertEqual(_audio_output_args(mp3_44)[0],
                         ["-c:a", "aac", "-q:a", "10", "-ar", "48000"])
        self.assertNotIn("-ar", _audio_output_args(pcm_44)[0])
        self.assertNotIn("-ac", _audio_output_args(mp3_44)[0])

        stereo_mp3 = StreamInfo(duration=1.0, audio_codec="mp3", audio_sample_rate=48000,
                                audio_channels=2, audio_bitrate=134858)
        mono_mp3 = StreamInfo(duration=1.0, audio_codec="mp3", audio_sample_rate=44100,
                              audio_channels=1, audio_bitrate=64000)
        rich_audio = StreamInfo(duration=1.0, audio_codec="ac3", audio_sample_rate=48000,
                                audio_channels=2, audio_bitrate=448000)
        self.assertEqual(_audio_output_args(stereo_mp3, fast_encoder="aac_mf")[0],
                         ["-c:a", "aac_mf", "-b:a", "256k", "-ar", "48000"])
        self.assertEqual(_audio_output_args(mono_mp3, fast_encoder="aac_mf")[0],
                         ["-c:a", "aac_mf", "-b:a", "128k", "-ar", "48000"])
        self.assertEqual(_audio_output_args(stereo_mp3, fast_encoder="aac_at")[0],
                         ["-c:a", "aac_at", "-b:a", "256k", "-ar", "48000"])
        self.assertEqual(_audio_output_args(mono_mp3, fast_encoder="aac_at")[0],
                         ["-c:a", "aac_at", "-b:a", "128k", "-ar", "48000"])
        self.assertEqual(_audio_output_args(rich_audio, fast_encoder="aac_mf")[0],
                         ["-c:a", "aac", "-q:a", "10", "-ar", "48000"])
        self.assertEqual(_audio_output_args(rich_audio, fast_encoder="aac_at")[0],
                         ["-c:a", "aac", "-q:a", "10", "-ar", "48000"])
        self.assertEqual(_audio_output_args(mp3_44, fast_encoder="aac_at")[0],
                         ["-c:a", "aac", "-q:a", "10", "-ar", "48000"])
        self.assertEqual(_audio_output_args(aac_48, fast_encoder="aac_at")[0],
                         ["-c:a", "copy"])

    def test_platform_aac_check_selects_fast_encoder_or_falls_back(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="mp3",
                                audio_sample_rate=48000, audio_channels=2,
                                audio_bitrate=134858)
        video_info = StreamInfo(duration=2.0, has_video=True, width=64, height=64,
                                frame_rate=Fraction(30, 1))

        cases = [
            ("win32", "AMD64", 0, "aac_mf"),
            ("win32", "AMD64", 1, "aac"),
            ("darwin", "x86_64", 0, "aac_at"),
            ("darwin", "x86_64", 1, "aac"),
            ("darwin", "arm64", 0, "aac"),
        ]
        for system, machine, check_code, expected_codec in cases:
            with self.subTest(system=system, machine=machine, check_code=check_code), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                audio, loop = root / "audio.mp3", root / "loop.mp4"
                audio.touch()
                loop.touch()
                commands: list[list[str]] = []

                def complete(cmd, duration, log, progress) -> int:
                    commands.append(cmd)
                    if cmd[-1].endswith(".partial.mp4") and progress:
                        progress(render.FINALIZING_PROGRESS)
                    return self._complete_stage(cmd, duration, log, progress)

                job = RenderJob()
                updates: list[float] = []
                logs: list[str] = []
                with (
                    patch("render.sys.platform", system),
                    patch("render.platform.machine", return_value=machine),
                    patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                    patch("render.probe_audio", return_value=audio_info),
                    patch("render.probe_video", return_value=video_info),
                    patch.object(job, "_run_probe", return_value=subprocess.CompletedProcess(
                        [], check_code, "", "encoder unavailable")) as probe_check,
                    patch.object(job, "_run", side_effect=complete),
                ):
                    job.render(audio, None, loop, None, root,
                               log=logs.append, progress=updates.append)

                final_cmd = commands[-1]
                self.assertEqual(final_cmd[final_cmd.index("-c:a") + 1], expected_codec)
                self.assertEqual(probe_check.call_count,
                                 int(system == "win32" or machine == "x86_64"))
                if check_code and machine != "arm64":
                    label = "Windows AAC" if system == "win32" else "AudioToolbox AAC"
                    self.assertTrue(any(f"{label} encoder unavailable" in line for line in logs))
                self.assertEqual(updates[-2:], [render.FINALIZING_PROGRESS, 1.0])

    @staticmethod
    def _complete_stage(cmd, _duration, _log, _progress) -> int:
        if cmd[-1] == "-":
            return 60
        if cmd[-1].endswith(".partial.mp4"):
            Path(cmd[-1]).write_bytes(b"complete mp4")
            return 300
        Path(cmd[-1]).write_bytes(b"period mp4")
        return 60

    def test_success_publishes_output_only_after_partial_file_is_complete(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac",
                                audio_sample_rate=48000)
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

            def complete_render(cmd, duration, log, progress) -> int:
                if cmd[-1].endswith(".partial.mp4"):
                    partial = Path(cmd[-1])
                    self.assertIn(".partial.", partial.name)
                    self.assertFalse((root / "episode_video.mp4").exists())
                return self._complete_stage(cmd, duration, log, progress)

            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                output = job.render(audio, None, video, None, root, log=lambda _line: None)

            self.assertEqual(output.resolve(), (root / "episode_video.mp4").resolve())
            self.assertEqual(output.read_bytes(), b"complete mp4")
            self.assertEqual(list(root.glob("*.partial.*")), [])

    def test_failed_render_removes_partial_output(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac",
                                audio_sample_rate=48000)
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

            def fail_render(cmd, duration, log, progress) -> int:
                if cmd[-1].endswith(".partial.mp4"):
                    Path(cmd[-1]).write_bytes(b"broken mp4")
                    raise RenderError("test failure")
                return self._complete_stage(cmd, duration, log, progress)

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
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac",
                                audio_sample_rate=48000)
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

            def complete_render(cmd, duration, log, progress) -> int:
                count = self._complete_stage(cmd, duration, log, progress)
                if cmd[-1].endswith(".partial.mp4"):
                    Path(cmd[-1]).write_bytes(b"new mp4")
                return count

            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                output = job.render(audio, None, video, None, root, log=lambda _line: None)

            self.assertEqual(existing.read_bytes(), b"original mp4")
            self.assertEqual(output.resolve(), (root / "episode_video_1.mp4").resolve())
            self.assertEqual(output.read_bytes(), b"new mp4")

    def test_ffmpeg_does_not_read_stdin_or_overwrite_output(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac",
                                audio_sample_rate=48000)
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

            def complete_render(cmd, duration, log, progress) -> int:
                commands.append(cmd)
                return self._complete_stage(cmd, duration, log, progress)

            job = RenderJob()
            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                job.render(audio, None, video, None, root, log=lambda _line: None)

        for command in commands:
            self.assertIn("-nostdin", command)
            self.assertIn("-n", command)
            self.assertNotIn("-y", command)
        for command in commands[1:-1]:
            self.assertEqual(command[command.index("-crf") + 1], "20")
            self.assertEqual(command[command.index("-maxrate") + 1], "8000k")
            self.assertEqual(command[command.index("-bufsize") + 1], "64000k")
            self.assertNotIn("-b:v", command)
        self.assertIn("copy", commands[-1])
        self.assertNotIn("libx264", commands[-1])

    def test_ffmpeg_receives_exact_fractional_frame_rate(self) -> None:
        audio_info = StreamInfo(duration=10.0, has_audio=True, audio_codec="aac",
                                audio_sample_rate=48000)
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

            def complete_render(cmd, duration, log, progress) -> int:
                commands.append(cmd)
                return self._complete_stage(cmd, duration, log, progress)

            job = RenderJob()
            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                job.render(audio, None, video, None, root, log=lambda _line: None)

        command = commands[1]
        self.assertEqual(command[command.index("-r") + 1], "30000/1001")
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("fps=30000/1001", video_filter)

    def test_short_audio_encodes_only_partial_loop(self) -> None:
        audio_info = StreamInfo(duration=1.0, has_audio=True, audio_codec="aac",
                                audio_sample_rate=48000)
        video_info = StreamInfo(
            duration=2.0, has_video=True, width=1920, height=1080,
            frame_rate=Fraction(30, 1),
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.m4a"
            loop = root / "loop.mp4"
            audio.touch()
            loop.touch()
            commands: list[list[str]] = []

            def complete_render(cmd, _duration, _log, _progress) -> int:
                commands.append(cmd)
                if cmd[-1] == "-":
                    return 60
                if cmd[-1].endswith("tail.mp4"):
                    Path(cmd[-1]).write_bytes(b"tail")
                    return 30
                Path(cmd[-1]).write_bytes(b"final")
                return 30

            job = RenderJob()
            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", return_value=audio_info),
                patch("render.probe_video", return_value=video_info),
                patch.object(job, "_run", side_effect=complete_render),
            ):
                job.render(audio, None, loop, None, root, log=lambda _line: None)

        self.assertEqual(len(commands), 3)
        self.assertIn("-frames:v", commands[1])
        self.assertEqual(commands[1][commands[1].index("-frames:v") + 1], "30")
        self.assertIn("-c:v", commands[-1])
        self.assertEqual(commands[-1][commands[-1].index("-c:v") + 1], "copy")

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

    def test_cancel_reports_when_process_cannot_be_killed(self) -> None:
        error_reported = threading.Event()
        errors: list[str] = []

        class UnstoppableProcess:
            @staticmethod
            def poll():
                return None

            @staticmethod
            def terminate() -> None:
                raise OSError("terminate denied")

            @staticmethod
            def kill() -> None:
                raise OSError("kill denied")

        def report_error(message: str) -> None:
            errors.append(message)
            error_reported.set()

        job = RenderJob(cancel_error=report_error)
        job._process = UnstoppableProcess()

        job.cancel()

        self.assertTrue(error_reported.wait(0.5), "cancel failure was not reported")
        self.assertEqual(errors, ["Could not stop media process: kill denied"])

    def test_cancel_during_ffprobe_stops_before_video_probes(self) -> None:
        probe_started = threading.Event()
        probe_stopped = threading.Event()

        class BlockingProbe:
            returncode = None

            @staticmethod
            def poll():
                return 1 if probe_stopped.is_set() else None

            @staticmethod
            def terminate() -> None:
                probe_stopped.set()

            @staticmethod
            def kill() -> None:
                probe_stopped.set()

            def communicate(self, timeout=None):
                probe_started.set()
                if not probe_stopped.wait(timeout):
                    raise subprocess.TimeoutExpired("ffprobe", timeout)
                self.returncode = 1
                return "", ""

        def probe_audio_through_runner(_path, _ffprobe, *, runner):
            runner(["ffprobe", "audio.wav"])
            raise AssertionError("Cancelled probe unexpectedly completed")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / "audio.wav"
            loop = root / "loop.mp4"
            audio.touch()
            loop.touch()
            job = RenderJob()
            outcome: list[BaseException] = []

            def render() -> None:
                try:
                    job.render(audio, None, loop, None, root, log=lambda _line: None)
                except BaseException as exc:
                    outcome.append(exc)

            with (
                patch("render.require_tools", return_value=("ffmpeg", "ffprobe")),
                patch("render.probe_audio", side_effect=probe_audio_through_runner),
                patch("render.probe_video") as probe_video,
                patch("render.subprocess.Popen", return_value=BlockingProbe()),
            ):
                worker = threading.Thread(target=render)
                worker.start()
                self.assertTrue(probe_started.wait(0.5), "ffprobe did not start")
                job.cancel()
                worker.join(0.5)

        self.assertFalse(worker.is_alive(), "render worker did not stop after cancellation")
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], RenderCancelled)
        probe_video.assert_not_called()

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
