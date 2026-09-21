import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import import_youtube_chat_replays


def session_file(session: str, status_tone: str) -> str:
    status = "encerrada" if status_tone == "ended" else "marcada para 09:00"
    return f'''+++
title = "Sessão #{session}"
date = 2026-09-21
template = "session.html"
draft = false

[extra]
session_number = "{session}"
youtube_video_id = "abc123def45"
status = "{status}"
status_tone = "{status_tone}"
+++
'''


class ImportYoutubeChatReplaySessionSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.content_dir = Path(self.tmpdir.name)
        patch = mock.patch.object(import_youtube_chat_replays, "CONTENT_DIR", self.content_dir)
        patch.start()
        self.addCleanup(patch.stop)

    def write_session(self, session: str, status_tone: str) -> Path:
        path = self.content_dir / f"{session}.md"
        path.write_text(session_file(session, status_tone), encoding="utf-8")
        return path

    def test_ended_session_is_selected(self):
        path = self.write_session("0093", "ended")

        self.assertEqual(
            import_youtube_chat_replays.session_youtube_ids(),
            [("abc123def45", "0093", path)],
        )

    def test_scheduled_session_is_selected(self):
        path = self.write_session("0094", "scheduled")

        self.assertEqual(
            import_youtube_chat_replays.session_youtube_ids(),
            [("abc123def45", "0094", path)],
        )

    def test_unrelated_status_is_not_selected(self):
        self.write_session("0094", "draft")

        self.assertEqual(import_youtube_chat_replays.session_youtube_ids(), [])


if __name__ == "__main__":
    unittest.main()
