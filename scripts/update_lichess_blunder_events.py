#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
OUTPUT_DIR = ROOT / "data" / "fcz" / "lichess_blunders"
YOUTUBE_METADATA_PATH = ROOT / "data" / "fcz" / "youtube_video_metadata.toml"
ENV_PATH = ROOT / ".env"
LOCAL_ZONE = ZoneInfo("America/Sao_Paulo")
LICHESS_URL_RE = re.compile(r"^https://lichess\.org/(?P<id>[A-Za-z0-9]{8,12})(?:/(?P<color>white|black))?$")
HEADER_RE = re.compile(r'^\[(?P<key>[A-Za-z0-9_]+)\s+"(?P<value>.*)"\]$')
COMMENT_RE = re.compile(r"\{[^}]*\}|[^\s{}]+")
CLK_RE = re.compile(r"\[%clk\s+([0-9:]+)\]")
EVAL_RE = re.compile(r"\(([^)]*?→[^)]*?)\)")
BEST_RE = re.compile(r"([A-Za-z0-9+#=xO\-]+) was best\.")
RESULT_TOKENS = {"1-0", "0-1", "1/2-1/2", "*"}
GLYPHS = ("??", "?!", "!?", "!!", "?", "!")


@dataclass(frozen=True)
class GameRef:
    session_number: str
    session_date: str
    session_time: str
    youtube_start_timestamp: int
    video_offset_seconds: int
    game_index: int
    game_id: str
    url: str


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_front_matter(path: Path) -> dict[str, Any]:
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


def lichess_id(url: Any) -> str:
    match = LICHESS_URL_RE.fullmatch(str(url or "").strip())
    return match.group("id")[:8] if match else ""


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def youtube_video_metadata() -> dict[str, Any]:
    if not YOUTUBE_METADATA_PATH.exists():
        return {}
    try:
        return tomllib.loads(YOUTUBE_METADATA_PATH.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}


def youtube_start_timestamp(session_number: str) -> int:
    sessions = youtube_video_metadata().get("sessions")
    if not isinstance(sessions, dict):
        return 0
    session = sessions.get(session_number)
    if not isinstance(session, dict):
        return 0
    return int_value(session.get("release_timestamp"))


def session_game_refs(path: Path) -> list[GameRef]:
    data = read_front_matter(path)
    if data.get("draft") is True:
        return []
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return []
    if str(extra.get("status_tone") or "").strip().casefold() in {"scheduled", "live"}:
        return []

    session_number = str(extra.get("session_number") or path.stem)
    session_date = str(data.get("date") or "")
    session_time = str(extra.get("time") or "00:00").strip() or "00:00"
    youtube_timestamp = int_value(extra.get("youtube_release_timestamp")) or youtube_start_timestamp(session_number)
    video_offset_seconds = int_value(extra.get("lichess_video_offset_seconds"))
    refs: list[GameRef] = []
    games = extra.get("games")
    if isinstance(games, list) and games:
        for index, game in enumerate(games, start=1):
            if not isinstance(game, dict):
                continue
            url = str(game.get("game_url") or game.get("lichess_game_url") or "").strip()
            game_id = lichess_id(url)
            if game_id:
                refs.append(GameRef(session_number, session_date, session_time, youtube_timestamp, video_offset_seconds, index, game_id, url))
        return refs

    url = str(extra.get("lichess_game_url") or "").strip()
    game_id = lichess_id(url)
    if game_id:
        refs.append(GameRef(session_number, session_date, session_time, youtube_timestamp, video_offset_seconds, 1, game_id, url))
    return refs


def session_numbers(numbers: set[str] | None, latest: int | None) -> list[Path]:
    paths = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        refs = session_game_refs(path)
        if refs:
            paths.append(path)
    if numbers is not None:
        return [path for path in paths if path.stem in numbers]
    if latest is not None and latest > 0:
        return paths[-latest:]
    return paths


def fetch_game(game_id: str, token: str, timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "accuracy": 1,
            "clocks": 1,
            "evals": 1,
            "literate": 1,
            "opening": 1,
            "pgnInJson": 1,
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


def pgn_headers(pgn: str) -> dict[str, str]:
    headers = {}
    for line in pgn.splitlines():
        match = HEADER_RE.match(line.strip())
        if match:
            headers[match.group("key")] = match.group("value")
    return headers


def strip_variations(text: str) -> str:
    output = []
    depth = 0
    in_comment = False
    for char in text:
        if char == "{" and depth == 0:
            in_comment = True
            output.append(char)
            continue
        if char == "}" and in_comment:
            in_comment = False
            output.append(char)
            continue
        if in_comment:
            output.append(char)
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            output.append(char)
    return "".join(output)


def body_tokens(pgn: str) -> list[str]:
    parts = pgn.split("\n\n", 1)
    body = strip_variations(parts[1] if len(parts) > 1 else pgn)
    return COMMENT_RE.findall(body)


def token_is_move_number(token: str) -> bool:
    return bool(re.fullmatch(r"\d+\.(?:\.\.)?", token))


def clean_move_token(token: str) -> tuple[str, str]:
    glyph = ""
    move = token
    for candidate in GLYPHS:
        if move.endswith(candidate):
            glyph = candidate
            move = move[: -len(candidate)]
            break
    return move, glyph


def parse_clock(value: str) -> int:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] if parts else 0


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def time_control(headers: dict[str, str]) -> tuple[int, int]:
    raw = headers.get("TimeControl", "")
    match = re.fullmatch(r"(\d+)\+(\d+)", raw)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0


