#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "chat_replays"
DEFAULT_RESTREAM_DIR = ROOT / "data" / "restream_chat_replays"
DEFAULT_YOUTUBE_DIR = ROOT / "data" / "youtube_chat_replays"
DEFAULT_TWITCH_DIR = ROOT / "data" / "twitch_chat_replays"
ANON_AUTHOR_RE = re.compile(r"^Person \d+$")
SOURCE_PRIORITY = {"restream": 0, "restream-html": 0, "youtube": 1, "twitch": 2}


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def extract_front_matter(text: str, path: Path) -> str:
    if not text.startswith("+++"):
        fail(f"missing TOML front matter in {path}")

    marker = "\n+++"
    end = text.find(marker, 3)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")

    return text[3:end].strip()


def session_numbers(numbers: set[str] | None, latest: int | None) -> list[str]:
    sessions = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        data = tomllib.loads(extract_front_matter(path.read_text(encoding="utf-8"), path))
        extra = data.get("extra")
        if not isinstance(extra, dict):
            continue
        youtube_id = str(extra.get("youtube_video_id") or "").strip()
        status = str(extra.get("status") or "").strip().lower()
        status_tone = str(extra.get("status_tone") or "").strip().lower()
        is_ended = status == "encerrada" or status_tone in {"ended", "completed"}
        if youtube_id and youtube_id != "REPLACE_WITH_YOUTUBE_VIDEO_ID" and is_ended:
            sessions.append(path.stem)

    if numbers is not None:
        return [session for session in sessions if session in numbers]
    if latest is not None and latest > 0:
        return sessions[-latest:]
    return sessions


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def message_source(message: dict[str, Any], fallback: str) -> str:
    raw = str(message.get("source") or fallback).strip().lower()
    if raw in {"restream", "restream-html", "youtube", "twitch"}:
        return raw
    platform = str(message.get("platform") or "").strip().lower()
    if platform == "youtube":
        return "youtube"
    if platform == "twitch":
        return "twitch"
    return fallback


def normalize_message(raw: dict[str, Any], fallback_source: str) -> dict[str, Any] | None:
    text = str(raw.get("text") or "").strip()
    author = str(raw.get("author") or "").strip()
    if not text or not author:
        return None

    seconds = max(0, int(round(float(raw.get("seconds") or 0))))
    source = message_source(raw, fallback_source)
    platform = str(raw.get("platform") or "").strip()
    if not platform:
        if source == "youtube":
            platform = "YouTube"
        elif source == "twitch":
            platform = "Twitch"
    message = {
        "time": format_time(seconds),
        "seconds": seconds,
        "platform": platform,
        "channel": str(raw.get("channel") or "").strip(),
        "author": author,
        "text": text,
        "source": source,
    }
    badges = raw.get("badges")
    if isinstance(badges, list) and badges:
        message["badges"] = [str(badge) for badge in badges]
    if raw.get("twitch_vod_id"):
        message["twitch_vod_id"] = str(raw["twitch_vod_id"])
    return message


def source_messages(data: dict[str, Any] | None, fallback_source: str) -> list[dict[str, Any]]:
    if not data:
        return []
    raw_messages = data.get("messages")
    if not isinstance(raw_messages, list):
        return []
    messages = []
    for raw in raw_messages:
        if not isinstance(raw, dict):
            continue
        message = normalize_message(raw, fallback_source)
        if message:
            messages.append(message)
    return messages


def author_lookups(messages: list[dict[str, Any]], max_delta_seconds: int) -> tuple[dict[tuple[str, int], str], dict[str, str]]:
    timed_lookup = {}
    text_authors: dict[str, set[str]] = {}
    for message in messages:
        text = str(message.get("text") or "")
        author = str(message.get("author") or "")
        seconds = int(message.get("seconds") or 0)
        if not text or not author or ANON_AUTHOR_RE.match(author):
            continue
        text_authors.setdefault(text, set()).add(author)
        for delta in range(-max_delta_seconds, max_delta_seconds + 1):
            timed_lookup.setdefault((text, seconds + delta), author)

    text_lookup = {text: next(iter(authors)) for text, authors in text_authors.items() if len(authors) == 1}
    return timed_lookup, text_lookup


