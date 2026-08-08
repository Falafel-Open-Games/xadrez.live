#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DATA_DIR = ROOT / "data" / "fcz"
WRAP_DIR = DATA_DIR / "wrap_sessions"
RESTREAM_DIR = DATA_DIR / "restream_chat_replays"
INBOX_DIR = DATA_DIR / "wrap_inbox"
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
ARRAY_REPLACE_KEYS = {"streak_attempts", "practice_sets", "games", "supporters"}
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


def load_wrap_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        fail(f"invalid wrap TOML in {path}: {error}")


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
    return data


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


def latest_lichess_ratings() -> dict[str, str]:
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


def run(command: list[str], dry_run: bool) -> None:
    print(f"$ {' '.join(command)}")
    if dry_run:
        return
    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist and apply a daily xadrez.live wrapup from files.")
    parser.add_argument("session", help="Session number, e.g. 0054")
    parser.add_argument("--toml-file", type=Path, help="TOML fragment from the userscript; defaults to data/fcz/wrap_inbox/NNNN.toml when present")
    parser.add_argument("--chat-json-file", type=Path, help="Restream chat JSON from the userscript; defaults to data/fcz/wrap_inbox/NNNN-chat.json when present")
    parser.add_argument("--dry-run", action="store_true", help="Persist raw inputs and print commands without applying changes")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-capivaradas", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = args.session.zfill(4)
    toml_file = args.toml_file or (INBOX_DIR / f"{session}.toml" if (INBOX_DIR / f"{session}.toml").exists() else None)
    chat_json_file = args.chat_json_file or (INBOX_DIR / f"{session}-chat.json" if (INBOX_DIR / f"{session}-chat.json").exists() else None)
    path, data, body = read_session(session)
    state: dict[str, Any] = {"session": session, "updated_at": datetime.now(timezone.utc).isoformat(), "inputs": {}}

    if toml_file:
        raw_toml = toml_file.read_text(encoding="utf-8")
        state["inputs"]["toml_file"] = str(toml_file)
        state["inputs"]["toml"] = raw_toml
        data = apply_wrap_toml(session, data, load_wrap_toml(toml_file))
        if not args.dry_run:
            write_session(path, data, body)
        print(f"{session}: applied TOML to {path}")
    else:
        print(f"{session}: no TOML input found")

    if chat_json_file:
        raw_chat_text = chat_json_file.read_text(encoding="utf-8")
        raw_chat = json.loads(raw_chat_text)
        state["inputs"]["chat_json_file"] = str(chat_json_file)
        state["inputs"]["chat_json"] = raw_chat
        replay = normalize_chat(session, data, raw_chat)
        added_supporters = merge_session_supporters(data, chat_supporters(replay["messages"]))
        if not args.dry_run:
            save_json(RESTREAM_DIR / f"{session}.json", replay)
            write_session(path, data, body)
        print(f"{session}: imported {replay['message_count']} Restream chat message(s)")
        print(f"{session}: added {added_supporters} supporter(s) from chat")
    else:
        print(f"{session}: no Restream chat input found")

    if not args.dry_run:
        save_json(WRAP_DIR / f"{session}.json", state)
        refresh_automatic_stat_sources(session, args.dry_run)
        updated_stats = auto_fill_post_stats(session, data)
        if updated_stats:
            write_session(path, data, body)
            print(f"{session}: auto-filled post stats ({', '.join(updated_stats)})")
        if chat_json_file:
            run(["python3", "scripts/merge_chat_replays.py", session], args.dry_run)
        if not args.skip_capivaradas:
            run(["just", "update-session-capivaradas", session], args.dry_run)
        run(["just", "verify-session", session], args.dry_run)
        if not args.skip_build:
            run(["just", "build"], args.dry_run)
    else:
        print(f"{session}: dry run; no files written")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
