import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import import_whisper_transcripts


def session_file(session: str, *, status: str, status_tone: str, youtube_id: str = "abc123def45") -> str:
    return f"""+++
title = "Sessão #{session}"
date = 2026-08-16
template = "session.html"
draft = false

[extra]
session_number = "{session}"
youtube_video_id = "{youtube_id}"
status = "{status}"
status_tone = "{status_tone}"
+++
"""


class ImportWhisperSessionSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.content_dir = self.root / "content"
        self.wrap_inbox_dir = self.root / "wrap_inbox"
        self.downloads_dir = self.root / "Downloads"
        self.content_dir.mkdir()
        self.wrap_inbox_dir.mkdir()
        self.downloads_dir.mkdir()

        patches = [
            mock.patch.object(import_whisper_transcripts, "CONTENT_DIR", self.content_dir),
            mock.patch.object(import_whisper_transcripts, "WRAP_INBOX_DIR", self.wrap_inbox_dir),
            mock.patch.object(import_whisper_transcripts, "DOWNLOADS_DIR", self.downloads_dir),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def write_session(self, session: str, *, status: str = "marcada para 09:30", status_tone: str = "scheduled") -> Path:
        path = self.content_dir / f"{session}.md"
        path.write_text(session_file(session, status=status, status_tone=status_tone), encoding="utf-8")
        return path

    def test_scheduled_session_without_wrap_toml_is_not_selected(self):
        self.write_session("0062")

        self.assertEqual(import_whisper_transcripts.session_youtube_ids(), [])

    def test_scheduled_session_with_downloads_wrap_toml_is_selected(self):
        path = self.write_session("0062")
        (self.downloads_dir / "0062.toml").write_text("[extra]\nduration = \"1:00:00\"\n", encoding="utf-8")

        self.assertEqual(import_whisper_transcripts.session_youtube_ids(), [("abc123def45", "0062", path)])

    def test_scheduled_session_with_inbox_wrap_toml_is_selected(self):
        path = self.write_session("0062")
        (self.wrap_inbox_dir / "0062.toml").write_text("[extra]\nduration = \"1:00:00\"\n", encoding="utf-8")

        self.assertEqual(import_whisper_transcripts.session_youtube_ids(), [("abc123def45", "0062", path)])

    def test_ended_session_is_selected_without_wrap_toml(self):
        path = self.write_session("0062", status="encerrada", status_tone="ended")

        self.assertEqual(import_whisper_transcripts.session_youtube_ids(), [("abc123def45", "0062", path)])

    def test_selected_sessions_accepts_unpadded_session_number(self):
        path = self.write_session("0065", status="encerrada", status_tone="ended")
        sessions = import_whisper_transcripts.session_youtube_ids()

        self.assertEqual(
            import_whisper_transcripts.selected_sessions(sessions, {"65"}, None),
            [("abc123def45", "0065", path)],
        )

    def test_default_prompt_biases_lichess_spelling(self):
        prompt = import_whisper_transcripts.DEFAULT_INITIAL_PROMPT

        self.assertIn("Lichess", prompt)
        self.assertIn("lichess.org", prompt)
        self.assertIn("lichez", prompt)
        self.assertIn("lichez.org", prompt)
        self.assertIn("lixez", prompt)
        self.assertIn("aproximações fonéticas", prompt)

    def test_default_prompt_biases_twitch_raid_spelling(self):
        prompt = import_whisper_transcripts.DEFAULT_INITIAL_PROMPT

        self.assertIn("Raid é a funcionalidade da Twitch", prompt)
        self.assertIn("raid, não rage", prompt)

    def test_default_prompt_biases_hobby_spelling(self):
        prompt = import_whisper_transcripts.DEFAULT_INITIAL_PROMPT

        self.assertIn("hobby, hobbista", prompt)
        self.assertIn("transcreva com h", prompt)
        self.assertIn("Robista", prompt)


if __name__ == "__main__":
    unittest.main()