def deanonymize(
    messages: list[dict[str, Any]],
    youtube_messages: list[dict[str, Any]],
    twitch_messages: list[dict[str, Any]],
    max_delta_seconds: int,
) -> list[dict[str, Any]]:
    youtube_timed, youtube_text = author_lookups(youtube_messages, max_delta_seconds)
    twitch_timed, twitch_text = author_lookups(twitch_messages, max_delta_seconds)
    resolved = []
    for message in messages:
        message = dict(message)
        author = str(message.get("author") or "")
        if not ANON_AUTHOR_RE.match(author):
            resolved.append(message)
            continue

        text = str(message.get("text") or "")
        seconds = int(message.get("seconds") or 0)
        platform = str(message.get("platform") or "")
        if platform == "YouTube":
            message["author"] = youtube_timed.get((text, seconds), youtube_text.get(text, author))
        elif platform == "Twitch":
            message["author"] = twitch_timed.get((text, seconds), twitch_text.get(text, author))
        resolved.append(message)
    return resolved


def duplicate_key(message: dict[str, Any], max_delta_seconds: int) -> tuple[str, str, int]:
    seconds = int(message.get("seconds") or 0)
    bucket = round(seconds / max_delta_seconds) if max_delta_seconds > 0 else seconds
    return (str(message.get("platform") or ""), str(message.get("text") or ""), bucket)


