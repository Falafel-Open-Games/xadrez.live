import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import import_youtube_transcripts


def session_file(session: str, *, skip_transcription: bool = False) -> str:
    skip_line = "skip_transcription = true\n" if skip_transcription else ""
    return f"""+++
title = "Sessão #{session}"
date = 2026-08-16
template = "session.html"
draft = false

[extra]
session_number = "{session}"
youtube_video_id = "abc123def45"
{skip_line}status = "encerrada"
status_tone = "ended"
+++
"""


class ImportYoutubeTranscriptsSessionSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.content_dir = Path(self.tmpdir.name)
        patch = mock.patch.object(import_youtube_transcripts, "CONTENT_DIR", self.content_dir)
        patch.start()
        self.addCleanup(patch.stop)

    def write_session(self, session: str, *, skip_transcription: bool = False) -> Path:
        path = self.content_dir / f"{session}.md"
        path.write_text(session_file(session, skip_transcription=skip_transcription), encoding="utf-8")
        return path

    def test_ended_session_is_selected(self):
        path = self.write_session("0062")

        self.assertEqual(import_youtube_transcripts.session_youtube_ids(), [("abc123def45", "0062", path)])

    def test_skip_transcription_session_is_not_selected(self):
        self.write_session("0062", skip_transcription=True)

        self.assertEqual(import_youtube_transcripts.session_youtube_ids(), [])


if __name__ == "__main__":
    unittest.main()
