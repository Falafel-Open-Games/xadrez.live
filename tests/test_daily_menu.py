import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import daily_menu


class DailyMenuStateTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.content_dir = self.root / "content"
        self.wrap_inbox_dir = self.root / "wrap_inbox"
        self.wrap_sessions_dir = self.root / "wrap_sessions"
        self.transcripts_dir = self.root / "transcripts"
        self.highlights_dir = self.root / "highlights"
        self.downloads_dir = self.root / "Downloads"
        self.local_recording_dir = self.root / "Videos"
        for path in [
            self.content_dir,
            self.wrap_inbox_dir,
            self.wrap_sessions_dir,
            self.transcripts_dir,
            self.highlights_dir,
            self.downloads_dir,
            self.local_recording_dir,
        ]:
            path.mkdir()
        self.patches = [
            mock.patch.object(daily_menu, "CONTENT_DIR", self.content_dir),
            mock.patch.object(daily_menu, "WRAP_INBOX_DIR", self.wrap_inbox_dir),
            mock.patch.object(daily_menu, "WRAP_SESSIONS_DIR", self.wrap_sessions_dir),
            mock.patch.object(daily_menu, "TRANSCRIPTS_DIR", self.transcripts_dir),
            mock.patch.object(daily_menu, "HIGHLIGHTS_DIR", self.highlights_dir),
            mock.patch.object(daily_menu, "DOWNLOADS_DIR", self.downloads_dir),
            mock.patch.object(daily_menu, "DEFAULT_LOCAL_RECORDING_DIR", self.local_recording_dir),
            mock.patch.object(daily_menu, "CACHE_PATH", self.root / "daily_menu.json"),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def write_session(self, session: str, extra: str = "") -> None:
        (self.content_dir / f"{session}.md").write_text(
            "+++\n"
            f'title = "Sessão #{session}"\n'
            "date = 2026-08-25\n"
            'template = "session.html"\n'
            "\n"
            "[extra]\n"
            f"{extra}"
            "+++\n",
            encoding="utf-8",
        )

    def state_for(self, key: str, session: str) -> daily_menu.ActionState:
        return daily_menu.action_state(next(action for action in daily_menu.ACTIONS if action.key == key), session)

    def test_session_actions_block_when_markdown_is_missing(self):
        state = self.state_for("wrap-session", "0071")

        self.assertEqual(state.status, "blocked")
        self.assertIn("missing content/fcz/0071.md", state.detail)

    def test_wrap_session_is_ready_when_userscript_inputs_exist(self):
        self.write_session("0071")
        (self.wrap_inbox_dir / "0071.toml").write_text("duration = \"1:00\"\n", encoding="utf-8")
        (self.wrap_inbox_dir / "0071-chat.json").write_text("{}\n", encoding="utf-8")

        state = self.state_for("wrap-session", "0071")

        self.assertEqual(state.status, "ready")

    def test_running_wrap_state_with_live_pid_is_ongoing_and_not_selectable(self):
        self.write_session("0071")
        (self.wrap_inbox_dir / "0071.toml").write_text("duration = \"1:00\"\n", encoding="utf-8")
        (self.wrap_inbox_dir / "0071-chat.json").write_text("{}\n", encoding="utf-8")
        (self.wrap_sessions_dir / "0071.json").write_text(
            json.dumps({"status": "running", "pid": os.getpid()}) + "\n",
            encoding="utf-8",
        )

        state = self.state_for("wrap-session", "0071")

        self.assertEqual(state.status, "ongoing")
        self.assertFalse(state.selectable)

    def test_running_wrap_state_without_live_pid_is_done_and_rerunnable(self):
        self.write_session("0071")
        (self.wrap_inbox_dir / "0071.toml").write_text("duration = \"1:00\"\n", encoding="utf-8")
        (self.wrap_inbox_dir / "0071-chat.json").write_text("{}\n", encoding="utf-8")
        (self.wrap_sessions_dir / "0071.json").write_text('{"status": "running"}\n', encoding="utf-8")

        state = self.state_for("wrap-session", "0071")

        self.assertEqual(state.status, "done")
        self.assertTrue(state.selectable)

    def test_completed_wrap_state_is_done_and_rerunnable(self):
        self.write_session("0071")
        (self.wrap_inbox_dir / "0071.toml").write_text("duration = \"1:00\"\n", encoding="utf-8")
        (self.wrap_inbox_dir / "0071-chat.json").write_text("{}\n", encoding="utf-8")
        (self.wrap_sessions_dir / "0071.json").write_text('{"status": "completed"}\n', encoding="utf-8")

        state = self.state_for("wrap-session", "0071")

        self.assertEqual(state.status, "done")
        self.assertTrue(state.selectable)

    def test_legacy_wrap_state_without_completion_marker_is_done_and_rerunnable(self):
        self.write_session("0071")
        (self.wrap_inbox_dir / "0071.toml").write_text("duration = \"1:00\"\n", encoding="utf-8")
        (self.wrap_inbox_dir / "0071-chat.json").write_text("{}\n", encoding="utf-8")
        path = self.wrap_sessions_dir / "0071.json"
        path.write_text('{"session": "0071"}\n', encoding="utf-8")

        state = self.state_for("wrap-session", "0071")

        self.assertEqual(state.status, "done")
        self.assertTrue(state.selectable)

    def test_calibration_is_not_a_separate_menu_action(self):
        self.assertNotIn("calibrate-offset", [action.key for action in daily_menu.ACTIONS])

    def test_wrap_command_prompts_for_calibration_anchor(self):
        action = next(action for action in daily_menu.ACTIONS if action.key == "wrap-session")

        with mock.patch.object(daily_menu, "prompt", side_effect=["f", "--yes"]):
            command = daily_menu.command_for(action, "0071")

        self.assertEqual(
            command,
            ["just", "wrap-session", "0071", "--calibration-anchor", "first-game", "--yes"],
        )

    def test_realign_blocks_until_faster_whisper_transcript_exists(self):
        self.write_session("0071", 'youtube_video_id = "abc123"\n')

        blocked = self.state_for("realign-highlights", "0071")
        self.assertEqual(blocked.status, "blocked")

        (self.transcripts_dir / "0071.faster-whisper.json").write_text("{}\n", encoding="utf-8")
        ready = self.state_for("realign-highlights", "0071")
        self.assertEqual(ready.status, "ready")

    def test_faster_whisper_is_ready_with_local_recording_without_youtube_id(self):
        self.write_session("0071", 'youtube_video_id = ""\n')
        (self.local_recording_dir / "0071-local.mp4").write_text("recording", encoding="utf-8")

        state = self.state_for("faster-whisper", "0071")

        self.assertEqual(state.status, "ready")
        self.assertEqual(state.detail, "local recording found")

    def test_faster_whisper_blocks_without_local_recording_or_youtube_id(self):
        self.write_session("0071", 'youtube_video_id = ""\n')

        state = self.state_for("faster-whisper", "0071")

        self.assertEqual(state.status, "blocked")
        self.assertIn("missing local recording", state.detail)

    def test_cached_session_is_normalized_and_loaded(self):
        daily_menu.save_cached_session("71")

        self.assertEqual(daily_menu.load_cached_session(), "0071")
        self.assertEqual(json.loads(daily_menu.CACHE_PATH.read_text(encoding="utf-8")), {"last_session": "0071"})


if __name__ == "__main__":
    unittest.main()
