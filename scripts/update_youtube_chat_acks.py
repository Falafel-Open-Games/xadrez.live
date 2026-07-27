#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DEFAULT_CACHE_DIR = Path("/tmp/xadrez-live-youtube-chat")
SELF_NAMES = {"@fczuardi", "Fabricio C Zuardi"}


@dataclass
class Session:
    number: str
    path: Path
    date: date | None
    youtube_id: str


def log(message: str) -> None:
    print(message, file=sys.stderr)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def extract_front_matter(text: str, path: Path) -> str:
    if not text.startswith("+++"):
        fail(f"missing TOML front matter in {path}")

    marker = "\n+++"
    end = text.find(marker, 3)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")

    return text[3:end].strip()


def load_sessions(numbers: set[str] | None, limit_latest: int | None) -> list[Session]:
    sessions = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        number = path.stem
        if numbers is not None and number not in numbers:
            continue

        text = path.read_text(encoding="utf-8")
        front_matter = extract_front_matter(text, path)
        try:
            data = tomllib.loads(front_matter)
        except tomllib.TOMLDecodeError as error:
            fail(f"malformed TOML front matter in {path}: {error}")

        extra = data.get("extra")
        if not isinstance(extra, dict):
            continue

        youtube_id = str(extra.get("youtube_video_id") or "").strip()
        if not youtube_id or youtube_id == "REPLACE_WITH_YOUTUBE_VIDEO_ID":
            continue

        raw_date = data.get("date")
        session_date = raw_date if isinstance(raw_date, date) else None
        sessions.append(Session(number, path, session_date, youtube_id))

    if numbers is None and limit_latest is not None:
        sessions = sessions[-limit_latest:]

    return sessions


def recent_session(session: Session, today: date, days: int) -> bool:
    if session.date is None:
        return False
    age = (today - session.date).days
    return 0 <= age <= days


def yt_dlp_command(
    yt_dlp: str,
    youtube_id: str,
    cache_dir: Path,
    js_runtime: str | None,
) -> list[str]:
    cmd = [yt_dlp]
    if js_runtime:
        cmd.extend(["--js-runtimes", js_runtime])
    cmd.extend(
        [
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
            f"https://www.youtube.com/live/{youtube_id}",
        ]
    )
    return cmd


def download_chat(
    session: Session,
    cache_dir: Path,
    yt_dlp: str,
    js_runtime: str | None,
    force: bool,
) -> Path | None:
    output = cache_dir / f"{session.youtube_id}.live_chat.json"
    if output.exists() and not force:
        return output

    cache_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        yt_dlp_command(yt_dlp, session.youtube_id, cache_dir, js_runtime),
        check=False,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if proc.returncode != 0:
        last_line = (proc.stderr.strip().splitlines() or ["yt-dlp failed"])[-1]
        if output.exists():
            log(f"{session.number}: refresh failed; using cached chat ({last_line})")
            return output
        log(f"{session.number}: no chat replay yet ({last_line})")
        return output if output.exists() else None

    if not output.exists():
        log(f"{session.number}: no live_chat subtitle")
        return None

    return output


def message_renderer(action: dict) -> dict | None:
    item = action.get("addChatItemAction", {}).get("item", {})
    renderer = item.get("liveChatTextMessageRenderer")
    return renderer if isinstance(renderer, dict) else None


def youtube_users(chat_path: Path) -> list[str]:
    users = []
    for line in chat_path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        actions = item.get("replayChatItemAction", {}).get("actions", [])
        for action in actions:
            if not isinstance(action, dict):
                continue
            renderer = message_renderer(action)
            if not renderer:
                continue
            name = renderer.get("authorName", {}).get("simpleText")
            if name and name not in SELF_NAMES and name not in users:
                users.append(name)
    return users


def youtube_link(name: str) -> str:
    handle = name[1:] if name.startswith("@") else name
    return f"[{name}](https://www.youtube.com/@{quote(handle)})"


def youtube_line(users: list[str]) -> str:
    return "- YouTube: " + ", ".join(youtube_link(user) for user in users)


def replace_acknowledgements(text: str, users: list[str]) -> str:
    line = youtube_line(users)
    heading_match = re.search(r"(?m)^## Agradecimentos\n", text)
    if not heading_match:
        suffix = "" if text.endswith("\n") else "\n"
        return text + suffix + "\n## Agradecimentos\n\n" + line + "\n"

    after_heading = heading_match.end()
    next_heading = re.search(r"(?m)^## ", text[after_heading:])
    end = after_heading + next_heading.start() if next_heading else len(text)
    section = text[after_heading:end]

    kept = []
    for raw in section.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("- youtube:") or lower.startswith("- youtube "):
            continue
        if "youtube.com/" in lower:
            continue
        kept.append(raw.rstrip())

    new_section = "\n".join(["", line, *kept]) + "\n"
    return text[:after_heading] + new_section + text[end:]


def node_runtime() -> str | None:
    node = shutil.which("node")
    return f"node:{node}" if node else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update session acknowledgements from YouTube chat replays."
    )
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0042")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument(
        "--js-runtime",
        default=node_runtime(),
        help="yt-dlp JavaScript runtime, e.g. node:/path/to/node. Use '' to disable.",
    )
    parser.add_argument(
        "--refresh-recent-days",
        type=int,
        default=3,
        help="Force re-download for sessions from the last N days.",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=5,
        help="Only scan the latest N sessions by default. Use 0 with --all to scan everything.",
    )
    parser.add_argument("--all", action="store_true", help="Scan all sessions.")
    parser.add_argument("--force", action="store_true", help="Re-download all selected chats.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = set(args.sessions) if args.sessions else None
    limit_latest = None if selected or args.all else args.latest
    js_runtime = args.js_runtime.strip() if args.js_runtime else None
    today = date.today()
    changed = []
    skipped = 0

    for session in load_sessions(selected, limit_latest):
        force = args.force or recent_session(session, today, args.refresh_recent_days)
        chat_path = download_chat(session, args.cache_dir, args.yt_dlp, js_runtime, force)
        if not chat_path:
            skipped += 1
            continue

        users = youtube_users(chat_path)
        if not users:
            log(f"{session.number}: no viewer chat messages")
            skipped += 1
            continue

        text = session.path.read_text(encoding="utf-8")
        new_text = replace_acknowledgements(text, users)
        if new_text == text:
            log(f"{session.number}: already up to date")
            continue

        changed.append((session, users))
        if args.dry_run:
            print(f"{session.number}: {', '.join(users)}")
        else:
            session.path.write_text(new_text, encoding="utf-8")
            log(f"{session.number}: updated {', '.join(users)}")

    action = "would update" if args.dry_run else "updated"
    log(f"{action}: {len(changed)}; skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
