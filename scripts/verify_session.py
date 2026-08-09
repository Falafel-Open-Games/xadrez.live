#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DATA_DIR = ROOT / "data" / "fcz"


@dataclass
class Check:
    level: str
    message: str


def extract_front_matter(text: str, path: Path) -> str:
    if not text.startswith("+++"):
        raise ValueError(f"missing TOML front matter in {path}")
    end = text.find("\n+++", 3)
    if end == -1:
        raise ValueError(f"malformed front matter in {path}: missing closing +++")
    return text[3:end].strip()


def read_session(session: str) -> dict[str, Any]:
    path = CONTENT_DIR / f"{session}.md"
    if not path.exists():
        raise FileNotFoundError(path)
    return tomllib.loads(extract_front_matter(path.read_text(encoding="utf-8"), path))


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_ended(extra: dict[str, Any]) -> bool:
    status = str(extra.get("status") or "").strip().lower()
    tone = str(extra.get("status_tone") or "").strip().lower()
    return status == "encerrada" or tone in {"ended", "completed"}


def has_youtube_supporter(extra: dict[str, Any]) -> bool:
    supporters = extra.get("supporters")
    if not isinstance(supporters, list):
        return False
    return any(str(supporter.get("platform") or "").strip().lower() == "youtube" for supporter in supporters if isinstance(supporter, dict))


def has_practice(extra: dict[str, Any]) -> bool:
    practice_sets = extra.get("practice_sets")
    streak_attempts = extra.get("streak_attempts")
    if isinstance(practice_sets, list):
        for practice_set in practice_sets:
            if isinstance(practice_set, dict) and (practice_set.get("url") or practice_set.get("title")):
                return True
    if isinstance(streak_attempts, list):
        for attempt in streak_attempts:
            if not isinstance(attempt, dict):
                continue
            puzzles = attempt.get("puzzles")
            if attempt.get("solved") or attempt.get("note") or (isinstance(puzzles, list) and puzzles):
                return True
    return False


def storm_timestamp_kinds(extra: dict[str, Any]) -> set[str]:
    attempts = extra.get("storm_attempts")
    if not isinstance(attempts, list):
        return set()
    kinds = set()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        if attempt.get("started_at"):
            kinds.add("storm_start")
    return kinds


def has_games(extra: dict[str, Any]) -> bool:
    games = extra.get("games")
    if not isinstance(games, list):
        return False
    return any(isinstance(game, dict) and (game.get("game_url") or game.get("lichess_game_url") or game.get("game_id")) for game in games)


def invalid_lichess_game_ids(extra: dict[str, Any]) -> list[str]:
    games = extra.get("games")
    if not isinstance(games, list):
        return []
    invalid = []
    for index, game in enumerate(games, start=1):
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("game_id") or "").strip()
        platform = str(game.get("platform") or "").strip().lower()
        if game_id and platform == "lichess" and not re.fullmatch(r"[A-Za-z0-9]{8}", game_id):
            invalid.append(f"partida {index}: {game_id}")
    return invalid


def timeline_kinds(session: str) -> set[str]:
    data = read_json(DATA_DIR / "lichess_blunders" / f"{session}.json")
    if not data:
        return set()
    timeline = data.get("timeline")
    if not isinstance(timeline, list):
        return set()
    return {str(event.get("kind") or "") for event in timeline if isinstance(event, dict)}


def chat_platforms(session: str) -> set[str]:
    data = read_json(DATA_DIR / "chat_replays" / f"{session}.json")
    if not data:
        return set()
    messages = data.get("messages")
    if not isinstance(messages, list):
        return set()
    return {str(message.get("platform") or "").strip() for message in messages if isinstance(message, dict) and message.get("platform")}


def anonymous_chat_author_count(session: str) -> int:
    data = read_json(DATA_DIR / "chat_replays" / f"{session}.json")
    if not data:
        return 0
    messages = data.get("messages")
    if not isinstance(messages, list):
        return 0
    return sum(
        1
        for message in messages
        if isinstance(message, dict)
        and re.fullmatch(r"Person \d+", str(message.get("author") or "").strip())
    )


def wrap_input_has_known_chat_authors(session: str) -> bool:
    data = read_json(DATA_DIR / "wrap_sessions" / f"{session}.json")
    if not data:
        return False
    inputs = data.get("inputs")
    if not isinstance(inputs, dict):
        return False
    chat_json = inputs.get("chat_json")
    if not isinstance(chat_json, dict):
        return False
    messages = chat_json.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict):
            continue
        author = str(message.get("author") or "").strip()
        if author and not re.fullmatch(r"Person \d+", author):
            return True
    return False


