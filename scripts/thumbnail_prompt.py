#!/usr/bin/env python3
import sys
import tomllib
from pathlib import Path


RESULT_LABELS = {
    "win": "vitória",
    "won": "vitória",
    "loss": "derrota",
    "lost": "derrota",
    "draw": "empate",
}

COLOR_LABELS = {
    "white": "brancas",
    "black": "pretas",
}


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def extract_front_matter(text, path):
    if not text.startswith("+++"):
        fail(f"missing TOML front matter in {path}")

    marker = "\n+++"
    end = text.find(marker, 3)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")

    return text[3:end].strip()


def load_extra(session):
    path = Path("content") / "fcz" / f"{session}.md"
    if not path.exists():
        fail(f"session file not found: {path}")

    front_matter = extract_front_matter(path.read_text(encoding="utf-8"), path)

    try:
        data = tomllib.loads(front_matter)
    except tomllib.TOMLDecodeError as error:
        fail(f"malformed TOML front matter in {path}: {error}")

    extra = data.get("extra")
    if not isinstance(extra, dict):
        fail(f"missing [extra] in {path}")

    return extra


def value(extra, key, default=""):
    raw = extra.get(key, default)
    if raw is None:
        return default
    return str(raw).strip()


def require_values(extra, keys):
    missing = [key for key in keys if not value(extra, key)]
    if missing:
        fail(f"missing required post thumbnail field(s): {', '.join(missing)}")


def result_label(result):
    result = result.strip()
    return RESULT_LABELS.get(result.lower(), result or "treino")


def color_label(color):
    color = color.strip()
    return COLOR_LABELS.get(color.lower(), color)


def short_opening(opening):
    if ":" in opening:
        return opening.split(":", 1)[1].strip()
    return opening.strip()


def game_platform(game):
    platform = value(game, "platform")
    if platform:
        return platform
    if value(game, "lichess_game_url"):
        return "lichess"
    if "chess.com" in value(game, "game_url"):
        return "chess.com"
    return ""


def featured_game(extra):
    games = extra.get("games")
    if isinstance(games, list) and games:
        for game in games:
            if isinstance(game, dict) and value(game, "result").lower() in ("win", "won"):
                return game

        last_game = games[-1]
        if isinstance(last_game, dict):
            return last_game
    return extra


def streak_value(extra):
    explicit = value(extra, "streak")
    if explicit:
        return explicit

    attempts = extra.get("streak_attempts")
    if not isinstance(attempts, list):
        return ""

    solved_values = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        solved = value(attempt, "solved")
        if solved.isdigit():
            solved_values.append(int(solved))

    return str(max(solved_values)) if solved_values else ""


def post_data_block(extra):
    require_values(extra, ["duration", "rapid", "puzzles"])

    game = featured_game(extra)
    opening = short_opening(value(game, "opening"))
    if not opening and game_platform(game) == "chess.com":
        opening = "não informada"
    return f"""session number: {value(extra, "session_number")}
status banner: live encerrada
duration: {value(extra, "duration")}
rapid: {value(extra, "rapid")}
puzzles: {value(extra, "puzzles")}
streak: {streak_value(extra)}
resultado: {result_label(value(game, "result"))}
cor: {color_label(value(game, "color"))}
abertura: {opening}
session context: {value(extra, "description")}
side notebook notes: create 2 to 4 very short Portuguese bullet notes from the structured data and session context above; each bullet must be 2 to 5 words, with no full sentences and no line wrapping"""


def pre_data_block(extra):
    return f"""session number: {value(extra, "session_number")}
time: {value(extra, "time")}
timezone: BRT
live badge: ao vivo
side notebook notes: create 2 or 3 short natural Portuguese notes for the planned session, such as puzzle do dia, rapid 10 min, and revisar abertura"""


def prompt(kind, data_block):
    label = "post-session" if kind == "post" else "pre-live"
    return f"""Use the provided image as the exact reference and base template.

This is a fill-in edit, not a redesign.

Image A is the blank {label} thumbnail template.
Preserve the same composition, matcha-green palette, notebook layout, side study notebook, matcha mug, calm chess diary style, typography style, and overall structure.

Only fill the blank placeholder content with the exact values below.

{data_block}

Main title must remain exactly:
"praticando xadrez depois dos 40"

For the side study notebook:
Keep the hand-drawn chessboard position and notebook layout.
Use compact handwritten bullet notes only.
Do not write paragraphs, long sentences, explanations, or diary-style prose in the side notebook.
If there is not enough space, prefer fewer shorter bullets over more text.
The side notebook notes should look like small labels, not a written recap.

Important:
- preserve the layout
- do not redesign the image
- do not change the palette
- do not add extra decorative clutter
- do not invent extra stats
- keep all text clean, aligned, and readable"""


def main():
    if len(sys.argv) not in (2, 3):
        fail("usage: thumbnail_prompt.py SESSION [pre|post]")

    session = sys.argv[1]
    kind = sys.argv[2] if len(sys.argv) == 3 else "post"
    if kind not in ("pre", "post"):
        fail(f"invalid KIND value: {kind}; expected 'pre' or 'post'")

    extra = load_extra(session)
    data_block = post_data_block(extra) if kind == "post" else pre_data_block(extra)
    print(prompt(kind, data_block))


if __name__ == "__main__":
    main()
