import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import merge_chat_replays


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


class MergeChatReplaySessionSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.content_dir = Path(self.tmpdir.name)
        patch = mock.patch.object(merge_chat_replays, "CONTENT_DIR", self.content_dir)
        patch.start()
        self.addCleanup(patch.stop)

    def write_session(self, session: str, status_tone: str) -> None:
        (self.content_dir / f"{session}.md").write_text(
            session_file(session, status_tone),
            encoding="utf-8",
        )

    def test_scheduled_session_is_selected(self):
        self.write_session("0094", "scheduled")

        self.assertEqual(merge_chat_replays.session_numbers({"0094"}, None), ["0094"])

    def test_unrelated_status_is_not_selected(self):
        self.write_session("0094", "draft")

        self.assertEqual(merge_chat_replays.session_numbers({"0094"}, None), [])


if __name__ == "__main__":
    unittest.main()