def session_start_utc(ref: GameRef) -> datetime | None:
    if ref.youtube_start_timestamp:
        return datetime.fromtimestamp(ref.youtube_start_timestamp, tz=timezone.utc)
    try:
        local_start = datetime.fromisoformat(f"{ref.session_date}T{ref.session_time}:00").replace(tzinfo=LOCAL_ZONE)
    except ValueError:
        return None
    return local_start.astimezone(timezone.utc)


def game_start_utc(headers: dict[str, str]) -> datetime | None:
    raw_date = headers.get("UTCDate", "").replace(".", "-")
    raw_time = headers.get("UTCTime", "")
    try:
        return datetime.fromisoformat(f"{raw_date}T{raw_time}+00:00")
    except ValueError:
        return None


def player_name(headers: dict[str, str], color: str) -> str:
    return headers.get("White" if color == "white" else "Black", color)


def mate_label(eval_change: str) -> str:
    if "Mate in " not in eval_change:
        return ""
    mate = eval_change.rsplit("Mate in ", 1)[-1].strip()
    if mate.isdigit():
        return f"Mate em {mate}"
    return ""


def event_text(player: str, move: str, move_number: int, eval_change: str, best: str) -> str:
    details = [f"{player} jogou {move} no lance {move_number}"]
    mate = mate_label(eval_change)
    if mate:
        details.append(mate)
    return ". ".join(details) + "."


def blunder_events(ref: GameRef, payload: dict[str, Any]) -> list[dict[str, Any]]:
    pgn = str(payload.get("pgn") or "")
    headers = pgn_headers(pgn)
    initial, increment = time_control(headers)
    session_start = session_start_utc(ref)
    game_start = game_start_utc(headers)
    game_offset = round((game_start - session_start).total_seconds()) if session_start and game_start else 0
    consumed = {"white": 0, "black": 0}
    events = []
    tokens = body_tokens(pgn)
    ply = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("{") or token_is_move_number(token) or token in RESULT_TOKENS:
            index += 1
            continue

        move, glyph = clean_move_token(token)
        ply += 1
        color = "white" if ply % 2 == 1 else "black"
        move_number = (ply + 1) // 2
        comments = []
        lookahead = index + 1
        while lookahead < len(tokens) and tokens[lookahead].startswith("{"):
            comments.append(tokens[lookahead].strip("{} "))
            lookahead += 1
        index = lookahead

        clock_seconds = None
        eval_change = ""
        best = ""
        for comment in comments:
            clock_match = CLK_RE.search(comment)
            if clock_match:
                clock_seconds = parse_clock(clock_match.group(1))
            eval_match = EVAL_RE.search(comment)
            if eval_match:
                eval_change = eval_match.group(1)
            best_match = BEST_RE.search(comment)
            if best_match:
                best = best_match.group(1)

        if clock_seconds is not None and initial:
            moves_made = (ply + 1) // 2 if color == "white" else ply // 2
            consumed[color] = max(0, initial + moves_made * increment - clock_seconds)
        elapsed = consumed["white"] + consumed["black"]

        if glyph != "??":
            continue

        seconds = max(0, game_offset + elapsed + ref.video_offset_seconds)
        player = player_name(headers, color)
        opponent = player_name(headers, "black" if color == "white" else "white")
        events.append(
            {
                "time": format_time(seconds),
                "seconds": seconds,
                "source": "lichess",
                "platform": "Lichess",
                "kind": "blunder",
                "label": "Capivarada",
                "session_number": ref.session_number,
                "game_index": ref.game_index,
                "game_id": ref.game_id,
                "game_url": ref.url,
                "video_offset_seconds": ref.video_offset_seconds,
                "ply": ply,
                "move_number": move_number,
                "color": color,
                "player": player,
                "opponent": opponent,
                "is_self": player.casefold() == "fcz",
                "move": move,
                "eval_change": eval_change,
                "best": best,
                "text": event_text(player, move, move_number, eval_change, best),
            }
        )

    return events


def write_json_if_changed(path: Path, data: dict[str, Any]) -> bool:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def update_sessions(paths: list[Path], token: str, timeout: int) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    updated = 0
    for path in paths:
        session_events = []
        refs = session_game_refs(path)
        failures = []
        for ref in refs:
            try:
                payload = fetch_game(ref.game_id, token, timeout)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                failures.append(f"{ref.url}: {error}")
                continue
            session_events.extend(blunder_events(ref, payload))
        if failures:
            print(f"{path.stem}: skipped; keeping existing blunder events because Lichess fetch failed")
            for failure in failures:
                print(f"  warning: {failure}")
            continue
        session_events.sort(key=lambda item: (int(item.get("seconds") or 0), int(item.get("game_index") or 0), int(item.get("ply") or 0)))
        output = {
            "session_number": path.stem,
            "source": "lichess",
            "event_count": len(session_events),
            "events": session_events,
        }
        if write_json_if_changed(OUTPUT_DIR / f"{path.stem}.json", output):
            updated += 1
            action = "updated"
        else:
            action = "unchanged"
        print(f"{path.stem}: {action} {len(session_events)} blunder events")
    print(f"summary: {updated} updated, {len(paths) - updated} unchanged")
    return updated


def main() -> int:
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Generate timestamped Lichess blunder events for session replays.")
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0051.")
    parser.add_argument("--latest", type=int, help="Only process the latest N sessions with games.")
    parser.add_argument("--token", default=os.environ.get("LICHESS_TOKEN", ""))
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    paths = session_numbers(set(args.sessions) if args.sessions else None, args.latest)
    update_sessions(paths, args.token, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
