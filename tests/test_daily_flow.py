import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import daily_flow


class DailyFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.content_dir = self.root / "content"
        self.data_dir = self.root / "data"
        self.workflows_dir = self.data_dir / "workflows"
        self.wrap_inbox_dir = self.data_dir / "wrap_inbox"
        self.restream_dir = self.data_dir / "restream_chat_replays"
        self.youtube_chat_dir = self.data_dir / "youtube_chat_replays"
        self.twitch_chat_dir = self.data_dir / "twitch_chat_replays"
        self.downloads_dir = self.root / "Downloads"
        for path in [
            self.content_dir,
            self.workflows_dir,
            self.wrap_inbox_dir,
            self.restream_dir,
            self.youtube_chat_dir,
            self.twitch_chat_dir,
            self.downloads_dir,
        ]:
            path.mkdir(parents=True)
        self.patches = [
            mock.patch.object(daily_flow, "ROOT", self.root),
            mock.patch.object(daily_flow, "CONTENT_DIR", self.content_dir),
            mock.patch.object(daily_flow, "DATA_DIR", self.data_dir),
            mock.patch.object(daily_flow, "WORKFLOWS_DIR", self.workflows_dir),
            mock.patch.object(daily_flow, "WRAP_INBOX_DIR", self.wrap_inbox_dir),
            mock.patch.object(daily_flow, "RESTREAM_CHAT_REPLAYS_DIR", self.restream_dir),
            mock.patch.object(daily_flow, "YOUTUBE_CHAT_REPLAYS_DIR", self.youtube_chat_dir),
            mock.patch.object(daily_flow, "TWITCH_CHAT_REPLAYS_DIR", self.twitch_chat_dir),
            mock.patch.object(daily_flow, "YOUTUBE_METADATA_PATH", self.data_dir / "youtube_video_metadata.toml"),
            mock.patch.object(daily_flow, "DOWNLOADS_DIR", self.downloads_dir),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def write_session(self, session: str) -> None:
        (self.content_dir / f"{session}.md").write_text(
            "+++\n"
            f'title = "Sessao #{session}"\n'
            "date = 2026-09-15\n"
            'template = "session.html"\n'
            "\n"
            "[extra]\n"
            'youtube_video_id = "abc123def45"\n'
            "+++\n",
            encoding="utf-8",
        )

    def write_toml(self, session: str) -> None:
        (self.wrap_inbox_dir / f"{session}.toml").write_text('duration = "1:00"\n', encoding="utf-8")

    def write_restream_chat(self, session: str) -> None:
        (self.restream_dir / f"{session}.json").write_text(
            '{"messages": [{"platform": "YouTube", "author": "Person 1", "text": "bom dia"}]}\n',
            encoding="utf-8",
        )

    def write_youtube_metadata(self, session: str, valid: bool = True) -> None:
        timestamp = 1789550000 if valid else 0
        duration = 3600 if valid else 0
        (self.data_dir / "youtube_video_metadata.toml").write_text(
            f'[sessions."{session}"]\nyoutube_video_id = "abc123def45"\nrelease_timestamp = {timestamp}\nduration_seconds = {duration}\nduration = "1:00:00"\n',
            encoding="utf-8",
        )

    def test_run_restream_import_targets_selected_session(self):
        state = daily_flow.default_state("0090")

        with mock.patch.object(daily_flow, "run_command", return_value=0) as run_command:
            with mock.patch.object(daily_flow, "restream_api_chat_path", return_value=self.restream_dir / "0090.json"):
                self.assertTrue(daily_flow.import_restream_chat(state))

        run_command.assert_called_once_with(
            state,
            "chat",
            [
                "python3",
                "scripts/import_restream_chat_replays.py",
                "--cache-dir",
                "/tmp/xadrez-restream-chat",
                "0090",
            ],
        )

    def test_resolve_chat_imports_restream_and_records_decision(self):
        self.write_session("0090")
        self.write_toml("0090")
        state = daily_flow.default_state("0090")

        def fake_import(import_state):
            self.write_restream_chat("0090")
            daily_flow.mark_done(import_state, "chat", "Restream API fallback accepted")
            return True

        with mock.patch.object(daily_flow, "prompt", return_value="r"):
            with mock.patch.object(daily_flow, "import_restream_chat", side_effect=fake_import):
                self.assertTrue(daily_flow.resolve_chat(state))

        self.assertEqual(state["decisions"]["chat"]["source"], "restream_api")
        self.assertTrue(state["decisions"]["chat"]["accepted_by_user"])

    def test_resolve_chat_accepts_direct_platform_replay_without_prompt(self):
        self.write_session("0090")
        self.write_toml("0090")
        (self.youtube_chat_dir / "0090.json").write_text(
            '{"messages": [{"platform": "YouTube", "author": "@viewer", "text": "bom dia"}]}\n',
            encoding="utf-8",
        )
        state = daily_flow.default_state("0090")

        with mock.patch.object(daily_flow, "prompt") as prompt:
            self.assertTrue(daily_flow.resolve_chat(state))

        prompt.assert_not_called()
        self.assertEqual(state["decisions"]["chat"]["source"], "direct_platform_replays")
        self.assertEqual(state["steps"]["chat"]["status"], "done")

    def test_wrap_command_uses_saved_decisions_without_reprompting(self):
        state = daily_flow.default_state("0090")
        state["decisions"] = {
            "chat": {"source": "restream_api", "accepted_by_user": True},
            "calibration": {"anchor": "first-game"},
            "wrap_session": {"extra_args": ["--skip-build"]},
        }

        self.assertEqual(
            daily_flow.wrap_command(state),
            [
                "just",
                "wrap-session",
                "0090",
                "--calibration-anchor",
                "first-game",
                "--use-restream-api-chat-fallback",
                "--skip-build",
            ],
        )

    def test_resolve_youtube_metadata_marks_valid_metadata_done(self):
        self.write_youtube_metadata("0090")
        state = daily_flow.default_state("0090")

        with mock.patch.object(daily_flow, "run_command", return_value=0) as run_command:
            self.assertTrue(daily_flow.resolve_youtube_metadata(state))

        run_command.assert_called_once_with(
            state,
            "youtube_metadata",
            ["python3", "scripts/update_youtube_video_metadata.py", "0090"],
        )
        self.assertEqual(state["steps"]["youtube_metadata"]["status"], "done")

    def test_resolve_youtube_metadata_blocks_without_release_timestamp(self):
        self.write_youtube_metadata("0090", valid=False)
        state = daily_flow.default_state("0090")

        with mock.patch.object(daily_flow, "run_command", return_value=0):
            with redirect_stdout(io.StringIO()):
                self.assertFalse(daily_flow.resolve_youtube_metadata(state))

        step = state["steps"]["youtube_metadata"]
        self.assertEqual(step["status"], "blocked")
        self.assertTrue(step["retryable"])

    def test_run_command_persists_failed_step(self):
        state = daily_flow.default_state("0090")

        with mock.patch.object(daily_flow.subprocess, "call", return_value=7):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(daily_flow.run_command(state, "wrap_session", ["false"]), 7)

        saved = json.loads((self.workflows_dir / "0090.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["steps"]["wrap_session"]["status"], "failed")
        self.assertEqual(saved["steps"]["wrap_session"]["exit_code"], 7)

    def test_status_does_not_create_workflow_state(self):
        self.write_session("0090")
        self.write_toml("0090")

        with redirect_stdout(io.StringIO()):
            self.assertEqual(daily_flow.show_status("0090"), 0)

        self.assertFalse((self.workflows_dir / "0090.json").exists())

    def test_completed_workflow_is_a_noop_without_restart(self):
        state = daily_flow.default_state("0090")
        state["status"] = "completed"
        daily_flow.save_state(state)

        with mock.patch.object(daily_flow, "run_command") as run_command:
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(daily_flow.continue_workflow("0090", restart=False), 0)

        run_command.assert_not_called()
        self.assertIn("already completed", output.getvalue())

    def test_completed_legacy_workflow_migrates_new_metadata_step_as_skipped(self):
        path = self.workflows_dir / "0090.json"
        path.write_text(
            json.dumps(
                {
                    "session": "0090",
                    "status": "completed",
                    "steps": {
                        "inputs": {"status": "done"},
                        "chat": {"status": "done"},
                        "wrap_session": {"status": "done"},
                        "verify": {"status": "done"},
                        "build": {"status": "done"},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        state = daily_flow.load_state("0090")

        self.assertEqual(state["steps"]["youtube_metadata"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
