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


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
OUTPUT_DIR = ROOT / "data" / "fcz" / "lichess_blunders"
ANALYSIS_CACHE_PATH = ROOT / "data" / "fcz" / "lichess_game_analysis.toml"
YOUTUBE_METADATA_PATH = ROOT / "data" / "fcz" / "youtube_video_metadata.toml"
ENV_PATH = ROOT / ".env"
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
    has_video_offset: bool
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


def explicit_lichess_id(game: dict[str, Any]) -> str:
    game_id = str(game.get("game_id") or "").strip()
    return game_id if re.fullmatch(r"[A-Za-z0-9]{8}", game_id) else ""


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


def session_start_utc_from_path(path: Path, refs: list[GameRef]) -> datetime | None:
    if refs:
        return session_start_utc(refs[0])

    data = read_front_matter(path)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return None

    session_number = str(extra.get("session_number") or path.stem)
    timestamp = int_value(extra.get("youtube_release_timestamp")) or youtube_start_timestamp(session_number)
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc)


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
    global_video_offset = extra.get("lichess_video_offset_seconds")
    video_offset_seconds = int_value(global_video_offset)
    has_global_video_offset = global_video_offset is not None
    refs: list[GameRef] = []
    games = extra.get("games")
    if isinstance(games, list) and games:
        for index, game in enumerate(games, start=1):
            if not isinstance(game, dict):
                continue
            url = str(game.get("game_url") or game.get("lichess_game_url") or "").strip()
            game_id = explicit_lichess_id(game) or lichess_id(url)
            if game_id and not url:
                color = str(game.get("color") or "").strip().lower()
                url = f"https://lichess.org/{game_id}{('/' + color) if color in {'white', 'black'} else ''}"
            game_video_offset = game.get("lichess_video_offset_seconds", game.get("video_offset_seconds"))
            has_game_video_offset = game_video_offset is not None
            if game_id:
                refs.append(
                    GameRef(
                        session_number,
                        session_date,
                        session_time,
                        youtube_timestamp,
                        int_value(game_video_offset, video_offset_seconds),
                        has_game_video_offset or has_global_video_offset,
                        index,
                        game_id,
                        url,
                    )
                )
        return refs

    url = str(extra.get("lichess_game_url") or "").strip()
    game_id = lichess_id(url)
    if game_id:
        refs.append(GameRef(session_number, session_date, session_time, youtube_timestamp, video_offset_seconds, has_global_video_offset, 1, game_id, url))
    return refs


def session_numbers(numbers: set[str] | None, latest: int | None) -> list[Path]:
    if numbers is not None:
        return [
            path
            for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md"))
            if path.stem in numbers and read_front_matter(path).get("draft") is not True
        ]

    paths = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        refs = session_game_refs(path)
        if refs:
            paths.append(path)
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