def same_known_author(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_author = str(left.get("author") or "").strip()
    right_author = str(right.get("author") or "").strip()
    if not left_author or not right_author:
        return True
    if ANON_AUTHOR_RE.match(left_author) or ANON_AUTHOR_RE.match(right_author):
        return True
    return left_author == right_author


def known_author(value: Any) -> str:
    author = str(value or "").strip()
    if not author or ANON_AUTHOR_RE.match(author):
        return ""
    return author


def same_message(left: dict[str, Any], right: dict[str, Any], max_delta_seconds: int) -> bool:
    same_platform = str(left.get("platform") or "") == str(right.get("platform") or "")
    same_text = str(left.get("text") or "") == str(right.get("text") or "")
    if not same_platform or not same_text or not same_known_author(left, right):
        return False

    left_author = known_author(left.get("author"))
    right_author = known_author(right.get("author"))
    if left_author and left_author == right_author:
        return True

    return (
        abs(int(left.get("seconds") or 0) - int(right.get("seconds") or 0)) <= max_delta_seconds
    )


def richer_message(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    chosen = dict(left)
    if ANON_AUTHOR_RE.match(str(chosen.get("author") or "")) and not ANON_AUTHOR_RE.match(str(right.get("author") or "")):
        chosen["author"] = right["author"]
    if not chosen.get("channel") and right.get("channel"):
        chosen["channel"] = right["channel"]
    if not chosen.get("badges") and right.get("badges"):
        chosen["badges"] = right["badges"]
    if not chosen.get("twitch_vod_id") and right.get("twitch_vod_id"):
        chosen["twitch_vod_id"] = right["twitch_vod_id"]
    return chosen


def merge_messages(source_groups: list[list[dict[str, Any]]], max_delta_seconds: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for group in source_groups:
        for message in group:
            duplicate_index = None
            for index, existing in enumerate(merged):
                if same_message(existing, message, max_delta_seconds):
                    duplicate_index = index
                    break
            if duplicate_index is None:
                merged.append(message)
            else:
                existing = merged[duplicate_index]
                existing_priority = SOURCE_PRIORITY.get(str(existing.get("source") or ""), 99)
                new_priority = SOURCE_PRIORITY.get(str(message.get("source") or ""), 99)
                if new_priority < existing_priority:
                    merged[duplicate_index] = richer_message(message, existing)
                else:
                    merged[duplicate_index] = richer_message(existing, message)

    return sorted(merged, key=lambda item: (int(item.get("seconds") or 0), SOURCE_PRIORITY.get(str(item.get("source") or ""), 99)))


def build_replay(
    session_number: str,
    restream_dir: Path,
    youtube_dir: Path,
    twitch_dir: Path,
    max_delta_seconds: int,
) -> dict[str, Any] | None:
    restream_data = read_json(restream_dir / f"{session_number}.json")
    youtube_data = read_json(youtube_dir / f"{session_number}.json")
    twitch_data = read_json(twitch_dir / f"{session_number}.json")
    restream_messages = source_messages(restream_data, "restream")
    youtube_messages = source_messages(youtube_data, "youtube")
    twitch_messages = source_messages(twitch_data, "twitch")
    if not restream_messages and not youtube_messages and not twitch_messages:
        return None

    if restream_messages:
        restream_messages = deanonymize(restream_messages, youtube_messages, twitch_messages, max_delta_seconds)
        messages = merge_messages([restream_messages], max_delta_seconds)
        sources = ["restream"]
    else:
        messages = merge_messages([youtube_messages, twitch_messages], max_delta_seconds)
        sources = []
        if youtube_data:
            sources.append("youtube")
        if twitch_data:
            sources.append("twitch")

    platforms = sorted({str(message.get("platform") or "") for message in messages if message.get("platform")})

    output: dict[str, Any] = {
        "session_number": session_number,
        "source": "merged",
        "sources": sources,
        "platforms": platforms,
        "message_count": len(messages),
        "messages": messages,
    }
    for data in (restream_data, youtube_data, twitch_data):
        if not data:
            continue
        if data.get("youtube_video_id") and not output.get("youtube_video_id"):
            output["youtube_video_id"] = data["youtube_video_id"]
        if data.get("restream_event_id") and not output.get("restream_event_id"):
            output["restream_event_id"] = data["restream_event_id"]
    return output


def write_json_if_changed(path: Path, data: dict[str, Any]) -> bool:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def merge_replays(
    output_dir: Path,
    restream_dir: Path,
    youtube_dir: Path,
    twitch_dir: Path,
    selected_numbers: set[str] | None,
    latest: int | None,
    max_delta_seconds: int,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    updated = 0
    unchanged = 0
    missing = 0
    for session_number in session_numbers(selected_numbers, latest):
        replay = build_replay(session_number, restream_dir, youtube_dir, twitch_dir, max_delta_seconds)
        if replay is None:
            print(f"{session_number}: no chat replay sources")
            missing += 1
            continue
        output_path = output_dir / f"{session_number}.json"
        if write_json_if_changed(output_path, replay):
            print(
                f"{session_number}: merged {replay['message_count']} messages "
                f"from {', '.join(replay['sources'])}"
            )
            updated += 1
        else:
            print(
                f"{session_number}: unchanged {replay['message_count']} messages "
                f"from {', '.join(replay['sources'])}"
            )
            unchanged += 1
    print(f"summary: {updated} updated, {unchanged} unchanged, {missing} missing")
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge primary chat replay sources into the site chat replay data.")
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0015")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--restream-dir", type=Path, default=DEFAULT_RESTREAM_DIR)
    parser.add_argument("--youtube-dir", type=Path, default=DEFAULT_YOUTUBE_DIR)
    parser.add_argument("--twitch-dir", type=Path, default=DEFAULT_TWITCH_DIR)
    parser.add_argument("--latest", type=int, help="Only process the latest N ended sessions.")
    parser.add_argument("--match-window", type=int, default=90)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    merge_replays(
        output_dir=args.output_dir,
        restream_dir=args.restream_dir,
        youtube_dir=args.youtube_dir,
        twitch_dir=args.twitch_dir,
        selected_numbers=set(args.sessions) if args.sessions else None,
        latest=args.latest,
        max_delta_seconds=args.match_window,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
