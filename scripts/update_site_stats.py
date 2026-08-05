#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
TRANSCRIPTS_DIR = ROOT / "data" / "fcz" / "transcripts"
CHAT_REPLAYS_DIR = ROOT / "data" / "fcz" / "chat_replays"
LICHESS_GAME_ANALYSIS = ROOT / "data" / "fcz" / "lichess_game_analysis.toml"
LICHESS_BLUNDERS_DIR = ROOT / "data" / "fcz" / "lichess_blunders"
OUTPUT = ROOT / "data" / "site_stats.toml"
CHART_WIDTH = 720
CHART_HEIGHT = 260
PLOT_LEFT = 46
PLOT_TOP = 20
PLOT_RIGHT = 694
PLOT_BOTTOM = 212

TRANSCRIPT_SUFFIXES_BY_PRIORITY = [
    "openai-gpt-4o-mini-transcribe.aligned",
    "openai-gpt-4o-transcribe.aligned",
    "openai-gpt-4o-mini-transcribe",
    "openai-gpt-4o-transcribe",
    "faster-whisper",
    "youtube",
]
SELF_CHAT_AUTHORS = {"host", "fczuardi", "@fczuardi", "sedentarismo", "@sedentarismo"}
BLOCKED_CHAT_AUTHORS = {"gsgsgehwge", "@gsgsgehwge"}


@dataclass
class Session:
    number: str
    title: str
    date: date | str
    extra: dict[str, Any]


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


def int_value(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_duration_minutes(value: Any) -> int:
    text = str(value or "").strip().lower()
    if not text:
        return 0

    match = re.fullmatch(r"(\d+):(\d{1,2})", text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))

    hours = 0
    minutes = 0
    hour_match = re.search(r"(\d+)\s*h", text)
    minute_match = re.search(r"(\d+)\s*(?:m|min)", text)
    if hour_match:
        hours = int(hour_match.group(1))
    if minute_match:
        minutes = int(minute_match.group(1))
    if hour_match or minute_match:
        return hours * 60 + minutes

    if text.isdigit():
        return int(text)

    return 0


def format_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h{mins:02d}"
    if hours:
        return f"{hours}h"
    return f"{mins}min"


