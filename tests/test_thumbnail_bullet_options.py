import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import thumbnail_bullet_options


class ThumbnailBulletOptionsTest(unittest.TestCase):
    def test_prompt_omits_clock_metadata_from_timeline_events(self):
        context = {
            "session": "0095",
            "summary_title": "Ruy Lopez e erros no meio-jogo",
            "description": "Uma derrota depois de perder a vantagem.",
            "games": [{"result": "loss", "color": "white", "opening": "Ruy Lopez", "note": "Sem análise."}],
            "timeline": [
                {
                    "kind": "blunder",
                    "move_number": 7,
                    "move": "Bf4",
                    "clock": "7:59",
                    "eval_change": "3.32 → 0.00",
                    "best": "Nxe5",
                    "text": "fcz jogou Bf4 no lance 7, com 7:59 no relógio.",
                }
            ],
            "highlights": [],
        }

        prompt = thumbnail_bullet_options.prompt_for_model(context, 5)

        self.assertNotIn('"clock"', prompt)
        self.assertNotIn("7:59", prompt)
        self.assertNotIn("com 7:59", prompt)
        self.assertIn('"move": "Bf4"', prompt)
        self.assertIn('"eval_change": "3.32 → 0.00"', prompt)

    def test_clock_bullets_require_explicit_editorial_evidence(self):
        context = {
            "summary_title": "Puzzles e rapid",
            "description": "Treino de puzzles e uma partida rapid.",
            "games": [{"note": "Devido ao atraso na live, nao tive tempo de analisar."}],
            "highlights": [],
        }
        raw = json.dumps(
            [
                ["Ruy Lopez", "Capivarada no roque", "Erro no meio-jogo"],
                ["Ruy Lopez", "Relógio forçou erro", "Erro no meio-jogo"],
            ]
        )

        self.assertEqual(
            thumbnail_bullet_options.parse_options(raw, 5, context),
            [["Ruy Lopez", "Capivarada no roque", "Erro no meio-jogo"]],
        )

    def test_explicit_clock_evidence_allows_clock_bullets(self):
        context = {
            "summary_title": "Derrota no tempo",
            "description": "A posição estava ganha, mas o relógio zerou.",
            "games": [],
            "highlights": [],
        }
        options = [["Posição ganha", "Relógio zerou", "Derrota no tempo"]]

        self.assertEqual(thumbnail_bullet_options.options_supported_by_context(options, context), options)

    def test_fallback_does_not_treat_time_to_analyze_as_clock_pressure(self):
        context = {
            "description": "Treino de puzzles e uma partida rapid.",
            "games": [
                {
                    "opening": "Ruy Lopez",
                    "result": "loss",
                    "note": "Devido ao atraso na live, nao tive tempo de analisar. Fica para outro dia.",
                }
            ],
        }

        options = thumbnail_bullet_options.fallback_options(context, 5)

        self.assertFalse(any("relógio" in bullet or "tempo" in bullet for option in options for bullet in option))

    def test_rejects_raw_move_and_lance_bullets(self):
        self.assertFalse(thumbnail_bullet_options.valid_bullet("Bh4 Lance 8"))
        self.assertFalse(thumbnail_bullet_options.valid_bullet("Nfd2 Lance 8"))
        self.assertFalse(thumbnail_bullet_options.valid_bullet("g4 Lance 7"))
        self.assertFalse(thumbnail_bullet_options.valid_bullet("relógio 8 52"))

    def test_keeps_editorial_chess_bullets(self):
        self.assertTrue(thumbnail_bullet_options.valid_bullet("peça pendurada"))
        self.assertTrue(thumbnail_bullet_options.valid_bullet("relógio apertou"))
        self.assertTrue(thumbnail_bullet_options.valid_bullet("decisão crítica"))
        self.assertTrue(thumbnail_bullet_options.valid_bullet("puzzle"))

    def test_filters_sets_with_too_many_coordinate_only_bullets(self):
        options = thumbnail_bullet_options.unique_bullet_sets(
            [
                ["Abertura Chigorin", "Bh4", "Nfd2"],
                ["peça pendurada", "relógio apertou", "decisão crítica"],
            ],
            2,
        )

        self.assertEqual(options, [["peça pendurada", "relógio apertou", "decisão crítica"]])

    def test_prompt_exit_option_returns_no_selection(self):
        options = [["peça pendurada", "relógio apertou", "decisão crítica"]]

        with mock.patch("builtins.input", return_value="2"):
            with redirect_stdout(io.StringIO()):
                selected = thumbnail_bullet_options.choose_with_prompt(options, [])

        self.assertEqual(selected, [])

    def test_gum_exit_option_returns_no_selection(self):
        options = [["peça pendurada", "relógio apertou", "decisão crítica"]]
        result = mock.Mock(returncode=0, stdout=thumbnail_bullet_options.EXIT_OPTION_LABEL + "\n")

        with mock.patch.object(thumbnail_bullet_options.subprocess, "run", return_value=result):
            selected = thumbnail_bullet_options.choose_with_gum(options, [])

        self.assertEqual(selected, [])

    def test_edit_selected_bullets_accepts_empty_input_as_unchanged(self):
        selected = ["peça pendurada", "relógio apertou", "decisão crítica"]

        with mock.patch.object(thumbnail_bullet_options.shutil, "which", return_value=None):
            with mock.patch.object(thumbnail_bullet_options.sys.stdin, "isatty", return_value=True):
                with mock.patch("builtins.input", return_value=""):
                    self.assertEqual(thumbnail_bullet_options.edit_selected_bullets(selected), selected)

    def test_edit_selected_bullets_accepts_pipe_separated_rewrite(self):
        selected = ["peça pendurada", "relógio apertou", "decisão crítica"]

        with mock.patch.object(thumbnail_bullet_options.shutil, "which", return_value=None):
            with mock.patch.object(thumbnail_bullet_options.sys.stdin, "isatty", return_value=True):
                with mock.patch("builtins.input", return_value="Dama sem troca | relógio apertou | final revisado"):
                    self.assertEqual(
                        thumbnail_bullet_options.edit_selected_bullets(selected),
                        ["Dama sem troca", "relógio apertou", "final revisado"],
                    )

    def test_edit_selected_bullets_accepts_puzzle_session_rewrite(self):
        selected = ["puzzle do dia", "mate teórico", "cansaço"]

        with mock.patch.object(thumbnail_bullet_options.shutil, "which", return_value=None):
            with mock.patch.object(thumbnail_bullet_options.sys.stdin, "isatty", return_value=True):
                with mock.patch("builtins.input", return_value="puzzle | mate teórico | cansasso"):
                    self.assertEqual(
                        thumbnail_bullet_options.edit_selected_bullets(selected),
                        ["puzzle", "mate teórico", "cansasso"],
                    )

    def test_edit_selected_bullets_accepts_simple_human_rewrite(self):
        selected = ["peça pendurada", "relógio apertou", "decisão crítica"]

        with mock.patch.object(thumbnail_bullet_options.shutil, "which", return_value=None):
            with mock.patch.object(thumbnail_bullet_options.sys.stdin, "isatty", return_value=True):
                with mock.patch("builtins.input", return_value="treino | lance 6 | mate"):
                    self.assertEqual(
                        thumbnail_bullet_options.edit_selected_bullets(selected),
                        ["treino", "lance 6", "mate"],
                    )

    def test_edit_selected_bullets_explains_empty_and_duplicate_items(self):
        selected = ["peça pendurada", "relógio apertou", "decisão crítica"]

        with mock.patch.object(thumbnail_bullet_options.shutil, "which", return_value=None):
            with mock.patch.object(thumbnail_bullet_options.sys.stdin, "isatty", return_value=True):
                with mock.patch("builtins.input", return_value="mate | | mate"):
                    with redirect_stderr(io.StringIO()) as error:
                        with self.assertRaises(SystemExit):
                            thumbnail_bullet_options.edit_selected_bullets(selected)

        message = error.getvalue()
        self.assertIn("got 1 bullet(s)", message)
        self.assertIn("'<empty>': empty bullet", message)
        self.assertIn("'mate': duplicate bullet", message)

    def test_main_accepts_fewer_openai_options_without_fallback(self):
        options = [
            ["peça pendurada", "relógio apertou", "decisão crítica"],
            ["ataque demorou", "vantagem escapou", "final no tempo"],
        ]

        with mock.patch.dict(thumbnail_bullet_options.os.environ, {"OPENAI_API_KEY": "test-key"}):
            with mock.patch.object(sys, "argv", ["thumbnail_bullet_options.py", "0061"]):
                with mock.patch.object(thumbnail_bullet_options, "load_env_file"):
                    with mock.patch.object(thumbnail_bullet_options, "session_context", return_value={"session": "0061"}):
                        with mock.patch.object(thumbnail_bullet_options, "cached_options", return_value=[]):
                            with mock.patch.object(thumbnail_bullet_options, "openai_options", return_value=options):
                                with mock.patch.object(thumbnail_bullet_options, "fallback_options") as fallback_options:
                                    with mock.patch.object(thumbnail_bullet_options, "remember_options"):
                                        with redirect_stdout(io.StringIO()) as output:
                                            self.assertEqual(thumbnail_bullet_options.main(), 0)

        fallback_options.assert_not_called()
        self.assertIn("warning: OpenAI returned 2 valid thumbnail bullet option(s)", output.getvalue())
        self.assertIn("peça pendurada | relógio apertou | decisão crítica", output.getvalue())

    def test_changed_bullets_force_post_thumb_regeneration(self):
        selected = ["peça pendurada", "relógio apertou", "decisão crítica"]

        with mock.patch.object(sys, "argv", ["thumbnail_bullet_options.py", "0061", "--choose", "--write", "--generate"]):
            with mock.patch.object(thumbnail_bullet_options, "load_env_file"):
                with mock.patch.object(
                    thumbnail_bullet_options,
                    "session_context",
                    return_value={"session": "0061", "summary_title": "Derrota no tempo"},
                ):
                    with mock.patch.object(thumbnail_bullet_options, "cached_options", return_value=[selected]):
                        with mock.patch.object(thumbnail_bullet_options, "choose_option", return_value=selected):
                            with mock.patch.object(thumbnail_bullet_options, "edit_selected_bullets", return_value=selected):
                                with mock.patch.object(thumbnail_bullet_options, "current_thumbnail_notes", return_value=["old", "notes", "here"]):
                                    with mock.patch.object(thumbnail_bullet_options, "selected_bullets", return_value=["old", "notes", "here"]):
                                        with mock.patch.object(thumbnail_bullet_options, "remember_selected"):
                                            with mock.patch.object(thumbnail_bullet_options, "write_thumbnail_notes", return_value=True):
                                                with mock.patch.object(thumbnail_bullet_options, "og_image_path", return_value=Path("thumb.jpg")):
                                                    with mock.patch.object(thumbnail_bullet_options.Path, "exists", return_value=True):
                                                        with mock.patch.object(thumbnail_bullet_options, "run") as run:
                                                            with redirect_stdout(io.StringIO()):
                                                                self.assertEqual(thumbnail_bullet_options.main(), 0)

        run.assert_called_once_with(["just", "post-thumb", "0061", "--force"])


if __name__ == "__main__":
    unittest.main()
