#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DATA_DIR = ROOT / "data" / "fcz"
WRAP_DIR = DATA_DIR / "wrap_sessions"
RESTREAM_DIR = DATA_DIR / "restream_chat_replays"
INBOX_DIR = DATA_DIR / "wrap_inbox"
DOWNLOADS_DIR = Path.home() / "Downloads"
NEXT_SESSION_CACHE_KEY = "next_session_answers"
SESSION_EDITORIAL_CHOICES_PATH = DATA_DIR / "session_editorial_choices.json"
YOUTUBE_EDITORIAL_CHOICES_PATH = DATA_DIR / "youtube_editorial_choices.json"
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
LICHESS_USERNAME = "fcz"
ARRAY_REPLACE_KEYS = {"streak_attempts", "storm_attempts", "practice_sets", "games", "supporters"}
TIMED_PUZZLE_ATTEMPT_KEYS = {"streak_attempts", "storm_attempts"}
SELF_SUPPORTERS = {
    ("youtube", "fczuardi"),
    ("twitch", "sedentarismo"),
}
SELF_HANDLES = {handle for _platform, handle in SELF_SUPPORTERS}
AGGREGATOR_PLATFORMS = {"restream", "restream.io"}
EXTRA_SCALAR_ORDER = [
    "puzzle_of_the_day_url",
    "puzzle_of_the_day_recorded_at",
    "puzzle_of_the_day_event",
    "streak",
    "description",
    "summary_title",
    "description_notes",
    "duration",
    "rapid",
    "puzzles",
    "session_number",
    "youtube_video_id",
    "og_image",
    "time",
    "status",
    "status_tone",
    "lichess_video_offset_seconds",
    "lichess_url",
    "tagline",
    "streak_goal",
    "thumbnail_notes",
    "practice_notes",
    "practice_notes_recorded_at",
    "practice_notes_event",
]
TABLE_FIELD_ORDER = {
    "extra.supporters": ["platform", "name", "url"],
}
PLACEHOLDER_DESCRIPTION = "Treino de puzzles e uma partida rapid."
PLACEHOLDER_SUMMARY_TITLE = "Puzzles e rapid"


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def extract_front_matter(text: str, path: Path) -> tuple[str, str]:
    if not text.startswith("+++\n"):
        fail(f"missing TOML front matter in {path}")
    end = text.find("\n+++", 4)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")
    return text[4:end], text[end + len("\n+++") :]


def read_session(session: str) -> tuple[Path, dict[str, Any], str]:
    path = CONTENT_DIR / f"{session}.md"
    if not path.exists():
        fail(f"session not found: {path}")
    front_matter, body = extract_front_matter(path.read_text(encoding="utf-8"), path)
    return path, tomllib.loads(front_matter), body


def toml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def toml_multiline(value: str) -> str:
    escaped = value.replace('"""', '\\"\\"\\"')
    return f'"""\n{escaped}\n"""'


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    text = str(value)
    if "\n" in text:
        return toml_multiline(text.strip("\n"))
    return toml_quote(text)


def sort_keys(mapping: dict[str, Any], preferred: list[str] | None = None) -> list[str]:
    preferred = preferred or []
    seen = [key for key in preferred if key in mapping]
    rest = sorted(key for key in mapping if key not in seen)
    return [*seen, *rest]


def render_table(
    lines: list[str],
    path: str,
    data: dict[str, Any],
    preferred: list[str] | None = None,
    emit_header: bool = True,
) -> None:
    preferred = TABLE_FIELD_ORDER.get(path, preferred)
    scalar_keys = []
    nested_dict_keys = []
    array_table_keys = []
    for key in sort_keys(data, preferred):
        value = data[key]
        if isinstance(value, dict):
            nested_dict_keys.append(key)
        elif isinstance(value, list) and any(isinstance(item, dict) for item in value):
            array_table_keys.append(key)
        else:
            scalar_keys.append(key)

    if path and emit_header:
        lines.append(f"[{path}]")
    for key in scalar_keys:
        lines.append(f"{key} = {toml_value(data[key])}")
    if scalar_keys:
        lines.append("")

    for key in nested_dict_keys:
        render_table(lines, f"{path}.{key}" if path else key, data[key])

    for key in array_table_keys:
        value = data[key]
        table_path = f"{path}.{key}" if path else key
        for item in value:
            if not isinstance(item, dict):
                continue
            lines.append(f"[[{table_path}]]")
            render_table(lines, table_path, item, emit_header=False)


