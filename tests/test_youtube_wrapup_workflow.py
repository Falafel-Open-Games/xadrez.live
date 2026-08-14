import io
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import update_youtube_chapters
import update_youtube_live_latency
import youtube_title_options


class GoogleTokenErrorTest(unittest.TestCase):
    def test_invalid_grant_points_to_youtube_reauthorization(self):
        body = b'{"error":"invalid_grant","error_description":"Token has been expired or revoked."}'
        error = urllib.error.HTTPError(
            url=update_youtube_chapters.GOOGLE_TOKEN_URL,
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(body),
        )

        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                update_youtube_chapters.token_request(
                    "client-id",
                    "client-secret",
                    {"grant_type": "refresh_token", "refresh_token": "revoked-token"},
                )

        message = str(raised.exception)
        self.assertIn("invalid_grant", message)
        self.assertIn("YOUTUBE_REFRESH_TOKEN expired or was revoked", message)
        self.assertIn("just youtube-chapters-authorize", message)
        self.assertIn("rerun the wrapup step", message)


class YouTubeTitlePublishStateTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.choices_path = Path(self.tmpdir.name) / "youtube_editorial_choices.json"
        self.choice_patch = mock.patch.object(youtube_title_options, "CHOICES_PATH", self.choices_path)
        self.choice_patch.start()
        self.addCleanup(self.choice_patch.stop)

    def test_selected_title_is_not_treated_as_published_after_failed_publish(self):
        title = "Mate em 1 no tabuleiro, tempo zerado | xadrez depois dos 40 #0060"
        youtube_title_options.remember_options("0060", "title", [title])
        youtube_title_options.remember_selected("0060", "title", title)

        with mock.patch.object(sys, "argv", ["youtube_title_options.py", "0060", "--choose", "--write"]):
            with mock.patch.object(youtube_title_options, "session_context", return_value={"session": "0060"}):
                with mock.patch.object(youtube_title_options, "choose_option", return_value=title):
                    with mock.patch.object(youtube_title_options, "publish_title_if_changed", return_value=0) as publish:
                        with redirect_stdout(io.StringIO()):
                            self.assertEqual(youtube_title_options.main(), 0)

        publish.assert_called_once()
        self.assertEqual(youtube_title_options.selected_choice("0060", "title"), title)
        self.assertEqual(youtube_title_options.published_choice("0060", "title"), title)

    def test_unchanged_title_skips_youtube_only_after_confirmed_publish(self):
        title = "Mate em 1 no tabuleiro, tempo zerado | xadrez depois dos 40 #0060"
        youtube_title_options.remember_options("0060", "title", [title])
        youtube_title_options.remember_selected("0060", "title", title, published_to_youtube=True)

        with mock.patch.object(sys, "argv", ["youtube_title_options.py", "0060", "--choose", "--write"]):
            with mock.patch.object(youtube_title_options, "session_context", return_value={"session": "0060"}):
                with mock.patch.object(youtube_title_options, "choose_option", return_value=title):
                    with mock.patch.object(youtube_title_options, "publish_title_if_changed") as publish:
                        with redirect_stdout(io.StringIO()):
                            self.assertEqual(youtube_title_options.main(), 0)

        publish.assert_not_called()


class YouTubeLiveLatencyTest(unittest.TestCase):
    def test_update_body_sets_ultralow_and_preserves_required_fields(self):
        broadcast = {
            "id": "abc123",
            "snippet": {
                "title": "Sessão #0061",
                "description": "Treino diário",
                "scheduledStartTime": "2026-08-15T11:00:00Z",
            },
            "contentDetails": {
                "enableDvr": True,
                "enableEmbed": True,
                "enableLowLatency": False,
                "monitorStream": {
                    "enableMonitorStream": True,
                    "broadcastStreamDelayMs": 0,
                },
            },
        }

        body = update_youtube_live_latency.update_body(broadcast, "ultraLow")

        self.assertEqual(body["id"], "abc123")
        self.assertEqual(body["snippet"]["title"], "Sessão #0061")
        self.assertEqual(body["snippet"]["description"], "Treino diário")
        self.assertEqual(body["snippet"]["scheduledStartTime"], "2026-08-15T11:00:00Z")
        self.assertEqual(body["contentDetails"]["latencyPreference"], "ultraLow")
        self.assertNotIn("enableLowLatency", body["contentDetails"])
        self.assertTrue(body["contentDetails"]["enableDvr"])
        self.assertTrue(body["contentDetails"]["monitorStream"]["enableMonitorStream"])
        self.assertEqual(body["contentDetails"]["monitorStream"]["broadcastStreamDelayMs"], 0)

    def test_set_latency_updates_live_broadcast_content_details(self):
        broadcast = {
            "id": "abc123",
            "snippet": {"title": "Sessão #0061", "scheduledStartTime": "2026-08-15T11:00:00Z"},
            "status": {"lifeCycleStatus": "ready"},
            "contentDetails": {
                "latencyPreference": "normal",
                "monitorStream": {"enableMonitorStream": True, "broadcastStreamDelayMs": 0},
            },
        }

        with mock.patch.object(update_youtube_live_latency, "fetch_broadcast", return_value=broadcast):
            with mock.patch.object(update_youtube_live_latency, "api_request", return_value={}) as api_request:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(update_youtube_live_latency.set_latency("token", "abc123", "ultraLow", True), 0)

        api_request.assert_called_once()
        _, token = api_request.call_args.args
        self.assertEqual(token, "token")
        self.assertEqual(api_request.call_args.kwargs["method"], "PUT")
        self.assertEqual(api_request.call_args.kwargs["query"], {"part": "snippet,contentDetails"})
        self.assertEqual(api_request.call_args.kwargs["body"]["contentDetails"]["latencyPreference"], "ultraLow")

    def test_live_chat_note_reports_replay_is_not_api_exposed_when_chat_is_present(self):
        broadcast = {
            "snippet": {"liveChatId": "Cg0KC2xpdmUtY2hhdA"},
            "status": {"madeForKids": False},
        }

        self.assertEqual(
            update_youtube_live_latency.live_chat_note(broadcast),
            "live chat present; replay setting is not exposed by API",
        )

    def test_live_chat_note_warns_when_chat_id_is_missing(self):
        broadcast = {
            "snippet": {},
            "status": {"madeForKids": False},
        }

        self.assertEqual(
            update_youtube_live_latency.live_chat_note(broadcast),
            "live chat id not returned; verify chat/replay in Studio",
        )


if __name__ == "__main__":
    unittest.main()
