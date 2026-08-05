#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DEFAULT_USERNAME = "fcz"
DEFAULT_TZ = "America/Sao_Paulo"
RESULT_TOKENS = {
    "win": ("win", "vitória", "vitoria", "ganhei"),
    "loss": ("loss", "lost", "perdi", "derrota", "timeout", "fail", "resign"),
    "draw": ("draw", "empate"),
}


@dataclass
class Session:
    number: str
    date: str
    time: str
    result: str
    color: str
    opening: str
    description: str


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_result(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    for key, tokens in RESULT_TOKENS.items():
        if any(token in text for token in tokens):
            return key
    return "other"


def normalize_color(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"white", "brancas", "branco"}:
        return "white"
    if text in {"black", "pretas", "preto"}:
        return "black"
    return ""


def front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return {}
    end = text.find("\n+++", 4)
    if end == -1:
        return {}
    return tomllib.loads(text[4:end])


def load_session(number: str) -> Session:
    path = CONTENT_DIR / f"{number}.md"
    if not path.exists():
        fail(f"session not found: {path}")
    data = front_matter(path)
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    return Session(
        number=number,
        date=str(data.get("date") or ""),
        time=str(extra.get("time") or "00:00"),
        result=str(extra.get("result") or ""),
        color=str(extra.get("color") or ""),
        opening=str(extra.get("opening") or ""),
        description=str(extra.get("description") or ""),
    )


def expand_sessions(values: list[str]) -> list[str]:
    numbers: list[str] = []
    for value in values:
        if "-" in value:
            start, end = value.split("-", 1)
            numbers.extend(f"{number:04d}" for number in range(int(start), int(end) + 1))
        else:
            numbers.append(f"{int(value):04d}")
    return numbers


def session_window(session: Session, tz_name: str, whole_day: bool) -> tuple[int, int]:
    tz = ZoneInfo(tz_name)
    day = datetime.fromisoformat(session.date).replace(tzinfo=tz)
    if whole_day:
        start = day
        end = day + timedelta(days=1)
    else:
        hour, minute = [int(part) for part in session.time.split(":", 1)]
        start = day.replace(hour=hour, minute=minute) - timedelta(minutes=30)
        end = start + timedelta(hours=4)
    return (
        int(start.astimezone(timezone.utc).timestamp() * 1000),
        int(end.astimezone(timezone.utc).timestamp() * 1000),
    )


def fetch_games(username: str, token: str, since_ms: int, until_ms: int, timeout: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "since": since_ms,
            "until": until_ms,
            "perfType": "rapid",
            "opening": "true",
            "clocks": "true",
            "pgnInJson": "true",
            "evals": "false",
            "literate": "false",
        }
    )
    url = f"https://lichess.org/api/games/user/{urllib.parse.quote(username)}?{query}"
    headers = {
        "Accept": "application/x-ndjson",
        "User-Agent": "xadrez.live session backfill (https://xadrez.live)",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        fail(f"Lichess export failed with HTTP {error.code}: {detail.strip()}")
    except URLError as error:
        fail(f"Lichess export failed: {error.reason}")
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def player_color(game: dict[str, Any], username: str) -> str:
    needle = username.casefold()
    for color in ("white", "black"):
        user = game.get("players", {}).get(color, {}).get("user", {})
        if str(user.get("name") or user.get("id") or "").casefold() == needle:
            return color
    return ""


def game_result(game: dict[str, Any], color: str) -> str:
    winner = game.get("winner")
    if winner == color:
        return "win"
    if winner in {"white", "black"}:
        return "loss"
    status = str(game.get("status") or "").casefold()
    if status in {"draw", "stalemate"}:
        return "draw"
    return ""


def opponent_rating(game: dict[str, Any], color: str) -> int | None:
    opponent = "black" if color == "white" else "white"
    rating = game.get("players", {}).get(opponent, {}).get("rating")
    return rating if isinstance(rating, int) else None


def rating_hints(session: Session) -> set[int]:
    text = f"{session.result} {session.description}"
    return {int(match) for match in re.findall(r"\b[1-9][0-9]{2,3}\b", text)}


def score_game(session: Session, game: dict[str, Any], username: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    color = player_color(game, username)
    expected_color = normalize_color(session.color)
    if expected_color and color == expected_color:
        score += 4
        reasons.append(f"cor {color}")
    expected_result = normalize_result(session.result)
    actual_result = game_result(game, color)
    if expected_result and actual_result == expected_result:
        score += 5
        reasons.append(f"resultado {actual_result}")
    opening = str(game.get("opening", {}).get("name") or "")
    if session.opening and session.opening.casefold() in opening.casefold():
        score += 3
        reasons.append("abertura")
    rating = opponent_rating(game, color)
    hints = rating_hints(session)
    if rating and hints and any(abs(rating - hint) <= 25 for hint in hints):
        score += 3
        reasons.append(f"rating adversario {rating}")
    return score, reasons


def game_summary(session: Session, game: dict[str, Any], username: str) -> str:
    color = player_color(game, username)
    result = game_result(game, color)
    created = datetime.fromtimestamp(game.get("createdAt", 0) / 1000, tz=timezone.utc)
    local = created.astimezone(ZoneInfo(DEFAULT_TZ)).strftime("%Y-%m-%d %H:%M")
    rating = opponent_rating(game, color)
    opening = game.get("opening", {}).get("name") or ""
    url = f"https://lichess.org/{game.get('id')}/{color}" if color else f"https://lichess.org/{game.get('id')}"
    return (
        f"{session.number}: {url} | {local} BRT | {color or '?'} | {result or '?'}"
        f" | opp {rating or '?'} | {opening}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Find Lichess game URL candidates for old xadrez.live sessions.")
    parser.add_argument("sessions", nargs="+", help="Session numbers or ranges, e.g. 0001 0002-0010")
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--token", default=os.environ.get("LICHESS_TOKEN", ""))
    parser.add_argument("--timezone", default=DEFAULT_TZ)
    parser.add_argument("--whole-day", action="store_true", help="Search the full local day instead of a 4h window.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    if not args.token:
        print("warning: LICHESS_TOKEN is not set; this may fail if public game export is disabled.", file=sys.stderr)

    for number in expand_sessions(args.sessions):
        session = load_session(number)
        since_ms, until_ms = session_window(session, args.timezone, args.whole_day)
        games = fetch_games(args.username, args.token, since_ms, until_ms, args.timeout)
        ranked = []
        for game in games:
            score, reasons = score_game(session, game, args.username)
            ranked.append((score, reasons, game))
        ranked.sort(key=lambda item: item[0], reverse=True)

        print(f"\nSessão {number}: {len(games)} rapid candidate(s)")
        for score, reasons, game in ranked[: args.top]:
            suffix = f" | score {score}"
            if reasons:
                suffix += f" ({', '.join(reasons)})"
            print(game_summary(session, game, args.username) + suffix)


if __name__ == "__main__":
    main()
