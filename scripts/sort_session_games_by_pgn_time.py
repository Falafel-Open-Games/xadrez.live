#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

import wrap_session


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
ANALYSIS_PATH = ROOT / "data" / "fcz" / "lichess_game_analysis.toml"
LICHESS_URL_RE = re.compile(r"^https://lichess\.org/(?P<id>[A-Za-z0-9]{8,12})(?:/(?:white|black))?$")
PGN_TAG_RE = re.compile(r'^\[(?P<name>[A-Za-z0-9_]+)\s+"(?P<value>.*)"\]$')


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def extract_front_matter(text: str, path: Path) -> tuple[str, str]:
    if not text.startswith("+++\n"):
        fail(f"missing TOML front matter in {path}")
    end = text.find("\n+++", 4)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")
    return text[4:end], text[end + 4 :]


def game_id_from_game(game: dict[str, Any]) -> str:
    game_id = str(game.get("game_id") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9]{8}", game_id):
        return game_id
    url = str(game.get("game_url") or game.get("lichess_game_url") or "").strip()
    match = LICHESS_URL_RE.fullmatch(url)
    return match.group("id")[:8] if match else ""


def pgn_tags(pgn: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for line in pgn.splitlines():
        match = PGN_TAG_RE.match(line.strip())
        if not match:
            if tags:
                break
            continue
        tags[match.group("name")] = match.group("value")
    return tags


def pgn_started_at(pgn: str) -> datetime | None:
    tags = pgn_tags(pgn)
    raw_date = tags.get("UTCDate") or tags.get("Date") or ""
    raw_time = tags.get("UTCTime") or ""
    if not raw_date or not raw_time or raw_date == "????.??.??":
        return None
    try:
        return datetime.strptime(f"{raw_date} {raw_time}", "%Y.%m.%d %H:%M:%S")
    except ValueError:
        return None


def load_game_times() -> dict[str, datetime]:
    if not ANALYSIS_PATH.exists():
        fail(f"{ANALYSIS_PATH} does not exist; run update_lichess_game_analysis.py first")
    data = tomllib.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    times: dict[str, datetime] = {}
    for game in data.get("games", []):
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("game_id") or "").strip()
        pgn = str(game.get("pgn") or "")
        started_at = pgn_started_at(pgn)
        if game_id and started_at:
            times[game_id] = started_at
    return times


def sort_session(session: str, game_times: dict[str, datetime], dry_run: bool) -> bool:
    path = CONTENT_DIR / f"{session}.md"
    if not path.exists():
        fail(f"{path} does not exist")

    text = path.read_text(encoding="utf-8")
    front_matter, body = extract_front_matter(text, path)
    data = tomllib.loads(front_matter)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return False
    games = extra.get("games")
    if not isinstance(games, list) or len(games) < 2:
        return False

    indexed_games = list(enumerate(games))

    def sort_key(item: tuple[int, Any]) -> tuple[int, datetime | None, int]:
        original_index, game = item
        if not isinstance(game, dict):
            return (1, None, original_index)
        game_id = game_id_from_game(game)
        started_at = game_times.get(game_id)
        if started_at is None:
            return (1, None, original_index)
        return (0, started_at, original_index)

    sorted_games = [game for _, game in sorted(indexed_games, key=sort_key)]
    if sorted_games == games:
        print(f"{session}: games already sorted by PGN time")
        return False

    before = [game_id_from_game(game) for game in games if isinstance(game, dict)]
    after = [game_id_from_game(game) for game in sorted_games if isinstance(game, dict)]
    print(f"{session}: reordered games by PGN time")
    print(f"  before: {', '.join(before)}")
    print(f"  after:  {', '.join(after)}")

    if dry_run:
        return True

    extra["games"] = sorted_games
    path.write_text(wrap_session.render_front_matter(data) + body, encoding="utf-8")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sort session extra.games by UTCDate/UTCTime from cached Lichess PGNs.")
    parser.add_argument("sessions", nargs="+", help="Session numbers, e.g. 0070")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    game_times = load_game_times()
    changed = 0
    for session in args.sessions:
        if sort_session(session.zfill(4), game_times, args.dry_run):
            changed += 1
    return 0 if changed >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
