#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DEFAULT_CACHE_DIR = Path("/tmp/xadrez-chat")
DEFAULT_OUTPUT_DIR = ROOT / "data" / "chat_replays"


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


def session_youtube_ids() -> list[tuple[str, str, Path]]:
    sessions: list[tuple[str, str, Path]] = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        data = tomllib.loads(extract_front_matter(path.read_text(encoding="utf-8"), path))
        extra = data.get("extra")
        if not isinstance(extra, dict):
            continue

        youtube_id = str(extra.get("youtube_video_id") or "").strip()
        status_tone = str(extra.get("status_tone") or "").strip()
        if youtube_id and youtube_id != "REPLACE_WITH_YOUTUBE_VIDEO_ID" and status_tone == "ended":
            sessions.append((youtube_id, path.stem, path))

    return sessions


def selected_sessions(all_sessions: list[tuple[str, str, Path]], numbers: set[str] | None, latest: int | None) -> list[tuple[str, str, Path]]:
    sessions = all_sessions
    if numbers is not None:
        sessions = [session for session in sessions if session[1] in numbers]
    elif latest is not None and latest > 0:
        sessions = sessions[-latest:]
    return sessions


def download_chat(youtube_id: str, cache_dir: Path, yt_dlp: str, force: bool) -> Path | None:
    chat_path = cache_dir / f"{youtube_id}.live_chat.json"
    if chat_path.exists() and not force:
        return chat_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            yt_dlp,
            "--skip-download",
            "--write-subs",
            "--sub-langs",
            "live_chat",
            "--sub-format",
            "json",
            "--paths",
            str(cache_dir),
            "--output",
            "%(id)s",
            f"https://www.youtube.com/watch?v={youtube_id}",
        ],
        check=False,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        last_line = (proc.stderr.strip().splitlines() or proc.stdout.strip().splitlines() or ["yt-dlp failed"])[-1]
        print(f"{youtube_id}: chat unavailable ({last_line})")
        return chat_path if chat_path.exists() else None

    if not chat_path.exists():
        print(f"{youtube_id}: no live_chat replay file")
        return None

    return chat_path


def runs_text(runs: list[dict]) -> str:
    chunks = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if "text" in run:
            chunks.append(str(run["text"]))
            continue

        emoji = run.get("emoji")
        if isinstance(emoji, dict):
            shortcuts = emoji.get("shortcuts")
            if isinstance(shortcuts, list) and shortcuts:
                chunks.append(str(shortcuts[0]))
            elif emoji.get("emojiId"):
                chunks.append(str(emoji["emojiId"]))

    return "".join(chunks).strip()


def renderer_message(renderer: dict) -> str:
    message = renderer.get("message")
    if not isinstance(message, dict):
        return ""

    runs = message.get("runs")
    if isinstance(runs, list):
        return runs_text(runs)

    simple_text = message.get("simpleText")
    return str(simple_text).strip() if simple_text else ""


def author_badges(renderer: dict) -> list[str]:
    badges = []
    for raw_badge in renderer.get("authorBadges") or []:
        if not isinstance(raw_badge, dict):
            continue
        badge = raw_badge.get("liveChatAuthorBadgeRenderer")
        if not isinstance(badge, dict):
            continue
        tooltip = badge.get("tooltip")
        if tooltip:
            badges.append(str(tooltip))
    return badges


def text_message_renderer(action: dict) -> dict | None:
    item = action.get("addChatItemAction", {}).get("item", {})
    renderer = item.get("liveChatTextMessageRenderer")
    return renderer if isinstance(renderer, dict) else None


def parse_chat(chat_path: Path) -> list[dict]:
    messages = []
    for line in chat_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        actions = item.get("replayChatItemAction", {}).get("actions", [])
        for action in actions:
            if not isinstance(action, dict):
                continue

            renderer = text_message_renderer(action)
            if not renderer:
                continue

            author = renderer.get("authorName", {}).get("simpleText")
            text = renderer_message(renderer)
            if not author or not text:
                continue

            offset_ms = int(item.get("replayChatItemAction", {}).get("videoOffsetTimeMsec") or 0)
            timestamp = renderer.get("timestampText", {}).get("simpleText") or format_time(offset_ms)
            messages.append(
                {
                    "time": timestamp,
                    "seconds": max(0, round(offset_ms / 1000)),
                    "author": str(author),
                    "text": text,
                    "badges": author_badges(renderer),
                }
            )

    return messages


def format_time(offset_ms: int) -> str:
    total_seconds = max(0, round(offset_ms / 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def import_replays(
    cache_dir: Path,
    output_dir: Path,
    selected_numbers: set[str] | None,
    latest: int | None,
    download: bool,
    force: bool,
    yt_dlp: str,
) -> int:
    sessions = selected_sessions(session_youtube_ids(), selected_numbers, latest)
    output_dir.mkdir(parents=True, exist_ok=True)
    imported = 0

    for youtube_id, session_number, _ in sessions:
        chat_path = download_chat(youtube_id, cache_dir, yt_dlp, force) if download else cache_dir / f"{youtube_id}.live_chat.json"
        if chat_path is None:
            continue
        if not chat_path.exists():
            continue

        messages = parse_chat(chat_path)
        if not messages:
            continue

        output_path = output_dir / f"{session_number}.json"
        output = {
            "session_number": session_number,
            "youtube_video_id": youtube_id,
            "message_count": len(messages),
            "messages": messages,
        }
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{session_number}: imported {len(messages)} messages from {chat_path}")
        imported += 1

    return imported


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import cached YouTube live_chat replay JSON into static session chat replay data."
    )
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0038")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--latest", type=int, help="Only process the latest N ended sessions.")
    parser.add_argument("--download", action="store_true", help="Download missing live_chat replay files with yt-dlp before importing.")
    parser.add_argument("--force", action="store_true", help="Re-download chat replay files when using --download.")
    parser.add_argument("--yt-dlp", default="yt-dlp")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_numbers = set(args.sessions) if args.sessions else None
    imported = import_replays(
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        selected_numbers=selected_numbers,
        latest=args.latest,
        download=args.download,
        force=args.force,
        yt_dlp=args.yt_dlp,
    )
    print(f"imported: {imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
