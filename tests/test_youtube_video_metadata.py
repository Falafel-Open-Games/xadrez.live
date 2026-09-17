import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import update_youtube_video_metadata


class SelectedSessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.content_dir = Path(self.tmpdir.name)
        self.addCleanup(self.tmpdir.cleanup)

    def write_session(self, number: str, tone: str) -> None:
        (self.content_dir / f"{number}.md").write_text(
            "+++\n"
            "draft = false\n\n"
            "[extra]\n"
            f"session_number = \"{number}\"\n"
            "youtube_video_id = \"video-id\"\n"
            f"status_tone = \"{tone}\"\n"
            "+++\n",
            encoding="utf-8",
        )

    def test_explicit_scheduled_session_is_selected(self):
        self.write_session("0092", "scheduled")
        with mock.patch.object(update_youtube_video_metadata, "CONTENT_DIR", self.content_dir):
            sessions = update_youtube_video_metadata.selected_sessions({"0092"}, None)
        self.assertEqual(sessions, [update_youtube_video_metadata.Session("0092", "video-id")])

    def test_unqualified_selection_still_excludes_scheduled_sessions(self):
        self.write_session("0092", "scheduled")
        self.write_session("0091", "ended")
        with mock.patch.object(update_youtube_video_metadata, "CONTENT_DIR", self.content_dir):
            sessions = update_youtube_video_metadata.selected_sessions(None, None)
        self.assertEqual(sessions, [update_youtube_video_metadata.Session("0091", "video-id")])


if __name__ == "__main__":
    unittest.main()