@lru_cache(maxsize=1)
def cached_game_payloads() -> dict[str, dict[str, Any]]:
    if not ANALYSIS_CACHE_PATH.exists():
        return {}
    try:
        data = tomllib.loads(ANALYSIS_CACHE_PATH.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    rows = data.get("games")
    if not isinstance(rows, list):
        return {}
    payloads: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        game_id = str(row.get("game_id") or "").strip()
        pgn = str(row.get("pgn") or "").strip()
        if re.fullmatch(r"[A-Za-z0-9]{8}", game_id) and pgn:
            payloads[game_id] = {"pgn": pgn}
    return payloads


def cached_game_payload(game_id: str) -> dict[str, Any] | None:
    return cached_game_payloads().get(game_id)


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


def color_time_control(headers: dict[str, str], color: str) -> tuple[int, int]:
    initial, increment = time_control(headers)
    berserk_key = "WhiteBerserk" if color == "white" else "BlackBerserk"
    if str(headers.get(berserk_key) or "").strip().casefold() == "true":
        return initial // 2, 0
    return initial, increment


def session_start_utc(ref: GameRef) -> datetime | None:
    if not ref.youtube_start_timestamp:
        return None
    return datetime.fromtimestamp(ref.youtube_start_timestamp, tz=timezone.utc)


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


def event_text(player: str, move: str, move_number: int, clock: str, eval_change: str, best: str) -> str:
    details = [f"{player} jogou {move} no lance {move_number}"]
    if clock:
        details[0] += f", com {clock} no relógio"
    mate = mate_label(eval_change)
    if mate:
        details.append(mate)
    return ". ".join(details) + "."


def pgn_elapsed_seconds(pgn: str) -> int:
    """Return the elapsed game time represented by the last PGN clock."""
    headers = pgn_headers(pgn)
    if not time_control(headers)[0]:
        return 0
    consumed = {"white": 0, "black": 0}
    ply = 0
    last_elapsed = 0
    tokens = body_tokens(pgn)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("{") or token_is_move_number(token) or token in RESULT_TOKENS:
            index += 1
            continue

        ply += 1
        color = "white" if ply % 2 == 1 else "black"
        comments = []
        lookahead = index + 1
        while lookahead < len(tokens) and tokens[lookahead].startswith("{"):
            comments.append(tokens[lookahead].strip("{} "))
            lookahead += 1
        index = lookahead
        for comment in comments:
            clock_match = CLK_RE.search(comment)
            if clock_match:
                initial, increment = color_time_control(headers, color)
                moves_made = (ply + 1) // 2 if color == "white" else ply // 2
                consumed[color] = max(0, initial + moves_made * increment - parse_clock(clock_match.group(1)))
        last_elapsed = consumed["white"] + consumed["black"]
    return last_elapsed


def game_timeline_events(ref: GameRef, payload: dict[str, Any]) -> list[dict[str, Any]]:
    pgn = str(payload.get("pgn") or "")
    headers = pgn_headers(pgn)
    session_start = session_start_utc(ref)
    game_start = game_start_utc(headers)
    if session_start is None or game_start is None:
        return []
    game_offset = round((game_start - session_start).total_seconds())
    if game_offset < -300 and game_offset + ref.video_offset_seconds < 0:
        return []
    start_seconds = max(0, game_offset + ref.video_offset_seconds)
    end_seconds = max(start_seconds, start_seconds + pgn_elapsed_seconds(pgn))
    return [
        {
            "time": format_time(start_seconds),
            "seconds": start_seconds,
            "kind": "game_start",
            "label": f"Partida {ref.game_index}",
            "source": "lichess_pgn",
            "game_index": ref.game_index,
            "game_id": ref.game_id,
            "game_url": ref.url,
        },
        {
            "time": format_time(end_seconds),
            "seconds": end_seconds,
            "kind": "game_end",
            "label": "Fim de Partida",
            "source": "lichess_pgn",
            "game_index": ref.game_index,
            "game_id": ref.game_id,
            "game_url": ref.url,
        },
    ]


def session_video_offset(path: Path) -> int:
    data = read_front_matter(path)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return 0
    return int_value(extra.get("lichess_video_offset_seconds"))


def practice_timeline_event(path: Path, session_start: datetime | None, video_offset_seconds: int = 0) -> dict[str, Any] | None:
    if session_start is None:
        return None
    data = read_front_matter(path)
    extra = data.get("extra")
    if not isinstance(extra, dict) or not extra.get("practice_notes"):
        return None
    raw_timestamp = str(extra.get("practice_notes_recorded_at") or "").strip()
    if not raw_timestamp:
        return None
    try:
        recorded_at = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    seconds = round((recorded_at.astimezone(timezone.utc) - session_start).total_seconds()) + video_offset_seconds
    if seconds < 0:
        return None
    return {
        "time": format_time(seconds),
        "seconds": seconds,
        "kind": "practice_end",
        "label": "Fim da prática",
        "source": "practice_notes",
    }


def recorded_seconds(raw_timestamp: Any, session_start: datetime | None, video_offset_seconds: int = 0) -> int | None:
    if session_start is None:
        return None
    raw_value = str(raw_timestamp or "").strip()
    if not raw_value:
        return None
    try:
        recorded_at = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    seconds = round((recorded_at.astimezone(timezone.utc) - session_start).total_seconds()) + video_offset_seconds
    return seconds if seconds >= 0 else None


def puzzle_of_the_day_timeline_event(path: Path, session_start: datetime | None, video_offset_seconds: int = 0) -> dict[str, Any] | None:
    if session_start is None:
        return None
    data = read_front_matter(path)
    extra = data.get("extra")
    if not isinstance(extra, dict) or not extra.get("puzzle_of_the_day_url"):
        return None
    if extra.get("puzzle_of_the_day_event") != "puzzle_of_the_day":
        return None
    raw_timestamp = str(extra.get("puzzle_of_the_day_recorded_at") or "").strip()
    if not raw_timestamp:
        return None
    try:
        recorded_at = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    seconds = round((recorded_at.astimezone(timezone.utc) - session_start).total_seconds()) + video_offset_seconds
    if seconds < 0:
        return None
    return {
        "time": format_time(seconds),
        "seconds": seconds,
        "kind": "puzzle_of_the_day",
        "label": "Puzzle do dia",
        "source": "userscript",
        "url": str(extra.get("puzzle_of_the_day_url")),
    }


def storm_timeline_events(path: Path, session_start: datetime | None, video_offset_seconds: int = 0) -> list[dict[str, Any]]:
    if session_start is None:
        return []
    data = read_front_matter(path)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return []
    attempts = extra.get("storm_attempts")
    if not isinstance(attempts, list):
        return []

    events: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict):
            continue
        score = str(attempt.get("score") or "").strip()
        duration_seconds = attempt.get("duration_seconds")
        started_seconds = recorded_seconds(attempt.get("started_at"), session_start, video_offset_seconds)
        finished_seconds = recorded_seconds(attempt.get("finished_at"), session_start, video_offset_seconds)
        if started_seconds is not None:
            label = "Storm"
            if len(attempts) > 1:
                label = f"Storm {index}"
            events.append(
                {
                    "time": format_time(started_seconds),
                    "seconds": started_seconds,
                    "kind": "storm_start",
                    "label": label,
                    "source": "userscript",
                    "storm_index": index,
                    "estimated": bool(attempt.get("estimated_start")),
                }
            )
    return events