def thumbnail_path(extra: dict[str, Any]) -> Path | None:
    raw = str(extra.get("og_image") or "").strip()
    if not raw:
        return None
    if raw.startswith("/"):
        return ROOT / "static" / raw.removeprefix("/")
    return ROOT / raw


def verify(session: str, require_published_thumbnail: bool) -> list[Check]:
    data = read_session(session)
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    checks: list[Check] = []

    if extra.get("youtube_video_id"):
        checks.append(Check("ok", "YouTube video id preenchido"))
    else:
        checks.append(Check("error", "YouTube video id ausente"))

    ended = is_ended(extra)
    if ended:
        missing_stats = [field for field in ("duration", "rapid", "puzzles") if not str(extra.get(field) or "").strip()]
        if missing_stats:
            checks.append(Check("error", f"Stats pós-live ausentes: {', '.join(missing_stats)}"))
        else:
            checks.append(Check("ok", "Stats pós-live preenchidos"))

    if extra.get("puzzle_of_the_day_url") and not extra.get("puzzle_of_the_day_recorded_at"):
        checks.append(Check("error", "Puzzle do dia tem URL, mas não tem puzzle_of_the_day_recorded_at"))
    elif extra.get("puzzle_of_the_day_recorded_at"):
        checks.append(Check("ok", "Puzzle do dia tem timestamp"))

    practice_expected = ended and has_practice(extra)
    if practice_expected and not extra.get("practice_notes_recorded_at"):
        checks.append(Check("error", "Há prática/streak registrados, mas falta practice_notes_recorded_at"))
    elif extra.get("practice_notes_recorded_at"):
        checks.append(Check("ok", "Prática tem timestamp"))

    kinds = timeline_kinds(session)
    if extra.get("puzzle_of_the_day_recorded_at") and "puzzle_of_the_day" not in kinds:
        checks.append(Check("error", "Timeline não contém evento Puzzle do dia"))
    if extra.get("practice_notes_recorded_at") and "practice_end" not in kinds:
        checks.append(Check("error", "Timeline não contém evento Fim da prática"))
    expected_storm_kinds = storm_timestamp_kinds(extra)
    if "storm_start" in expected_storm_kinds and "storm_start" not in kinds:
        checks.append(Check("error", "Timeline não contém início de Puzzle Storm"))
    if ended and has_games(extra) and "game_start" not in kinds:
        checks.append(Check("error", "Há jogos registrados, mas a timeline não contém Partida"))
    invalid_ids = invalid_lichess_game_ids(extra)
    if invalid_ids:
        checks.append(Check("error", f"game_id Lichess inválido: {', '.join(invalid_ids)}"))
    if kinds:
        checks.append(Check("ok", f"Timeline encontrada com {len(kinds)} tipo(s) de evento"))

    platforms = chat_platforms(session)
    if ended and has_youtube_supporter(extra) and "YouTube" not in platforms:
        checks.append(Check("error", "Há supporter do YouTube, mas o chat final não contém mensagens do YouTube"))
    elif platforms:
        checks.append(Check("ok", f"Chat final contém: {', '.join(sorted(platforms))}"))
    anonymous_authors = anonymous_chat_author_count(session)
    if anonymous_authors:
        level = "error" if wrap_input_has_known_chat_authors(session) else "warning"
        checks.append(Check(level, f"Chat final contém {anonymous_authors} autor(es) anonimizado(s) como Person N"))

    thumb = thumbnail_path(extra)
    published = read_toml(DATA_DIR / "youtube_published_assets.toml").get("thumbnails", {})
    published_session = published.get(session, {}) if isinstance(published, dict) else {}
    if thumb is None:
        checks.append(Check("warning", "og_image ausente"))
    elif not thumb.exists():
        checks.append(Check("error", f"Thumbnail local não encontrado: {thumb.relative_to(ROOT)}"))
    else:
        current_hash = sha256(thumb)
        published_hash = str(published_session.get("sha256") or "")
        if published_hash == current_hash:
            checks.append(Check("ok", "Thumbnail local corresponde ao último upload registrado"))
        elif require_published_thumbnail:
            checks.append(Check("error", "Thumbnail local mudou ou ainda não foi publicado no YouTube"))
        else:
            checks.append(Check("warning", "Thumbnail local mudou ou ainda não foi publicado no YouTube"))

    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the daily wrap data for one xadrez.live session.")
    parser.add_argument("session", help="Session number, e.g. 0054")
    parser.add_argument("--require-published-thumbnail", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks = verify(args.session, args.require_published_thumbnail)
    errors = [check for check in checks if check.level == "error"]
    warnings = [check for check in checks if check.level == "warning"]
    print(f"{args.session}: session verification")
    for check in checks:
        label = {"ok": "ok", "warning": "warning", "error": "error"}[check.level]
        print(f"- {label}: {check.message}")
    print(f"summary: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
