#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
OUTPUT = ROOT / "data" / "fcz" / "lichess_game_analysis.toml"
ENV_PATH = ROOT / ".env"
LICHESS_URL_RE = re.compile(r"^https://lichess\.org/(?P<id>[A-Za-z0-9]{8,12})(?:/(?P<color>white|black))?$")


@dataclass(frozen=True)
class SessionGame:
    session_number: str
    game_index: int
    game_id: str
    url: str
    color: str


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


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


def normalize_color(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"white", "black"}:
        return text
    return ""


def lichess_game_from_url(url: Any, fallback_color: Any = "") -> tuple[str, str] | None:
    match = LICHESS_URL_RE.fullmatch(str(url or "").strip())
    if not match:
        return None
    color = match.group("color") or normalize_color(fallback_color)
    return match.group("id")[:8], color


def explicit_lichess_game(game: dict[str, Any]) -> tuple[str, str, str] | None:
    game_id = str(game.get("game_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{8}", game_id):
        return None
    color = normalize_color(game.get("color"))
    url = str(game.get("game_url") or game.get("lichess_game_url") or "").strip()
    if not url:
        url = f"https://lichess.org/{game_id}{('/' + color) if color else ''}"
    return game_id, color, url


def session_games(path: Path) -> list[SessionGame]:
    data = front_matter(path)
    if data.get("draft") is True:
        return []
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return []
    if str(extra.get("status_tone") or "").strip().casefold() in {"scheduled", "live"}:
        return []

    session_number = str(extra.get("session_number") or path.stem)
    rows: list[SessionGame] = []
    games = extra.get("games")
    if isinstance(games, list) and games:
        for index, game in enumerate(games, start=1):
            if not isinstance(game, dict):
                continue
            explicit = explicit_lichess_game(game)
            if explicit:
                game_id, color, url = explicit
                rows.append(SessionGame(session_number, index, game_id, url, color))
                continue
            url = str(game.get("game_url") or game.get("lichess_game_url") or "").strip()
            parsed = lichess_game_from_url(url, game.get("color"))
            if parsed:
                game_id, color = parsed
                rows.append(SessionGame(session_number, index, game_id, url, color))
        return rows

    url = str(extra.get("lichess_game_url") or "").strip()
    parsed = lichess_game_from_url(url, extra.get("color"))
    if parsed:
        game_id, color = parsed
        rows.append(SessionGame(session_number, 1, game_id, url, color))
    return rows


def load_all_session_games() -> list[SessionGame]:
    games = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        games.extend(session_games(path))
    return games


def selected_games(games: list[SessionGame], sessions: set[str]) -> list[SessionGame]:
    if not sessions:
        return games
    return [game for game in games if game.session_number in sessions]


def fetch_game(game_id: str, token: str, timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "accuracy": 1,
            "evals": 1,
            "opening": 1,
            "division": 1,
        }
    )
    request = urllib.request.Request(
        f"https://lichess.org/game/export/{game_id}?{query}",
        headers={
            "Accept": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def player_analysis(payload: dict[str, Any], color: str) -> dict[str, Any] | None:
    players = payload.get("players")
    if not isinstance(players, dict):
        return None
    player = players.get(color)
    if not isinstance(player, dict):
        return None
    analysis = player.get("analysis")
    return analysis if isinstance(analysis, dict) else None


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return None


def export_rows(rows: list[dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    analysed = [row for row in rows if row["has_analysis"]]
    missing = [row for row in rows if not row["has_analysis"]]
    total_blunders = sum(row["blunder"] for row in analysed)
    total_mistakes = sum(row["mistake"] for row in analysed)
    total_inaccuracies = sum(row["inaccuracy"] for row in analysed)
    total_accuracy = sum(row["accuracy"] for row in analysed)
    total_acpl = sum(row["acpl"] for row in analysed)

    lines = [
        "# Generated by scripts/update_lichess_game_analysis.py; do not edit manually.",
        "",
        "[summary]",
        f"updated_at = {toml_string(now)}",
        f"game_count = {len(rows)}",
        f"analysed_count = {len(analysed)}",
        f"missing_count = {len(missing)}",
        f"total_blunders = {total_blunders}",
        f"total_mistakes = {total_mistakes}",
        f"total_inaccuracies = {total_inaccuracies}",
        f"average_blunders = {(total_blunders / len(analysed)) if analysed else 0:.2f}",
        f"average_mistakes = {(total_mistakes / len(analysed)) if analysed else 0:.2f}",
        f"average_inaccuracies = {(total_inaccuracies / len(analysed)) if analysed else 0:.2f}",
        f"average_accuracy = {(total_accuracy / len(analysed)) if analysed else 0:.2f}",
        f"average_acpl = {(total_acpl / len(analysed)) if analysed else 0:.2f}",
        "",
    ]

    for row in rows:
        lines.extend(
            [
                "[[games]]",
                f"session_number = {toml_string(row['session_number'])}",
                f"game_index = {row['game_index']}",
                f"game_id = {toml_string(row['game_id'])}",
                f"url = {toml_string(row['url'])}",
                f"color = {toml_string(row['color'])}",
                f"has_analysis = {toml_bool(row['has_analysis'])}",
                f"inaccuracy = {row['inaccuracy']}",
                f"mistake = {row['mistake']}",
                f"blunder = {row['blunder']}",
                f"acpl = {row['acpl']}",
                f"accuracy = {row['accuracy']}",
                f"opening_accuracy = {row['opening_accuracy']}",
                f"middlegame_accuracy = {row['middlegame_accuracy']}",
                f"endgame_accuracy = {row['endgame_accuracy']}",
                "",
            ]
        )

    for row in missing:
        lines.extend(
            [
                "[[missing]]",
                f"session_number = {toml_string(row['session_number'])}",
                f"game_index = {row['game_index']}",
                f"game_id = {toml_string(row['game_id'])}",
                f"url = {toml_string(row['url'])}",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def build_row(game: SessionGame, payload: dict[str, Any] | None) -> dict[str, Any]:
    analysis = player_analysis(payload or {}, game.color) if game.color else None
    phases = analysis.get("phases") if isinstance(analysis, dict) else None
    if not isinstance(phases, dict):
        phases = {}
    return {
        "session_number": game.session_number,
        "game_index": game.game_index,
        "game_id": game.game_id,
        "url": game.url,
        "color": game.color,
        "has_analysis": bool(analysis),
        "inaccuracy": int_or_none((analysis or {}).get("inaccuracy")) or 0,
        "mistake": int_or_none((analysis or {}).get("mistake")) or 0,
        "blunder": int_or_none((analysis or {}).get("blunder")) or 0,
        "acpl": int_or_none((analysis or {}).get("acpl")) or 0,
        "accuracy": int_or_none((analysis or {}).get("accuracy")) or 0,
        "opening_accuracy": int_or_none(phases.get("opening")) or 0,
        "middlegame_accuracy": int_or_none(phases.get("middlegame")) or 0,
        "endgame_accuracy": int_or_none(phases.get("endgame")) or 0,
    }


def existing_rows_by_key(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    rows = data.get("games")
    if not isinstance(rows, list):
        return {}
    existing: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        session_number = str(row.get("session_number") or "")
        game_index = int_or_none(row.get("game_index"))
        if session_number and game_index is not None:
            existing[(session_number, game_index)] = row
    return existing


def semantic_cache(data: dict[str, Any]) -> dict[str, Any]:
    summary = dict(data.get("summary") or {})
    summary.pop("updated_at", None)
    return {
        **data,
        "summary": summary,
    }


def write_cache_if_changed(path: Path, content: str) -> bool:
    if path.exists():
        try:
            existing = tomllib.loads(path.read_text(encoding="utf-8"))
            incoming = tomllib.loads(content)
        except tomllib.TOMLDecodeError:
            existing = {}
            incoming = {}
        if existing and incoming and semantic_cache(existing) == semantic_cache(incoming):
            return False
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Fetch cached Lichess computer analysis for registered session games.")
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0052.")
    parser.add_argument("--token", default=os.environ.get("LICHESS_TOKEN", ""))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--missing-only", action="store_true", help="Only print games without saved analysis after fetching.")
    parser.add_argument("--no-write", action="store_true", help="Fetch and report without writing the TOML cache.")
    args = parser.parse_args()

    games = load_all_session_games()
    selected_numbers = set(args.sessions)
    games_to_fetch = selected_games(games, selected_numbers)
    existing_rows = existing_rows_by_key(OUTPUT) if selected_numbers else {}
    rows = []
    failures = []
    fetch_keys = {(game.session_number, game.game_index) for game in games_to_fetch}
    if selected_numbers:
        print(f"Fetching Lichess analysis for {len(games_to_fetch)} game(s): {', '.join(sorted(selected_numbers))}")

    fetched = 0
    for game in games:
        key = (game.session_number, game.game_index)
        if key not in fetch_keys:
            existing = existing_rows.get(key)
            rows.append(dict(existing) if existing else build_row(game, None))
            continue

        fetched += 1
        print(f"{game.session_number} partida {game.game_index}: fetching {game.url}")
        try:
            payload = fetch_game(game.game_id, args.token, args.timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            payload = None
            failures.append(f"{game.session_number} #{game.game_index} {game.url}: {error}")
        if payload is None and key in existing_rows:
            rows.append(dict(existing_rows[key]))
        else:
            rows.append(build_row(game, payload))
        if fetched < len(games_to_fetch) and args.sleep > 0:
            time.sleep(args.sleep)

    missing = [row for row in rows if not row["has_analysis"]]
    if not args.no_write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        if write_cache_if_changed(OUTPUT, export_rows(rows)):
            print(f"Updated {OUTPUT.relative_to(ROOT)}")
        else:
            print(f"Unchanged {OUTPUT.relative_to(ROOT)}")

    if args.missing_only:
        if missing:
            print("Games missing Lichess analysis:")
            for row in missing:
                print(f"- #{row['session_number']} partida {row['game_index']}: {row['url']}")
        else:
            print("All registered Lichess games have analysis.")
    else:
        print(f"Analysed {len(rows) - len(missing)}/{len(rows)} registered Lichess games.")
        if missing:
            print(f"Missing analysis: {len(missing)}")
    if failures:
        print("Fetch failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