def blunder_events(ref: GameRef, payload: dict[str, Any]) -> list[dict[str, Any]]:
    pgn = str(payload.get("pgn") or "")
    headers = pgn_headers(pgn)
    has_clock_time_control = bool(time_control(headers)[0])
    session_start = session_start_utc(ref)
    if session_start is None:
        print(
            f"{ref.session_number}: skipping timestamped blunders for {ref.game_id}; "
            "actual YouTube release timestamp is unavailable"
        )
        return []
    game_start = game_start_utc(headers)
    game_offset = round((game_start - session_start).total_seconds()) if session_start and game_start else 0
    if game_offset < -300 and game_offset + ref.video_offset_seconds < 0:
        print(
            f"{ref.session_number}: skipping timestamped blunders for {ref.game_id}; "
            "game started before the live and the configured offset does not place it in the video"
        )
        return []
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

        if clock_seconds is not None and has_clock_time_control:
            initial, increment = color_time_control(headers, color)
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
                "clock": format_time(clock_seconds) if clock_seconds is not None else "",
                "eval_change": eval_change,
                "best": best,
                "text": event_text(
                    player,
                    move,
                    move_number,
                    format_time(clock_seconds) if clock_seconds is not None else "",
                    eval_change,
                    best,
                ),
            }
        )

    return events


def write_json_if_changed(path: Path, data: dict[str, Any]) -> bool:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def existing_output(session: str) -> dict[str, Any]:
    path = OUTPUT_DIR / f"{session}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def update_sessions(paths: list[Path], token: str, timeout: int) -> int:
    refs_by_path: list[tuple[Path, list[GameRef]]] = []
    missing_timestamps: list[str] = []
    for path in paths:
        refs = session_game_refs(path)
        refs_by_path.append((path, refs))
        for ref in refs:
            if not ref.youtube_start_timestamp:
                missing_timestamps.append(f"{path.stem} ({ref.game_id})")
    if missing_timestamps:
        details = ", ".join(missing_timestamps)
        raise RuntimeError(
            "Cannot generate timestamped blunders: missing actual YouTube release timestamp for "
            f"{details}. Refusing to use the scheduled session time."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    updated = 0
    for path, refs in refs_by_path:
        session_events = []
        timeline_events: list[dict[str, Any]] = []
        failures = []
        session_start = session_start_utc_from_path(path, refs)
        if session_start is not None:
            video_offset_seconds = session_video_offset(path)
            practice_event = practice_timeline_event(path, session_start, video_offset_seconds)
            if practice_event:
                timeline_events.append(practice_event)
            puzzle_event = puzzle_of_the_day_timeline_event(path, session_start, video_offset_seconds)
            if puzzle_event:
                timeline_events.append(puzzle_event)
            timeline_events.extend(storm_timeline_events(path, session_start, video_offset_seconds))
        for ref in refs:
            payload = cached_game_payload(ref.game_id)
            if payload is None:
                try:
                    payload = fetch_game(ref.game_id, token, timeout)
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                    failures.append(f"{ref.url}: {error}")
                    continue
            session_events.extend(blunder_events(ref, payload))
            timeline_events.extend(game_timeline_events(ref, payload))
        if failures:
            print(f"{path.stem}: keeping existing Lichess-derived events because Lichess fetch failed")
            for failure in failures:
                print(f"  warning: {failure}")
            existing = existing_output(path.stem)
            existing_events = existing.get("events")
            if isinstance(existing_events, list):
                session_events = [event for event in existing_events if isinstance(event, dict)]
            existing_timeline = existing.get("timeline")
            if isinstance(existing_timeline, list):
                timeline_events.extend(
                    event
                    for event in existing_timeline
                    if isinstance(event, dict) and event.get("kind") in {"game_start", "game_end"}
                )
        session_events.sort(key=lambda item: (int(item.get("seconds") or 0), int(item.get("game_index") or 0), int(item.get("ply") or 0)))
        timeline_events.extend(session_events)
        timeline_events.sort(
            key=lambda item: (
                int(item.get("seconds") or 0),
                {
                    "session_start": 0,
                    "puzzle_of_the_day": 1,
                    "storm_start": 2,
                    "practice_end": 3,
                    "game_start": 4,
                    "blunder": 5,
                    "game_end": 6,
                }.get(item.get("kind"), 9),
            )
        )
        output = {
            "session_number": path.stem,
            "source": "lichess",
            "event_count": len(session_events),
            "events": session_events,
            "timeline": timeline_events,
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
