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


if __name__ == "__main__":
    unittest.main()