def format_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def normalize_result(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return "unknown"
    if any(token in text for token in ("draw", "empate")):
        return "draw"
    if any(token in text for token in ("win", "vitória", "vitoria", "ganhei")):
        return "win"
    if any(token in text for token in ("loss", "perdi", "derrota", "timeout", "fail", "resign")):
        return "loss"
    return "other"


def normalize_color(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"white", "brancas", "branco"}:
        return "white"
    if text in {"black", "pretas", "preto"}:
        return "black"
    return "unknown" if not text else text


def front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return {}

    end = text.find("\n+++", 4)
    if end == -1:
        return {}

    try:
        return tomllib.loads(text[4:end])
    except tomllib.TOMLDecodeError:
        return {}


def load_sessions() -> list[Session]:
    sessions = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        data = front_matter(path)
        if data.get("draft") is True:
            continue
        extra = data.get("extra")
        if not isinstance(extra, dict):
            extra = {}
        number = str(extra.get("session_number") or path.stem)
        sessions.append(
            Session(
                number=number,
                title=str(data.get("title") or f"Sessão #{number}"),
                date=data.get("date") or "",
                extra=extra,
            )
        )
    return sessions


def session_games(extra: dict[str, Any]) -> list[dict[str, Any]]:
    games = extra.get("games")
    if isinstance(games, list):
        return [game for game in games if isinstance(game, dict)]

    if extra.get("result") or extra.get("opening") or extra.get("color"):
        return [
            {
                "platform": extra.get("platform") or "lichess",
                "game_url": extra.get("lichess_game_url") or "",
                "result": extra.get("result") or "",
                "color": extra.get("color") or "",
                "opening": extra.get("opening") or "",
            }
        ]

    return []


def puzzle_count(extra: dict[str, Any]) -> int:
    total = 1 if str(extra.get("puzzle_of_the_day_url") or "").strip() else 0
    attempts = extra.get("streak_attempts")
    if not isinstance(attempts, list):
        return total

    solved_values = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        solved = int_value(attempt.get("solved"))
        if solved is not None:
            solved_values.append(solved)
        elif isinstance(attempt.get("puzzles"), list):
            solved_values.append(len(attempt["puzzles"]))

    return total + (max(solved_values) if solved_values else 0)


def iter_text_values(value: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        texts.append(value)
    elif isinstance(value, list):
        for item in value:
            texts.extend(iter_text_values(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "transcript"}:
                texts.extend(iter_text_values(item))
            elif key in {"blocks", "segments", "messages"}:
                texts.extend(iter_text_values(item))
    return texts


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ]+(?:[-'][\wÀ-ÿ]+)?\b", text, flags=re.UNICODE))


def transcript_path_for_session(session_number: str) -> Path | None:
    for suffix in TRANSCRIPT_SUFFIXES_BY_PRIORITY:
        path = TRANSCRIPTS_DIR / f"{session_number}.{suffix}.json"
        if path.exists():
            return path
    return None


def transcript_stats(sessions: list[Session]) -> tuple[int, int, list[dict[str, Any]]]:
    total_words = 0
    counted = []

    for session in sessions:
        path = transcript_path_for_session(session.number)
        if not path:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        words = sum(word_count(text) for text in iter_text_values(data))
        if words <= 0:
            continue
        total_words += words
        counted.append(
            {
                "session_number": session.number,
                "source": str(data.get("source_id") or data.get("source") or path.stem),
                "words": words,
            }
        )

    return len(counted), total_words, counted


def chat_message_count() -> int:
    return sum(item["count"] for item in chat_message_counts_by_session())


def chat_message_counts_by_session() -> list[dict[str, Any]]:
    counts = []
    for path in sorted(CHAT_REPLAYS_DIR.glob("[0-9][0-9][0-9][0-9].json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        messages = data.get("messages")
        if isinstance(messages, list):
            counts.append(
                {
                    "session_number": path.stem,
                    "count": sum(1 for message in messages if is_viewer_chat_message(message)),
                }
            )
    return counts


def is_viewer_chat_message(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    author = str(message.get("author") or "").strip().casefold()
    author = author.removeprefix("@")
    return bool(author) and author not in SELF_CHAT_AUTHORS and author not in BLOCKED_CHAT_AUTHORS


def latest_rating(sessions: list[Session], field: str) -> int:
    for session in reversed(sessions):
        value = int_value(session.extra.get(field))
        if value is not None:
            return value
    return 0


def format_decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def load_lichess_game_analysis() -> dict[tuple[str, int], dict[str, Any]]:
    if not LICHESS_GAME_ANALYSIS.exists():
        return {}
    try:
        data = tomllib.loads(LICHESS_GAME_ANALYSIS.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    rows = data.get("games")
    if not isinstance(rows, list):
        return {}
    analysis = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        session_number = str(row.get("session_number") or "")
        game_index = int_value(row.get("game_index")) or 0
        if session_number and game_index:
            analysis[(session_number, game_index)] = row
    return analysis


def opponent_blunders_by_session() -> Counter[str]:
    counts: Counter[str] = Counter()
    if not LICHESS_BLUNDERS_DIR.exists():
        return counts

    for path in sorted(LICHESS_BLUNDERS_DIR.glob("[0-9][0-9][0-9][0-9].json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        events = data.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if isinstance(event, dict) and event.get("is_self") is False:
                counts[path.stem] += 1
    return counts


def scale_chart_points(values: list[dict[str, Any]], value_key: str = "count") -> dict[str, Any]:
    numeric = [int(item[value_key]) for item in values]
    max_value = max(numeric, default=0)
    y_max = max(1, max_value)
    y_span = PLOT_BOTTOM - PLOT_TOP
    x_span = PLOT_RIGHT - PLOT_LEFT
    denominator = max(len(values) - 1, 1)

    scaled = []
    svg_points = []
    for index, item in enumerate(values):
        value = int(item[value_key])
        x = PLOT_LEFT + (index / denominator) * x_span
        y = PLOT_BOTTOM - (value / y_max) * y_span
        point = {
            **item,
            "x": x,
            "y": y,
            "value": value,
        }
        scaled.append(point)
        svg_points.append(f"{x:.1f},{y:.1f}")

    return {
        "scaled": scaled,
        "svg_points": " ".join(svg_points),
        "max_value": max_value,
        "y_max": y_max,
        "plot_left": PLOT_LEFT,
        "plot_right": PLOT_RIGHT,
        "plot_top": PLOT_TOP,
        "plot_bottom": PLOT_BOTTOM,
        "chart_width": CHART_WIDTH,
        "chart_height": CHART_HEIGHT,
        "x_axis_y": PLOT_BOTTOM,
        "y_max_label_y": PLOT_TOP + 4,
        "y_min_label_y": PLOT_BOTTOM + 4,
        "x_label_y": CHART_HEIGHT - 14,
    }


def render_counter_table(name: str, counter: Counter[str], labels: dict[str, str] | None = None) -> list[str]:
    labels = labels or {}
    lines = []
    for key, count in counter.most_common():
        lines.extend(
            [
                f"[[{name}]]",
                f"key = {toml_string(key)}",
                f"label = {toml_string(labels.get(key, key))}",
                f"count = {count}",
                "",
            ]
        )
    return lines


def build_stats() -> str:
    sessions = load_sessions()
    ended_sessions = [
        session
        for session in sessions
        if str(session.extra.get("status_tone") or "").strip().casefold() not in {"scheduled", "live"}
    ]

    total_minutes = sum(parse_duration_minutes(session.extra.get("duration")) for session in ended_sessions)
    games = []
    for session in ended_sessions:
        for index, game in enumerate(session_games(session.extra), start=1):
            games.append({**game, "_session_number": session.number, "_game_index": index})
    result_counts = Counter(normalize_result(game.get("result")) for game in games)
    color_counts = Counter(normalize_color(game.get("color")) for game in games)
    platform_counts = Counter(str(game.get("platform") or "lichess").strip() or "lichess" for game in games)
    game_analysis = load_lichess_game_analysis()
    analysed_game_rows = [
        game_analysis[(game["_session_number"], game["_game_index"])]
        for game in games
        if (game["_session_number"], game["_game_index"]) in game_analysis
        and game_analysis[(game["_session_number"], game["_game_index"])].get("has_analysis") is True
    ]
    missing_analysis_games = [
        game
        for game in games
        if str(game.get("platform") or "lichess").strip() == "lichess"
        and game.get("game_url")
        and (
            (game["_session_number"], game["_game_index"]) not in game_analysis
            or game_analysis[(game["_session_number"], game["_game_index"])].get("has_analysis") is not True
        )
    ]
    total_blunders = sum(int_value(row.get("blunder")) or 0 for row in analysed_game_rows)
    total_mistakes = sum(int_value(row.get("mistake")) or 0 for row in analysed_game_rows)
    total_inaccuracies = sum(int_value(row.get("inaccuracy")) or 0 for row in analysed_game_rows)
    total_accuracy = sum(int_value(row.get("accuracy")) or 0 for row in analysed_game_rows)
    total_acpl = sum(int_value(row.get("acpl")) or 0 for row in analysed_game_rows)
    analysed_count = len(analysed_game_rows)
    average_blunders = total_blunders / analysed_count if analysed_count else 0
    average_accuracy = total_accuracy / analysed_count if analysed_count else 0
    average_acpl = total_acpl / analysed_count if analysed_count else 0
    blunders_by_session = Counter(
        str(row.get("session_number") or "")
        for row in analysed_game_rows
        for _ in range(int_value(row.get("blunder")) or 0)
    )
    opponent_blunders = opponent_blunders_by_session()
    total_puzzles = sum(puzzle_count(session.extra) for session in ended_sessions)
    best_streak = max((int_value(session.extra.get("streak")) or 0 for session in ended_sessions), default=0)
    transcript_sessions, total_words, transcripts = transcript_stats(ended_sessions)
    chat_counts = chat_message_counts_by_session()
    messages = sum(item["count"] for item in chat_counts)
    average_chat_messages = messages / len(ended_sessions) if ended_sessions else 0
    chat_counts_by_number = {item["session_number"]: item["count"] for item in chat_counts}
    chat_chart_items = [
        {
            "session_number": session.number,
            "title": session.title,
            "summary_title": str(session.extra.get("summary_title") or "").strip(),
            "date": str(session.date),
            "count": chat_counts_by_number.get(session.number, 0),
            "url": f"/fcz/{session.number}/",
        }
        for session in ended_sessions
    ]
    chat_chart = scale_chart_points(chat_chart_items)
    blunder_chart_items = [
        {
            "session_number": session.number,
            "title": session.title,
            "summary_title": str(session.extra.get("summary_title") or "").strip(),
            "date": str(session.date),
            "count": blunders_by_session.get(session.number, 0),
            "self_count": blunders_by_session.get(session.number, 0),
            "opponent_count": opponent_blunders.get(session.number, 0),
            "url": f"/fcz/{session.number}/",
        }
        for session in ended_sessions
    ]
    blunder_chart = scale_chart_points(blunder_chart_items)
    blunder_chart_max_value = max(
        [item["self_count"] for item in blunder_chart_items] + [item["opponent_count"] for item in blunder_chart_items],
        default=0,
    )

    first_session = ended_sessions[0] if ended_sessions else None
    latest_session = ended_sessions[-1] if ended_sessions else None

    lines = [
        "# Generated by scripts/update_site_stats.py; do not edit manually.",
        "",
        "[summary]",
        f"session_count = {len(ended_sessions)}",
        f"session_count_label = {toml_string(format_int(len(ended_sessions)))}",
        f"total_minutes = {total_minutes}",
        f"total_hours = {total_minutes / 60:.2f}",
        f"total_duration_label = {toml_string(format_duration(total_minutes))}",
        f"game_count = {len(games)}",
        f"game_count_label = {toml_string(format_int(len(games)))}",
        f"analysed_game_count = {analysed_count}",
        f"analysed_game_count_label = {toml_string(format_int(analysed_count))}",
        f"missing_game_analysis_count = {len(missing_analysis_games)}",
        f"missing_game_analysis_count_label = {toml_string(format_int(len(missing_analysis_games)))}",
        f"total_blunders = {total_blunders}",
        f"total_blunders_label = {toml_string(format_int(total_blunders))}",
        f"average_blunders = {average_blunders:.2f}",
        f"average_blunders_label = {toml_string(format_decimal(average_blunders))}",
        f"total_mistakes = {total_mistakes}",
        f"total_mistakes_label = {toml_string(format_int(total_mistakes))}",
        f"total_inaccuracies = {total_inaccuracies}",
        f"total_inaccuracies_label = {toml_string(format_int(total_inaccuracies))}",
        f"average_accuracy = {average_accuracy:.2f}",
        f"average_accuracy_label = {toml_string(format_decimal(average_accuracy))}",
        f"average_acpl = {average_acpl:.2f}",
        f"average_acpl_label = {toml_string(format_decimal(average_acpl))}",
        f"puzzles_solved = {total_puzzles}",
        f"puzzles_solved_label = {toml_string(format_int(total_puzzles))}",
        f"best_streak = {best_streak}",
        f"best_streak_label = {toml_string(format_int(best_streak))}",
        f"latest_rapid = {latest_rating(ended_sessions, 'rapid')}",
        f"latest_rapid_label = {toml_string(format_int(latest_rating(ended_sessions, 'rapid')))}",
        f"latest_puzzles = {latest_rating(ended_sessions, 'puzzles')}",
        f"latest_puzzles_label = {toml_string(format_int(latest_rating(ended_sessions, 'puzzles')))}",
        f"transcript_session_count = {transcript_sessions}",
        f"transcript_session_count_label = {toml_string(format_int(transcript_sessions))}",
        f"transcript_word_count = {total_words}",
        f"transcript_word_count_label = {toml_string(format_int(total_words))}",
        f"chat_message_count = {messages}",
        f"chat_message_count_label = {toml_string(format_int(messages))}",
        f"average_chat_messages = {average_chat_messages:.2f}",
        f"average_chat_messages_label = {toml_string(format_decimal(average_chat_messages))}",
        f"first_session = {toml_string(first_session.number if first_session else '')}",
        f"latest_session = {toml_string(latest_session.number if latest_session else '')}",
        f"has_transcripts = {toml_bool(transcript_sessions > 0)}",
        "",
        "[chat_chart]",
        f"label = {toml_string('Mensagens de chat por sessão')}",
        f"color = {toml_string('#80b8ff')}",
        f"point_count = {len(chat_chart_items)}",
        f"first_session = {toml_string(first_session.number if first_session else '')}",
        f"latest_session = {toml_string(latest_session.number if latest_session else '')}",
        f"first_label = {toml_string('#' + first_session.number if first_session else '')}",
        f"latest_label = {toml_string('#' + latest_session.number if latest_session else '')}",
        f"max_value = {chat_chart['max_value']}",
        f"max_value_label = {toml_string(format_int(chat_chart['max_value']))}",
        f"svg_points = {toml_string(chat_chart['svg_points'])}",
        f"plot_left = {chat_chart['plot_left']}",
        f"plot_right = {chat_chart['plot_right']}",
        f"plot_top = {chat_chart['plot_top']}",
        f"plot_bottom = {chat_chart['plot_bottom']}",
        f"y_max_label_y = {chat_chart['y_max_label_y']}",
        f"y_min_label_y = {chat_chart['y_min_label_y']}",
        f"x_label_y = {chat_chart['x_label_y']}",
        f"chart_width = {chat_chart['chart_width']}",
        f"chart_height = {chat_chart['chart_height']}",
        "",
    ]

    for point in chat_chart["scaled"]:
        message_word = "mensagem" if point["count"] == 1 else "mensagens"
        session_label = f"Sessão #{point['session_number']}"
        if point["summary_title"]:
            session_label = f"{session_label}: {point['summary_title']}"
        tooltip = f"{point['count']} {message_word} - {session_label} ({point['date']})"
        lines.extend(
            [
                "[[chat_chart.points]]",
                f"session_number = {toml_string(point['session_number'])}",
                f"title = {toml_string(point['title'])}",
                f"summary_title = {toml_string(point['summary_title'])}",
                f"date = {toml_string(point['date'])}",
                f"count = {point['count']}",
                f"count_label = {toml_string(format_int(point['count']))}",
                f"url = {toml_string(point['url'])}",
                f"x = {point['x']:.1f}",
                f"y = {point['y']:.1f}",
                f"tooltip = {toml_string(tooltip)}",
                "",
            ]
        )

    lines.extend(
        [
            "[blunder_chart]",
            f"label = {toml_string('Capivaradas por sessão')}",
            f"color = {toml_string('#f07178')}",
            f"point_count = {len(blunder_chart_items)}",
            f"first_session = {toml_string(first_session.number if first_session else '')}",
            f"latest_session = {toml_string(latest_session.number if latest_session else '')}",
            f"first_label = {toml_string('#' + first_session.number if first_session else '')}",
            f"latest_label = {toml_string('#' + latest_session.number if latest_session else '')}",
            f"max_value = {blunder_chart_max_value}",
            f"max_value_label = {toml_string(format_int(blunder_chart_max_value))}",
            "",
        ]
    )

    for point in blunder_chart["scaled"]:
        self_word = "capivarada minha" if point["self_count"] == 1 else "capivaradas minhas"
        opponent_word = "do oponente" if point["opponent_count"] == 1 else "dos oponentes"
        session_label = f"Sessão #{point['session_number']}"
        if point["summary_title"]:
            session_label = f"{session_label}: {point['summary_title']}"
        tooltip = (
            f"{point['self_count']} {self_word}; "
            f"{point['opponent_count']} {opponent_word} - {session_label} ({point['date']})"
        )
        lines.extend(
            [
                "[[blunder_chart.points]]",
                f"session_number = {toml_string(point['session_number'])}",
                f"title = {toml_string(point['title'])}",
                f"summary_title = {toml_string(point['summary_title'])}",
                f"date = {toml_string(point['date'])}",
                f"count = {point['count']}",
                f"count_label = {toml_string(format_int(point['count']))}",
                f"self_count = {point['self_count']}",
                f"self_count_label = {toml_string(format_int(point['self_count']))}",
                f"opponent_count = {point['opponent_count']}",
                f"opponent_count_label = {toml_string(format_int(point['opponent_count']))}",
                f"url = {toml_string(point['url'])}",
                f"tooltip = {toml_string(tooltip)}",
                "",
            ]
        )

    lines.extend(
        render_counter_table(
            "results",
            result_counts,
            {
                "win": "Vitórias",
                "loss": "Derrotas",
                "draw": "Empates",
                "other": "Outros",
                "unknown": "Sem resultado",
            },
        )
    )
    lines.extend(
        render_counter_table(
            "colors",
            color_counts,
            {
                "white": "Brancas",
                "black": "Pretas",
                "unknown": "Sem cor",
            },
        )
    )
    lines.extend(render_counter_table("platforms", platform_counts))

    for game in missing_analysis_games:
        lines.extend(
            [
                "[[missing_game_analysis]]",
                f"session_number = {toml_string(game['_session_number'])}",
                f"game_index = {game['_game_index']}",
                f"url = {toml_string(str(game.get('game_url') or ''))}",
                "",
            ]
        )

    for transcript in transcripts:
        lines.extend(
            [
                "[[transcripts]]",
                f"session_number = {toml_string(transcript['session_number'])}",
                f"source = {toml_string(transcript['source'])}",
                f"words = {transcript['words']}",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    OUTPUT.write_text(build_stats(), encoding="utf-8")
    print(f"Updated {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
