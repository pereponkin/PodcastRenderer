import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from main import APP_TITLE, APP_VERSION, App, find_video_siblings


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
        self.assertEqual(APP_VERSION, "1.2.0")
        self.assertEqual(APP_TITLE, "Podcast Renderer 1.2.0")


class WindowLifecycleTests(unittest.TestCase):
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

    def test_cancel_failure_is_reported_and_window_remains_open(self) -> None:
        app = object.__new__(App)
        app.log_queue = queue.Queue()
        app.log_queue.put(("cancel_error", "Could not stop media process: denied"))
        app._append = Mock()
        app._closing = True
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
