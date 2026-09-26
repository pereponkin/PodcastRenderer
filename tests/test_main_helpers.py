import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import APP_TITLE, APP_VERSION, App, find_video_siblings
from render import FINALIZING_PROGRESS, MUX_START_PROGRESS


class VideoSiblingTests(unittest.TestCase):
    def test_matching_filename_role_still_autofills_video_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            intro = root / "show_Intro.mp4"
            loop = root / "show_Loop.mp4"
            outro = root / "show_Outro.mp4"
            for path in (intro, loop, outro):
                path.touch()

            siblings = find_video_siblings(loop, selected_slot="LOOP")

        self.assertEqual(
            siblings,
            {"INTRO": intro, "LOOP": loop, "OUTRO": outro},
        )

    def test_autofill_is_skipped_when_filename_role_disagrees_with_selected_slot(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            intro = root / "show_Intro.mp4"
            loop = root / "show_Loop.mp4"
            outro = root / "show_Outro.mp4"
            for path in (intro, loop, outro):
                path.touch()

            siblings = find_video_siblings(intro, selected_slot="LOOP")

        self.assertEqual(siblings, {})


class VersionTests(unittest.TestCase):
    def test_window_title_contains_current_version(self) -> None:
        self.assertEqual(APP_TITLE, f"Podcast Renderer {APP_VERSION}")


class WindowLifecycleTests(unittest.TestCase):
    def test_render_worker_uses_automatic_audio_output(self) -> None:
        app = object.__new__(App)
        app.current_job = Mock()
        app.current_job.render.return_value = Path("output.mp4")
        app.log_queue = queue.Queue()

        App._render_worker(app, {
            "AUDIO": "audio.wav", "INTRO": "", "LOOP": "loop.mp4",
            "OUTRO": "", "OUTPUT": "output",
        })

        self.assertNotIn("audio_format", app.current_job.render.call_args.kwargs)
        self.assertEqual(app.log_queue.get_nowait(), ("done", "output.mp4"))

    def test_drop_uses_tcl_file_list_and_fills_audio_output_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / "запись #1 с пробелами.wav"
            audio.touch()
            app = object.__new__(App)
            app.tk = tk.Tcl()
            app.entries = {"AUDIO": Mock(), "OUTPUT": Mock()}
            app.entries["OUTPUT"].get.return_value = ""

            App._drop_file(app, SimpleNamespace(data="{" + str(audio) + "}"), "AUDIO")

            app.entries["AUDIO"].set.assert_called_once_with(str(audio))
            app.entries["OUTPUT"].set.assert_called_once_with(str(audio.parent))

    def test_drop_rejects_multiple_files(self) -> None:
        app = object.__new__(App)
        app.tk = tk.Tcl()
        app.entries = {"LOOP": Mock()}
        with patch("main.messagebox.showerror") as showerror:
            App._drop_file(app, SimpleNamespace(data="{one.mp4} {two.mp4}"), "LOOP")
        showerror.assert_called_once()
        app.entries["LOOP"].set.assert_not_called()

    def test_dropped_loop_autofills_matching_video_fields(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            intro, loop, outro = (root / f"эпизод_{part}.mp4"
                                  for part in ("Intro", "Loop", "Outro"))
            for path in (intro, loop, outro):
                path.touch()
            app = object.__new__(App)
            app.tk = tk.Tcl()
            app.entries = {key: Mock() for key in ("INTRO", "LOOP", "OUTRO")}
            for entry in app.entries.values():
                entry.get.return_value = ""

            App._drop_file(app, SimpleNamespace(data="{" + str(loop) + "}"), "LOOP")

            app.entries["INTRO"].set.assert_called_once_with(str(intro))
            app.entries["LOOP"].set.assert_called_once_with(str(loop))
            app.entries["OUTRO"].set.assert_called_once_with(str(outro))

    def test_close_cancels_active_render_before_destroying_window(self) -> None:
        app = object.__new__(App)
        app.current_job = Mock()
        app.cancel_button = Mock()
        app._append = Mock()
        app.destroy = Mock()
        app._closing = False

        App._on_close(app)

        app.current_job.cancel.assert_called_once_with()
        app.destroy.assert_not_called()
        self.assertTrue(app._closing)

    def test_progress_text_names_finalization_phase(self) -> None:
        app = object.__new__(App)
        app.render_started_at = 90.0

        with patch("main.time.monotonic", return_value=100.0):
            text = App._progress_text(app, 0.999)

        self.assertEqual(text, "00:10 elapsed / finalizing")

    def test_eta_waits_for_mux_and_uses_its_observed_speed(self) -> None:
        app = object.__new__(App)
        app.render_started_at = 100.0
        app.mux_started_at = None
        app.eta_deadline = None
        app.progress_value = 0.2
        with patch("main.time.monotonic", return_value=110.0):
            App._update_eta(app)
            self.assertEqual(App._progress_text(app, 0.2),
                             "00:10 elapsed / --:-- remaining")
        self.assertIsNone(app.eta_deadline)

        app.progress_value = MUX_START_PROGRESS
        with patch("main.time.monotonic", return_value=120.0):
            App._update_eta(app)
        self.assertEqual(app.mux_started_at, 120.0)

        app.progress_value = MUX_START_PROGRESS + 0.25 * (FINALIZING_PROGRESS - MUX_START_PROGRESS)
        with patch("main.time.monotonic", return_value=130.0):
            App._update_eta(app)
            self.assertEqual(App._progress_text(app, app.progress_value),
                             "00:30 elapsed / 00:30 remaining")
        with patch("main.time.monotonic", return_value=135.0):
            self.assertEqual(App._progress_text(app, app.progress_value),
                             "00:35 elapsed / 00:25 remaining")

    def test_preparation_bar_does_not_show_stage_weights_as_completion(self) -> None:
        app = object.__new__(App)
        app.progress_canvas = Mock()
        app.progress_canvas.winfo_width.return_value = 100
        app.progress_canvas.winfo_height.return_value = 26
        app.render_started_at = 100.0
        app.eta_deadline = None
        app.progress_value = 0.7

        with patch("main.time.monotonic", return_value=110.0):
            App._draw_progress(app)

        filled = [call.args for call in app.progress_canvas.create_rectangle.call_args_list
                  if call.kwargs.get("fill") == "#4f8bd6"]
        self.assertTrue(filled)
        self.assertLessEqual(filled[0][2] - filled[0][0], 40)

    def test_cancel_failure_is_reported_and_window_remains_open(self) -> None:
        app = object.__new__(App)
        app.log_queue = queue.Queue()
        app.log_queue.put(("cancel_error", "Could not stop media process: denied"))
        app._append = Mock()
        app._closing = True
        app.render_started_at = None
        app.cancel_button = Mock()
        app.after = Mock()

        with patch("main.messagebox.showerror") as showerror:
            App._drain_log(app)

        self.assertFalse(app._closing)
        app.cancel_button.configure.assert_called_once_with(state="normal")
        showerror.assert_called_once_with(
            "Cancel failed",
            "Could not stop media process: denied",
        )


if __name__ == "__main__":
    unittest.main()