def render_front_matter(data: dict[str, Any]) -> str:
    lines = ["+++"]
    root = {key: value for key, value in data.items() if key != "extra"}
    for key in sort_keys(root, ["title", "date", "template", "draft"]):
        lines.append(f"{key} = {toml_value(root[key])}")
    lines.append("")
    extra = data.get("extra")
    if isinstance(extra, dict):
        render_table(lines, "extra", extra, EXTRA_SCALAR_ORDER)
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("+++")
    return "\n".join(lines)


def write_session(path: Path, data: dict[str, Any], body: str) -> None:
    path.write_text(render_front_matter(data) + body, encoding="utf-8")


def compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def selected_youtube_editorial_choice(session: str, key: str) -> str:
    if not YOUTUBE_EDITORIAL_CHOICES_PATH.exists():
        return ""
    try:
        data = json.loads(YOUTUBE_EDITORIAL_CHOICES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        return ""
    item = sessions.get(session, {}).get(key)
    if not isinstance(item, dict):
        return ""
    selected = item.get("selected")
    return compact_spaces(str(selected or ""))


def selected_session_editorial_choice(session: str, key: str) -> str:
    if not SESSION_EDITORIAL_CHOICES_PATH.exists():
        return ""
    try:
        data = json.loads(SESSION_EDITORIAL_CHOICES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        return ""
    item = sessions.get(session, {}).get(key)
    if not isinstance(item, dict):
        return ""
    selected = item.get("selected")
    return compact_spaces(str(selected or ""))


def apply_selected_editorial_choices(session: str, data: dict[str, Any]) -> list[str]:
    extra = data.setdefault("extra", {})
    if not isinstance(extra, dict):
        fail("[extra] is not a table")

    updated = []
    current_description = compact_spaces(str(extra.get("description") or ""))
    selected_hook = selected_youtube_editorial_choice(session, "description_hooks")
    if selected_hook and current_description in {"", PLACEHOLDER_DESCRIPTION}:
        extra["description"] = selected_hook
        updated.append("description")

    current_summary = compact_spaces(str(extra.get("summary_title") or ""))
    selected_summary = selected_session_editorial_choice(session, "summary_titles")
    if selected_summary and current_summary in {"", PLACEHOLDER_SUMMARY_TITLE}:
        extra["summary_title"] = selected_summary
        updated.append("summary_title")

    return updated


def load_wrap_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        fail(f"invalid wrap TOML in {path}: {error}")


def wrap_extra_list(wrap: dict[str, Any], key: str) -> list[dict[str, Any]]:
    extra = wrap.get("extra")
    if not isinstance(extra, dict):
        return []
    value = extra.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def summarize_wrap_toml(session: str, wrap: dict[str, Any], path: Path) -> str:
    lines = [
        "",
        f"Resumo do TOML importado para a sessão {session}",
        f"Fonte: {path}",
        "",
    ]

    puzzle_url = str(wrap.get("puzzle_of_the_day_url") or "").strip()
    recorded_at = str(wrap.get("puzzle_of_the_day_recorded_at") or "").strip()
    lines.append("Puzzle do dia:")
    lines.append(f"- {puzzle_url}" if puzzle_url else "- ausente")
    if recorded_at:
        lines.append(f"- registrado em {recorded_at}")

    practice_sets = wrap_extra_list(wrap, "practice_sets")
    lines.append("")
    lines.append(f"Práticas: {len(practice_sets)} bloco(s)")
    for index, practice_set in enumerate(practice_sets, start=1):
        title = str(practice_set.get("title") or "sem título").strip()
        exercises = practice_set.get("exercises")
        exercise_count = len(exercises) if isinstance(exercises, list) else 0
        url = str(practice_set.get("url") or "").strip()
        lines.append(f"{index}. {title} ({exercise_count} exercício(s))")
        if url:
            lines.append(f"   {url}")

    games = wrap_extra_list(wrap, "games")
    lines.append("")
    lines.append(f"Partidas: {len(games)}")
    for index, game in enumerate(games, start=1):
        game_id = str(game.get("game_id") or "").strip()
        result = str(game.get("result") or "sem resultado").strip()
        color = str(game.get("color") or "sem cor").strip()
        opening = str(game.get("opening") or "").strip()
        game_url = str(game.get("game_url") or game.get("lichess_game_url") or "").strip()
        heading = f"{index}. {result}, {color}"
        if game_id:
            heading += f", {game_id}"
        lines.append(heading)
        if opening:
            lines.append(f"   abertura: {opening}")
        if game_url:
            lines.append(f"   {game_url}")

    streak_attempts = wrap_extra_list(wrap, "streak_attempts")
    lines.append("")
    lines.append(f"Puzzle Streak: {len(streak_attempts)} tentativa(s)")
    for index, attempt in enumerate(streak_attempts, start=1):
        puzzles = attempt.get("puzzles")
        puzzle_count = len(puzzles) if isinstance(puzzles, list) else 0
        solved = attempt.get("solved")
        detail = f"{index}. {puzzle_count} puzzle(s)"
        if solved not in (None, ""):
            detail += f", {solved} resolvido(s)"
        lines.append(detail)

    storm_attempts = wrap_extra_list(wrap, "storm_attempts")
    lines.append("")
    lines.append(f"Puzzle Storm: {len(storm_attempts)} tentativa(s)")
    for index, attempt in enumerate(storm_attempts, start=1):
        puzzles = attempt.get("puzzles")
        puzzle_count = len(puzzles) if isinstance(puzzles, list) else 0
        score = attempt.get("score")
        detail = f"{index}. {puzzle_count} puzzle(s)"
        if score not in (None, ""):
            detail += f", {score} ponto(s)"
        lines.append(detail)

    supporters = wrap_extra_list(wrap, "supporters")
    if supporters:
        lines.append("")
        lines.append(f"Apoiadores no TOML: {len(supporters)}")

    scalar_keys = ["duration", "rapid", "puzzles", "practice_notes"]
    scalars = [f"{key}={wrap[key]}" for key in scalar_keys if str(wrap.get(key) or "").strip()]
    if scalars:
        lines.append("")
        lines.append("Outros campos: " + ", ".join(scalars))

    return "\n".join(lines)


def confirm_wrap_toml(session: str, wrap: dict[str, Any], path: Path, assume_yes: bool) -> None:
    print(summarize_wrap_toml(session, wrap, path))
    print("")
    if assume_yes:
        print(f"{session}: confirmação do TOML pulada por --yes")
        return
    if not sys.stdin.isatty():
        fail("confirmação interativa indisponível; rode em um terminal ou passe --yes")
    if not confirm(f"Aplicar este TOML à sessão {session}?"):
        fail("wrap cancelado antes de aplicar o TOML")


def apply_wrap_toml(session: str, data: dict[str, Any], wrap: dict[str, Any]) -> dict[str, Any]:
    extra = data.setdefault("extra", {})
    if not isinstance(extra, dict):
        fail(f"{session}: [extra] is not a table")

    incoming_extra = wrap.get("extra")
    for key, value in wrap.items():
        if key == "extra":
            continue
        extra[key] = value

    if isinstance(incoming_extra, dict):
        for key in TIMED_PUZZLE_ATTEMPT_KEYS:
            if key not in incoming_extra and key in extra:
                del extra[key]
        for key, value in incoming_extra.items():
            if key in ARRAY_REPLACE_KEYS:
                extra[key] = value
            elif isinstance(value, dict) and isinstance(extra.get(key), dict):
                extra[key].update(value)
            else:
                extra[key] = value

    extra["status"] = "encerrada"
    extra["status_tone"] = "ended"
    extra["session_number"] = session
    clean_empty_generated_entries(extra)
    return data


def has_text_value(item: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(str(item.get(key) or "").strip() for key in keys)


def is_in_progress_puzzle_attempt(attempt: dict[str, Any]) -> bool:
    note = str(attempt.get("note") or "").strip().casefold()
    solved = str(attempt.get("solved") or "").strip()
    return note == "attempt in progress" and not solved


def clean_empty_generated_entries(extra: dict[str, Any]) -> bool:
    changed = False

    games = extra.get("games")
    if isinstance(games, list):
        cleaned_games = [
            game
            for game in games
            if isinstance(game, dict)
            and has_text_value(
                game,
                (
                    "game_url",
                    "lichess_game_url",
                    "game_id",
                    "platform",
                    "result",
                    "color",
                    "opening",
                    "opening_url",
                    "note",
                ),
            )
        ]
        if len(cleaned_games) != len(games):
            changed = True
        if cleaned_games:
            extra["games"] = cleaned_games
        elif "games" in extra:
            del extra["games"]

    attempts = extra.get("streak_attempts")
    if isinstance(attempts, list):
        cleaned_attempts = []
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            if is_in_progress_puzzle_attempt(attempt):
                continue
            puzzles = attempt.get("puzzles")
            if has_text_value(attempt, ("solved", "note")) or (isinstance(puzzles, list) and len(puzzles) > 0):
                cleaned_attempts.append(attempt)
        if len(cleaned_attempts) != len(attempts):
            changed = True
        if cleaned_attempts:
            extra["streak_attempts"] = cleaned_attempts
        elif "streak_attempts" in extra:
            del extra["streak_attempts"]

    return changed


def normalized_handle(name: str) -> str:
    return name.removeprefix("@").strip().lower()


def normalized_platform(platform: str) -> str:
    value = platform.strip().lower()
    if value in {"youtube", "twitch", "lichess", "chess.com", "discord"}:
        return value
    return ""


def is_self_supporter(platform: str, name: str) -> bool:
    handle = normalized_handle(name)
    return (normalized_platform(platform), handle) in SELF_SUPPORTERS or handle in SELF_HANDLES


def is_aggregator_platform(platform: str) -> bool:
    return platform.strip().lower() in AGGREGATOR_PLATFORMS


def supporter_url(platform: str, name: str) -> str:
    handle = name.removeprefix("@").strip()
    if not handle:
        return ""
    platform_key = normalized_platform(platform)
    if platform_key == "youtube":
        return f"https://www.youtube.com/@{quote(handle)}"
    if platform_key == "twitch":
        return f"https://www.twitch.tv/{quote(handle)}"
    return ""


def chat_supporters(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for message in messages:
        platform = str(message.get("platform") or "").strip()
        author = str(message.get("author") or "").strip()
        if (
            not platform
            or not author
            or author == "Host"
            or is_aggregator_platform(platform)
            or is_self_supporter(platform, author)
        ):
            continue
        key = (platform, author)
        by_key[key] = {"platform": platform, "name": author, "url": supporter_url(platform, author)}
    return sorted(by_key.values(), key=lambda item: (item["platform"], item["name"].casefold()))


def merge_session_supporters(data: dict[str, Any], supporters: list[dict[str, str]]) -> int:
    if not supporters:
        return 0
    extra = data.setdefault("extra", {})
    if not isinstance(extra, dict):
        fail("[extra] is not a table")

    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for item in extra.get("supporters") or []:
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform") or "").strip()
        name = str(item.get("name") or "").strip()
        if platform and name and not is_aggregator_platform(platform) and not is_self_supporter(platform, name):
            by_key[(platform, name)] = {key: str(value) for key, value in item.items() if value is not None}

    before = set(by_key)
    for supporter in supporters:
        by_key[(supporter["platform"], supporter["name"])] = supporter

    extra["supporters"] = sorted(by_key.values(), key=lambda item: (item["platform"], item["name"].casefold()))
    return len(set(by_key) - before)


def read_metadata() -> dict[str, Any]:
    path = DATA_DIR / "youtube_video_metadata.toml"
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}


def refresh_automatic_stat_sources(session: str, dry_run: bool) -> None:
    commands = [
        ["python3", "scripts/update_youtube_video_metadata.py", session],
        ["python3", "scripts/update_lichess_rating_history.py"],
    ]
    for command in commands:
        print(f"$ {' '.join(command)}")
        if dry_run:
            continue
        subprocess.run(command, check=False)


def format_duration_field(duration_seconds: int) -> str:
    minutes = max(0, duration_seconds) // 60
    hours, remainder = divmod(minutes, 60)
    if hours:
        return f"{hours}:{remainder:02d}"
    return str(remainder)


def rating_text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return str(round(float(value)))
    except (TypeError, ValueError):
        return None


def current_lichess_ratings(username: str = LICHESS_USERNAME, timeout: int = 20) -> dict[str, str]:
    url = f"https://lichess.org/api/user/{username}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "xadrez.live session wrap (https://xadrez.live)",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"Warning: could not fetch current Lichess ratings from {url}: {error}", file=sys.stderr)
        return {}

    perfs = payload.get("perfs") if isinstance(payload, dict) else {}
    if not isinstance(perfs, dict):
        return {}

    ratings = {}
    for key, perf_key in (("rapid", "rapid"), ("puzzles", "puzzle")):
        perf = perfs.get(perf_key)
        if not isinstance(perf, dict):
            continue
        value = rating_text(perf.get("rating"))
        if value:
            ratings[key] = value
    return ratings


def cached_lichess_ratings() -> dict[str, str]:
    path = DATA_DIR / "lichess_rating_history.toml"
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    ratings: dict[str, str] = {}
    for series in data.get("series") or []:
        if not isinstance(series, dict):
            continue
        key = str(series.get("key") or "")
        latest = series.get("latest_rating")
        if key in {"rapid", "puzzles"} and latest is not None:
            ratings[key] = str(latest)
    return ratings


def latest_lichess_ratings() -> dict[str, str]:
    ratings = current_lichess_ratings()
    if {"rapid", "puzzles"} <= set(ratings):
        return ratings

    cached = cached_lichess_ratings()
    missing = sorted({"rapid", "puzzles"} - set(ratings))
    if cached and missing:
        print(
            f"Warning: falling back to cached Lichess rating history for {', '.join(missing)}",
            file=sys.stderr,
        )
    return {**cached, **ratings}


def auto_fill_post_stats(session: str, data: dict[str, Any]) -> list[str]:
    extra = data.setdefault("extra", {})
    if not isinstance(extra, dict):
        fail("[extra] is not a table")

    updated = []
    metadata = read_metadata().get("sessions", {})
    session_metadata = metadata.get(session, {}) if isinstance(metadata, dict) else {}
    duration_seconds = session_metadata.get("duration_seconds") if isinstance(session_metadata, dict) else None
    if isinstance(duration_seconds, int) and duration_seconds > 0:
        value = format_duration_field(duration_seconds)
        if extra.get("duration") != value:
            extra["duration"] = value
            updated.append(f"duration={value}")

    ratings = latest_lichess_ratings()
    for key in ("rapid", "puzzles"):
        value = ratings.get(key)
        if value and extra.get(key) != value:
            extra[key] = value
            updated.append(f"{key}={value}")

    return updated


def session_start(data: dict[str, Any], session: str) -> datetime:
    metadata = read_metadata().get("sessions", {})
    if isinstance(metadata, dict):
        release_at = str(metadata.get(session, {}).get("release_at") or "")
        if release_at:
            return datetime.fromisoformat(release_at).astimezone(timezone.utc)

    raw_date = data.get("date")
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    raw_time = str(extra.get("time") or "00:00")
    if isinstance(raw_date, date):
        session_date = raw_date
    else:
        session_date = date.fromisoformat(str(raw_date))
    hour, minute = [int(part) for part in raw_time.split(":", 1)]
    return datetime.combine(session_date, time(hour, minute), tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def seconds_from_clock(clock: str, start: datetime) -> int:
    parts = [int(part) for part in clock.split(":")]
    if len(parts) != 3:
        fail(f"Restream clock must be HH:MM:SS, got {clock!r}")
    local = datetime.combine(start.astimezone(LOCAL_TZ).date(), time(parts[0], parts[1], parts[2]), tzinfo=LOCAL_TZ)
    if local.astimezone(timezone.utc) < start and parts[0] < 4:
        local = local + timedelta(days=1)
    return max(0, round((local.astimezone(timezone.utc) - start).total_seconds()))


def format_time(total_seconds: int) -> str:
    hours, remainder = divmod(max(0, total_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def normalize_chat(session: str, data: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    start = session_start(data, session)
    messages = []
    for item in raw.get("messages") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        author = str(item.get("author") or "").strip()
        if not text or not author:
            continue
        seconds = item.get("seconds")
        if seconds is None:
            seconds = seconds_from_clock(str(item.get("clock") or ""), start)
        else:
            seconds = max(0, int(round(float(seconds))))
        messages.append(
            {
                "time": format_time(seconds),
                "seconds": seconds,
                "platform": str(item.get("platform") or "").strip(),
                "channel": str(item.get("channel") or "").strip(),
                "author": author,
                "text": text,
            }
        )
    platforms = sorted({message["platform"] for message in messages if message["platform"]})
    return {
        "session_number": session,
        "youtube_video_id": str(extra.get("youtube_video_id") or ""),
        "source": str(raw.get("source") or "restream-userscript"),
        "page_url": str(raw.get("pageUrl") or ""),
        "exported_at": str(raw.get("exportedAt") or ""),
        "platforms": platforms,
        "message_count": len(messages),
        "messages": sorted(messages, key=lambda item: int(item["seconds"])),
    }


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def run(command: list[str], dry_run: bool) -> None:
    print(f"$ {' '.join(command)}")
    if dry_run:
        return
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        fail(f"command failed with exit code {error.returncode}: {' '.join(command)}")


def has_configured_lichess_video_offset(data: dict[str, Any]) -> bool:
    extra = data.get("extra")
    return isinstance(extra, dict) and "lichess_video_offset_seconds" in extra


def run_calibration(
    session: str,
    data: dict[str, Any],
    anchor: str,
    force: bool,
    skip: bool,
    dry_run: bool,
) -> bool:
    if skip:
        print(f"{session}: calibration skipped by --skip-calibration")
        return False
    if has_configured_lichess_video_offset(data) and not force:
        print(f"{session}: calibration skipped; lichess_video_offset_seconds already configured")
        return False
    if not sys.stdin.isatty() and not dry_run:
        print(f"{session}: calibration skipped; interactive terminal unavailable")
        return False

    command = [
        "python3",
        "scripts/calibrate_lichess_video_offset.py",
        session,
        "--anchor",
        anchor,
        "--exit-code-on-skip",
        "75",
    ]
    print(f"$ {' '.join(command)}")
    if dry_run:
        return False

    result = subprocess.run(command, check=False)
    if result.returncode == 75:
        print(f"{session}: calibration skipped; anchor data unavailable")
        return False
    if result.returncode != 0:
        fail(f"command failed with exit code {result.returncode}: {' '.join(command)}")
    return True


def has_gum() -> bool:
    return shutil.which("gum") is not None


def prompt(label: str, default: str = "") -> str:
    if has_gum():
        command = ["gum", "input", "--prompt", f"{label}: "]
        if default:
            command.extend(["--value", default])
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, check=False)
        if result.returncode != 0:
            return ""
        return result.stdout.strip() or default
    suffix = f" [{default}]" if default else ""
    return input(f"{label}{suffix}: ").strip() or default


def confirm(message: str) -> bool:
    if has_gum():
        return subprocess.run(["gum", "confirm", message], check=False).returncode == 0
    return prompt(f"{message} Digite SIM para confirmar", "") == "SIM"


def next_session_number(session: str) -> str:
    try:
        return f"{int(session) + 1:04d}"
    except ValueError:
        return ""


def has_scheduled_session(session: str) -> bool:
    if not session:
        return False
    path = CONTENT_DIR / f"{session}.md"
    if not path.exists():
        return False
    try:
        data = tomllib.loads(extract_front_matter(path.read_text(encoding="utf-8"), path)[0])
    except tomllib.TOMLDecodeError:
        return False
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return False
    tone = str(extra.get("status_tone") or "").strip().casefold()
    video_id = str(extra.get("youtube_video_id") or "").strip()
    return tone in {"scheduled", "live"} and bool(video_id) and video_id != "REPLACE_WITH_YOUTUBE_VIDEO_ID"


def schedule_next_session(args: argparse.Namespace, session: str, state: dict[str, Any]) -> tuple[list[str], str, str] | None:
    has_explicit_next = any([args.next_session, args.next_date, args.next_time, args.next_youtube])
    if args.skip_next_session:
        return None
    cached_next = state.get(NEXT_SESSION_CACHE_KEY)
    if not isinstance(cached_next, dict):
        cached_next = {}

    default_next_session = str(cached_next.get("session") or next_session_number(session))
    if not has_explicit_next and has_scheduled_session(default_next_session):
        print(f"{session}: next session {default_next_session} already scheduled; skipping next-session prompt")
        return None
    if not has_explicit_next and not sys.stdin.isatty():
        return None
    if not has_explicit_next and not confirm("Agendar a próxima sessão agora?"):
        return None

    default_next_date = str(cached_next.get("date") or (date.today() + timedelta(days=1)).isoformat())
    default_next_time = str(cached_next.get("time") or "08:30")
    default_next_youtube = str(cached_next.get("youtube") or "")

    next_session = args.next_session or prompt("Próxima sessão", default_next_session)
    next_date = args.next_date or prompt("Data da próxima live YYYY-MM-DD", default_next_date)
    next_time = args.next_time or prompt("Horário BRT HH:MM", default_next_time)
    next_youtube = args.next_youtube or prompt("YouTube URL ou ID", default_next_youtube)
    if not next_session or not next_date or not next_time or not next_youtube:
        fail("próxima sessão precisa de número, data, horário e YouTube URL/ID")

    state[NEXT_SESSION_CACHE_KEY] = {
        "session": next_session,
        "date": next_date,
        "time": next_time,
        "youtube": next_youtube,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    return (
        [
            "just",
            "schedule-next-session",
            next_session,
            "--date",
            next_date,
            "--time",
            next_time,
            "--youtube",
            next_youtube,
        ],
        next_session,
        next_time,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist and apply a daily xadrez.live wrapup from files.")
    parser.add_argument("session", help="Session number, e.g. 0054")
    parser.add_argument("--toml-file", type=Path, help="TOML fragment from the userscript; defaults to data/fcz/wrap_inbox/NNNN.toml when present")
    parser.add_argument("--chat-json-file", type=Path, help="Restream chat JSON from the userscript; defaults to data/fcz/wrap_inbox/NNNN-chat.json when present")
    parser.add_argument("--allow-missing-userscript-inputs", action="store_true", help="Allow wrapup to continue without both userscript exports")
    parser.add_argument("--dry-run", action="store_true", help="Persist raw inputs and print commands without applying changes")
    parser.add_argument("--yes", action="store_true", help="Skip the imported TOML confirmation checkpoint")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-capivaradas", action="store_true")
    parser.add_argument("--skip-calibration", action="store_true", help="Do not offer the Lichess video offset calibration checkpoint")
    parser.add_argument("--force-calibration", action="store_true", help="Run calibration even when lichess_video_offset_seconds is already configured")
    parser.add_argument(
        "--calibration-anchor",
        choices=("puzzle-of-the-day", "first-game"),
        default="puzzle-of-the-day",
        help="Anchor used by the wrapup calibration checkpoint",
    )
    parser.add_argument("--skip-youtube-finish", action="store_true")
    parser.add_argument("--skip-youtube-title", action="store_true")
    parser.add_argument("--skip-next-session", action="store_true", help="Do not offer to create/update the next scheduled session")
    parser.add_argument("--skip-next-pre-thumb", action="store_true", help="Do not generate/upload the next session pre-live thumbnail")
    parser.add_argument("--skip-next-youtube-latency", action="store_true", help="Do not set the next YouTube live to ultra-low latency")
    parser.add_argument("--next-session", help="Next session number, e.g. 0056")
    parser.add_argument("--next-date", help="Next session date in YYYY-MM-DD")
    parser.add_argument("--next-time", help="Next session local time in HH:MM")
    parser.add_argument("--next-youtube", help="Next YouTube video id or URL")
    parser.add_argument("--downloads-max-age-hours", type=float, default=12.0, help="Maximum age for implicit ~/Downloads fallback inputs")
    return parser.parse_args()


def existing_input(candidates: list[Path]) -> Path | None:
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def fresh_download_input(path: Path, max_age_hours: float) -> Path | None:
    if not path.exists():
        return None
    age_seconds = time_module.time() - path.stat().st_mtime
    if age_seconds <= max_age_hours * 3600:
        return path
    print(f"warning: ignoring stale Downloads input older than {max_age_hours:g}h: {path}")
    return None


def require_userscript_inputs(session: str, toml_file: Path | None, chat_json_file: Path | None) -> None:
    missing = []
    if toml_file is None:
        missing.append(
            "TOML do wrap: "
            f"{INBOX_DIR / f'{session}.toml'} ou {DOWNLOADS_DIR / f'{session}.toml'}"
        )
    if chat_json_file is None:
        missing.append(
            "chat Restream JSON: "
            f"{INBOX_DIR / f'{session}-chat.json'} ou {DOWNLOADS_DIR / f'{session}-chat.json'}"
        )
    if not missing:
        return
    fail(
        "faltam export(s) do userscript antes do wrapup:\n"
        + "\n".join(f"- {item}" for item in missing)
        + "\n\nSalve os dois arquivos em Downloads/inbox ou passe --toml-file/--chat-json-file. "
        "Use --allow-missing-userscript-inputs só para sessões fora da rotina."
    )


def main() -> int:
    args = parse_args()
    session = args.session.zfill(4)
    toml_file = (
        args.toml_file
        or existing_input([INBOX_DIR / f"{session}.toml"])
        or fresh_download_input(DOWNLOADS_DIR / f"{session}.toml", args.downloads_max_age_hours)
    )
    chat_json_file = (
        args.chat_json_file
        or existing_input([INBOX_DIR / f"{session}-chat.json"])
        or fresh_download_input(DOWNLOADS_DIR / f"{session}-chat.json", args.downloads_max_age_hours)
    )
    if not args.allow_missing_userscript_inputs:
        require_userscript_inputs(session, toml_file, chat_json_file)
    path, data, body = read_session(session)
    previous_state = load_json(WRAP_DIR / f"{session}.json")
    state: dict[str, Any] = {
        "session": session,
        "pid": os.getpid(),
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {},
    }
    cached_next = previous_state.get(NEXT_SESSION_CACHE_KEY)
    if isinstance(cached_next, dict):
        state[NEXT_SESSION_CACHE_KEY] = cached_next

    try:
        if toml_file:
            raw_toml = toml_file.read_text(encoding="utf-8")
            wrap_toml = load_wrap_toml(toml_file)
            confirm_wrap_toml(session, wrap_toml, toml_file, args.yes)
            state["inputs"]["toml_file"] = str(toml_file)
            state["inputs"]["toml"] = raw_toml
            data = apply_wrap_toml(session, data, wrap_toml)
            if not args.dry_run:
                write_session(path, data, body)
            action = "would apply" if args.dry_run else "applied"
            print(f"{session}: {action} TOML to {path}")
        else:
            print(f"{session}: no TOML input found")

        if chat_json_file:
            raw_chat_text = chat_json_file.read_text(encoding="utf-8")
            raw_chat = json.loads(raw_chat_text)
            state["inputs"]["chat_json_file"] = str(chat_json_file)
            state["inputs"]["chat_json"] = raw_chat
            replay = normalize_chat(session, data, raw_chat)
            added_supporters = merge_session_supporters(data, chat_supporters(replay["messages"]))
            extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
            cleaned_entries = clean_empty_generated_entries(extra)
            if not args.dry_run:
                save_json(RESTREAM_DIR / f"{session}.json", replay)
                if added_supporters or cleaned_entries:
                    write_session(path, data, body)
            print(f"{session}: imported {replay['message_count']} Restream chat message(s)")
            print(f"{session}: added {added_supporters} supporter(s) from chat")
        else:
            print(f"{session}: no Restream chat input found")

        if not args.dry_run:
            save_json(WRAP_DIR / f"{session}.json", state)
            refresh_automatic_stat_sources(session, args.dry_run)
            updated_stats = auto_fill_post_stats(session, data)
            extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
            cleaned_entries = clean_empty_generated_entries(extra)
            if updated_stats:
                write_session(path, data, body)
                print(f"{session}: auto-filled post stats ({', '.join(updated_stats)})")
            elif cleaned_entries:
                write_session(path, data, body)
                print(f"{session}: removed empty generated entries")
            if chat_json_file:
                run(["python3", "scripts/merge_chat_replays.py", session], args.dry_run)
            calibrated = run_calibration(
                session,
                data,
                args.calibration_anchor,
                args.force_calibration,
                args.skip_calibration,
                args.dry_run,
            )
            if calibrated:
                path, data, body = read_session(session)
            if not args.skip_capivaradas:
                run(["just", "update-session-capivaradas-data", session], args.dry_run)
            if not args.skip_youtube_finish:
                recipe = "youtube-finish-session-skip-title-no-build" if args.skip_youtube_title else "youtube-finish-session-no-build"
                run(["just", recipe, session], args.dry_run)
                editorial_updates = apply_selected_editorial_choices(session, data)
                if editorial_updates:
                    write_session(path, data, body)
                    print(f"{session}: applied selected editorial choices to page ({', '.join(editorial_updates)})")
            else:
                run(["just", "verify-session", session], args.dry_run)
            next_session_command = schedule_next_session(args, session, state)
            if next_session_command:
                command, next_session, next_time = next_session_command
                save_json(WRAP_DIR / f"{session}.json", state)
                run(command, args.dry_run)
                if not args.skip_next_youtube_latency:
                    run(["just", "youtube-live-latency", next_session], args.dry_run)
                if not args.skip_next_pre_thumb:
                    run(["just", "pre-thumb", next_session, next_time], args.dry_run)
            if not args.skip_build:
                run(["just", "build"], args.dry_run)
            state["status"] = "completed"
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            state["updated_at"] = state["completed_at"]
            save_json(WRAP_DIR / f"{session}.json", state)
        else:
            print(f"{session}: dry run; no files written")
    except KeyboardInterrupt:
        if not args.dry_run:
            state["status"] = "interrupted"
            state["interrupted_at"] = datetime.now(timezone.utc).isoformat()
            state["updated_at"] = state["interrupted_at"]
            save_json(WRAP_DIR / f"{session}.json", state)
        print(f"\n{session}: wrapup interrupted; rerun wrap-session to continue")
        raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
