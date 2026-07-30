#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = Path("/tmp/xadrez-twitch-chat")
DEFAULT_OUTPUT_DIR = ROOT / "data" / "twitch_chat_replays"
DEFAULT_CHANNEL_URL = "https://www.twitch.tv/sedentarismo/videos"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
GQL_URL = "https://gql.twitch.tv/gql"
COMMENTS_QUERY_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"
SESSION_RE = re.compile(r"#(\d{4})")


def gql_request(payload: list[dict]) -> Any:
    request = urllib.request.Request(
        GQL_URL,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Client-ID": TWITCH_CLIENT_ID,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "xadrez-live-twitch-chat-importer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Twitch GraphQL failed with HTTP {error.code}: {body}") from error


def comments_payload(video_id: str, cursor: str | None) -> list[dict]:
    variables: dict[str, str | int] = {"videoID": video_id}
    if cursor:
        variables["cursor"] = cursor
    else:
        variables["contentOffsetSeconds"] = 0
    return [
        {
            "operationName": "VideoCommentsByOffsetOrCursor",
            "variables": variables,
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": COMMENTS_QUERY_HASH,
                }
            },
        }
    ]


def fetch_comments(video_id: str, cache_dir: Path, force: bool) -> list[dict]:
    cache_path = cache_dir / f"{video_id}.comments.json"
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    cache_dir.mkdir(parents=True, exist_ok=True)
    comments: list[dict] = []
    cursor = None
    while True:
        data = gql_request(comments_payload(video_id, cursor))
        video = data[0].get("data", {}).get("video") if isinstance(data, list) and data else None
        if not isinstance(video, dict):
            break

        comment_data = video.get("comments")
        if not isinstance(comment_data, dict):
            break

        edges = comment_data.get("edges")
        if isinstance(edges, list):
            comments.extend(edge.get("node") for edge in edges if isinstance(edge, dict) and isinstance(edge.get("node"), dict))

        page_info = comment_data.get("pageInfo")
        has_next = bool(page_info.get("hasNextPage")) if isinstance(page_info, dict) else False
        if not has_next or not edges:
            break
        cursor = edges[-1].get("cursor")
        if not cursor:
            break
        time.sleep(0.1)

    cache_path.write_text(json.dumps(comments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return comments


def list_vods(channel_url: str, playlist_end: int, yt_dlp: str) -> list[dict]:
    proc = subprocess.run(
        [
            yt_dlp,
            "--flat-playlist",
            "--playlist-end",
            str(playlist_end),
            "--dump-json",
            channel_url,
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr.strip().splitlines() or ["yt-dlp failed"])[-1])

    vods = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        title = str(item.get("title") or "")
        match = SESSION_RE.search(title)
        if not match:
            continue
        video_id = str(item.get("id") or "").removeprefix("v")
        if not video_id:
            continue
        vods.append(
            {
                "session_number": match.group(1),
                "video_id": video_id,
                "title": title,
                "url": str(item.get("url") or item.get("webpage_url") or f"https://www.twitch.tv/videos/{video_id}"),
            }
        )
    return vods


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def comment_text(comment: dict) -> str:
    fragments = comment.get("message", {}).get("fragments", [])
    if not isinstance(fragments, list):
        return ""
    return "".join(str(fragment.get("text") or "") for fragment in fragments if isinstance(fragment, dict)).strip()


def commenter_name(comment: dict) -> str:
    commenter = comment.get("commenter")
    if not isinstance(commenter, dict):
        return "unknown"
    display_name = str(commenter.get("displayName") or "").strip()
    login = str(commenter.get("login") or "").strip()
    return display_name or login or "unknown"


def normalize_comments(comments: list[dict], vod: dict) -> list[dict]:
    messages = []
    for comment in comments:
        text = comment_text(comment)
        if not text:
            continue
        seconds = round(float(comment.get("contentOffsetSeconds") or 0))
        name = commenter_name(comment)
        messages.append(
            {
                "time": format_time(seconds),
                "seconds": seconds,
                "platform": "Twitch",
                "channel": "sedentarismo",
                "author": f"@{name}",
                "text": text,
                "twitch_vod_id": vod["video_id"],
            }
        )
    return sorted(messages, key=lambda message: (message["twitch_vod_id"], int(message["seconds"])))


def import_chats(
    channel_url: str,
    cache_dir: Path,
    output_dir: Path,
    selected_numbers: set[str] | None,
    playlist_end: int,
    force: bool,
    yt_dlp: str,
) -> int:
    vods = list_vods(channel_url, playlist_end, yt_dlp)
    by_session: dict[str, list[dict]] = {}
    for vod in vods:
        if selected_numbers is not None and vod["session_number"] not in selected_numbers:
            continue
        by_session.setdefault(vod["session_number"], []).append(vod)

    output_dir.mkdir(parents=True, exist_ok=True)
    imported = 0
    for session_number, session_vods in sorted(by_session.items()):
        all_messages = []
        for vod in session_vods:
            comments = fetch_comments(vod["video_id"], cache_dir, force)
            all_messages.extend(normalize_comments(comments, vod))

        if not all_messages:
            continue

        output = {
            "session_number": session_number,
            "source": "twitch",
            "vods": session_vods,
            "message_count": len(all_messages),
            "messages": all_messages,
        }
        output_path = output_dir / f"{session_number}.json"
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{session_number}: imported {len(all_messages)} Twitch messages from {len(session_vods)} VOD(s)")
        imported += 1

    return imported


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Twitch VOD chat comments into static cache data.")
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0044")
    parser.add_argument("--channel-url", default=DEFAULT_CHANNEL_URL)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--playlist-end", type=int, default=80)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--yt-dlp", default="yt-dlp")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    imported = import_chats(
        channel_url=args.channel_url,
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        selected_numbers=set(args.sessions) if args.sessions else None,
        playlist_end=args.playlist_end,
        force=args.force,
        yt_dlp=args.yt_dlp,
    )
    print(f"imported: {imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
