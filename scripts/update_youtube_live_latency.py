#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from update_youtube_chapters import ENV_PATH, access_token, api_request, env_value, load_env_file


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
LATENCIES = {"normal", "low", "ultraLow"}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        fail(f"missing TOML front matter in {path}")
    end = text.find("\n+++", 4)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")
    return tomllib.loads(text[4:end])


def youtube_video_id(session: str) -> str:
    path = CONTENT_DIR / f"{session}.md"
    if not path.exists():
        fail(f"session not found: {path}")
    data = read_front_matter(path)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        fail(f"missing [extra] in {path}")
    video_id = str(extra.get("youtube_video_id") or "").strip()
    if not video_id or video_id == "REPLACE_WITH_YOUTUBE_VIDEO_ID":
        fail(f"{session}: youtube_video_id is not configured")
    return video_id


def youtube_token() -> str:
    client_id = env_value("YOUTUBE_CLIENT_ID")
    client_secret = env_value("YOUTUBE_CLIENT_SECRET")
    refresh_token = env_value("YOUTUBE_REFRESH_TOKEN")
    if not client_id or not client_secret or not refresh_token:
        fail("set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN in .env")
    return access_token(client_id, client_secret, refresh_token)


def fetch_broadcast(token: str, video_id: str) -> dict[str, Any]:
    data = api_request(
        "liveBroadcasts",
        token,
        query={"part": "snippet,contentDetails,status", "id": video_id},
    )
    items = data.get("items")
    if not isinstance(items, list) or not items:
        fail(f"YouTube live broadcast not found for video id {video_id}")
    broadcast = items[0]
    if not isinstance(broadcast, dict):
        fail(f"unexpected liveBroadcast response for video id {video_id}")
    return broadcast


def update_body(broadcast: dict[str, Any], latency: str) -> dict[str, Any]:
    broadcast_id = str(broadcast.get("id") or "").strip()
    snippet = broadcast.get("snippet")
    content_details = broadcast.get("contentDetails")
    if not broadcast_id:
        fail("liveBroadcast response did not include id")
    if not isinstance(snippet, dict):
        fail(f"{broadcast_id}: liveBroadcast response did not include snippet")
    if not isinstance(content_details, dict):
        fail(f"{broadcast_id}: liveBroadcast response did not include contentDetails")

    scheduled_start = str(snippet.get("scheduledStartTime") or "").strip()
    title = str(snippet.get("title") or "").strip()
    if not scheduled_start:
        fail(f"{broadcast_id}: liveBroadcast snippet is missing scheduledStartTime")
    if not title:
        fail(f"{broadcast_id}: liveBroadcast snippet is missing title")

    output_snippet: dict[str, Any] = {
        "title": title,
        "scheduledStartTime": scheduled_start,
    }
    for key in ("description", "scheduledEndTime"):
        if key in snippet:
            output_snippet[key] = snippet[key]

    output_content_details = copy.deepcopy(content_details)
    monitor_stream = output_content_details.setdefault("monitorStream", {})
    if not isinstance(monitor_stream, dict):
        fail(f"{broadcast_id}: contentDetails.monitorStream is not an object")
    monitor_stream.setdefault("enableMonitorStream", True)
    monitor_stream.setdefault("broadcastStreamDelayMs", 0)
    output_content_details["latencyPreference"] = latency
    output_content_details.pop("enableLowLatency", None)

    return {
        "id": broadcast_id,
        "snippet": output_snippet,
        "contentDetails": output_content_details,
    }


def live_chat_note(broadcast: dict[str, Any]) -> str:
    snippet = broadcast.get("snippet")
    status = broadcast.get("status")
    live_chat_id = str(snippet.get("liveChatId") or "").strip() if isinstance(snippet, dict) else ""
    made_for_kids = bool(status.get("madeForKids")) if isinstance(status, dict) else False
    if made_for_kids:
        return "live chat unavailable: made for kids"
    if live_chat_id:
        return "live chat present; replay setting is not exposed by API"
    return "live chat id not returned; verify chat/replay in Studio"


def youtube_error_reason(error: RuntimeError) -> str:
    match = re.search(r"YouTube API request failed with HTTP \d+:\s*(\{.*\})", str(error), re.S)
    if not match:
        return ""
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ""
    errors = data.get("error", {}).get("errors", [])
    if not isinstance(errors, list):
        return ""
    for item in errors:
        if isinstance(item, dict) and item.get("reason"):
            return str(item["reason"])
    return ""


def set_latency(token: str, video_id: str, latency: str, write: bool) -> int:
    broadcast = fetch_broadcast(token, video_id)
    current = str((broadcast.get("contentDetails") or {}).get("latencyPreference") or "")
    status = str((broadcast.get("status") or {}).get("lifeCycleStatus") or "unknown")
    chat_note = live_chat_note(broadcast)
    if current == latency:
        print(f"{video_id}: live latency already {latency} (status: {status}; {chat_note})")
        return 0

    body = update_body(broadcast, latency)
    if not write:
        print(f"{video_id}: would update live latency {current or 'unknown'} -> {latency} (status: {status}; {chat_note})")
        return 0

    try:
        api_request(
            "liveBroadcasts",
            token,
            method="PUT",
            query={"part": "snippet,contentDetails"},
            body=body,
        )
    except RuntimeError as error:
        reason = youtube_error_reason(error)
        if reason == "MODIFICATION_NOT_ALLOWED":
            print(
                f"{video_id}: live latency not changed; YouTube does not allow modifying this broadcast "
                f"now (status: {status}; current: {current or 'unknown'}; wanted: {latency}; {chat_note})"
            )
            return 0
        fail(str(error))
    print(f"{video_id}: updated live latency {current or 'unknown'} -> {latency} (status: {status}; {chat_note})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the latency preference for a scheduled YouTube live broadcast.")
    parser.add_argument("session", help="Session number, e.g. 0061")
    parser.add_argument("--latency", choices=sorted(LATENCIES), default="ultraLow")
    parser.add_argument("--write", action="store_true", help="Actually update YouTube. Without this, print a dry-run.")
    args = parser.parse_args()

    load_env_file(ENV_PATH)
    session = args.session.zfill(4)
    video_id = youtube_video_id(session)
    return set_latency(youtube_token(), video_id, args.latency, args.write)


if __name__ == "__main__":
    raise SystemExit(main())
