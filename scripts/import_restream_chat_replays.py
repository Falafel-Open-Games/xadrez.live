#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DEFAULT_CACHE_DIR = Path("/tmp/xadrez-restream-chat")
DEFAULT_OUTPUT_DIR = ROOT / "data" / "fcz" / "restream_chat_replays"
DEFAULT_YOUTUBE_CACHE_DIR = Path("/tmp/xadrez-chat")
DEFAULT_TWITCH_DATA_DIR = ROOT / "data" / "fcz" / "twitch_chat_replays"
ENV_PATH = ROOT / ".env"
API_BASE = "https://api.restream.io/v2"
TOKEN_URL = "https://api.restream.io/oauth/token"
YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/|youtube\.com/live/|embed/)([A-Za-z0-9_-]{11})")
ANON_AUTHOR_RE = re.compile(r"^Person \d+$")


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        method="POST",
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "xadrez-live-restream-importer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body_text = error.read().decode("utf-8", errors="replace")
        if error.code == 401:
            raise RuntimeError("Restream token refresh failed: refresh token is unauthorized or expired") from error
        raise RuntimeError(f"Restream token refresh failed with HTTP {error.code}: {body_text}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Restream token refresh failed: {error.reason}") from error

    token = str(data.get("access_token") or data.get("accessToken") or "")
    if not token:
        raise RuntimeError("Restream token refresh response did not include an access token")
    return token


def restream_token(cli_token: str) -> str:
    if cli_token:
        return cli_token

    refresh_token = env_value("RESTREAM_REFRESH_TOKEN")
    client_id = env_value("RESTREAM_CLIENT_ID", "RESTREAM_API_CLIENT_ID")
    client_secret = env_value("RESTREAM_CLIENT_SECRET", "RESTREAM_API_CLIENT_SECRET")
    if refresh_token and client_id and client_secret:
        return refresh_access_token(client_id, client_secret, refresh_token)

    token = env_value("RESTREAM_ACCESS_TOKEN")
    if token:
        return token

    return ""


def extract_front_matter(text: str, path: Path) -> str:
    if not text.startswith("+++"):
        fail(f"missing TOML front matter in {path}")

    marker = "\n+++"
    end = text.find(marker, 3)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")

    return text[3:end].strip()


def youtube_supporter_names(extra: dict[str, Any]) -> list[str]:
    names = []
    for supporter in extra.get("supporters", []):
        if not isinstance(supporter, dict):
            continue
        platform = str(supporter.get("platform") or "").strip().lower()
        name = str(supporter.get("name") or "").strip()
        if platform == "youtube" and name:
            names.append(name)
    return names


def session_youtube_ids(min_session: int) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        if int(path.stem) < min_session:
            continue

        data = tomllib.loads(extract_front_matter(path.read_text(encoding="utf-8"), path))
        extra = data.get("extra")
        if not isinstance(extra, dict):
            continue

        youtube_id = str(extra.get("youtube_video_id") or "").strip()
        status = str(extra.get("status") or "").strip().lower()
        status_tone = str(extra.get("status_tone") or "").strip().lower()
        is_ended = status == "encerrada" or status_tone in {"ended", "completed"}
        if youtube_id and youtube_id != "REPLACE_WITH_YOUTUBE_VIDEO_ID" and is_ended:
            sessions.append(
                {
                    "session_number": path.stem,
                    "youtube_video_id": youtube_id,
                    "title": str(data.get("title") or ""),
                    "date": str(data.get("date") or ""),
                    "chat_author_aliases": extra.get("chat_author_aliases") if isinstance(extra.get("chat_author_aliases"), dict) else {},
                    "youtube_supporters": youtube_supporter_names(extra),
                }
            )

    return sessions


def selected_sessions(all_sessions: list[dict[str, str]], numbers: set[str] | None, latest: int | None) -> list[dict[str, str]]:
    sessions = all_sessions
    if numbers is not None:
        sessions = [session for session in sessions if session["session_number"] in numbers]
    elif latest is not None and latest > 0:
        sessions = sessions[-latest:]
    return sessions


def request_json(url: str, token: str, method: str = "GET") -> Any:
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "xadrez-live-restream-importer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        if error.code == 401:
            raise RuntimeError("Restream access token is unauthorized or expired; run `just restream-refresh-token`") from error
        raise RuntimeError(f"{method} {url} failed with HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"{method} {url} failed: {error.reason}") from error


def cache_path(cache_dir: Path, name: str) -> Path:
    return cache_dir / name


def fetch_events_history(token: str, cache_dir: Path, force: bool, limit: int) -> list[dict]:
    path = cache_path(cache_dir, "events-history.json")
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))

    cache_dir.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"page": page, "limit": limit})
        data = request_json(f"{API_BASE}/user/events/history?{query}", token)
        items = data.get("items")
        if not isinstance(items, list):
            break
        events.extend(item for item in items if isinstance(item, dict))

        pagination = data.get("pagination") if isinstance(data, dict) else None
        pages_total = int(pagination.get("pages_total") or page) if isinstance(pagination, dict) else page
        if page >= pages_total:
            break
        page += 1

    path.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return events


def youtube_ids_from_event(event: dict) -> set[str]:
    ids: set[str] = set()
    for destination in event.get("destinations") or []:
        if not isinstance(destination, dict):
            continue
        external_url = str(destination.get("externalUrl") or "")
        ids.update(YOUTUBE_ID_RE.findall(external_url))
    return ids


def index_events_by_youtube_id(events: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for event in events:
        for youtube_id in youtube_ids_from_event(event):
            indexed[youtube_id] = event
    return indexed


def fetch_chat_history(token: str, event_id: str, cache_dir: Path, force: bool) -> list[dict]:
    path = cache_path(cache_dir, f"{event_id}.chat-history.json")
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))

    messages: list[dict] = []
    page_token = ""
    while True:
        query = {"pageSize": "1000"}
        if page_token:
            query["pageToken"] = page_token
        url = f"{API_BASE}/user/events/{event_id}/chat/history?{urllib.parse.urlencode(query)}"
        data = request_json(url, token)
        page_messages = data.get("messages")
        if isinstance(page_messages, list):
            messages.extend(message for message in page_messages if isinstance(message, dict))

        page_token = str(data.get("nextPageToken") or "")
        if not page_token:
            break

    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return messages


def parse_timestamp(timestamp: str) -> datetime | None:
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


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
            image = emoji.get("image")
            accessibility = image.get("accessibility") if isinstance(image, dict) else None
            accessibility_data = accessibility.get("accessibilityData") if isinstance(accessibility, dict) else None
            label = accessibility_data.get("label") if isinstance(accessibility_data, dict) else None
            if label:
                chunks.append(str(label))
                continue

            shortcuts = emoji.get("shortcuts")
            if isinstance(shortcuts, list) and shortcuts:
                chunks.append(str(shortcuts[0]))
            elif emoji.get("emojiId"):
                chunks.append(str(emoji["emojiId"]))

    return "".join(chunks).strip()


def youtube_renderer_message(renderer: dict) -> str:
    message = renderer.get("message")
    if not isinstance(message, dict):
        return ""

    runs = message.get("runs")
    if isinstance(runs, list):
        return runs_text(runs)

    simple_text = message.get("simpleText")
    return str(simple_text).strip() if simple_text else ""


def youtube_text_message_renderer(action: dict) -> dict | None:
    item = action.get("addChatItemAction", {}).get("item", {})
    renderer = item.get("liveChatTextMessageRenderer")
    return renderer if isinstance(renderer, dict) else None


def parse_youtube_chat(chat_path: Path) -> list[dict]:
    messages = []
    if not chat_path.exists():
        return messages

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

            renderer = youtube_text_message_renderer(action)
            if not renderer:
                continue

            author = renderer.get("authorName", {}).get("simpleText")
            text = youtube_renderer_message(renderer)
            if not author or not text:
                continue

            offset_ms = int(item.get("replayChatItemAction", {}).get("videoOffsetTimeMsec") or 0)
            messages.append(
                {
                    "seconds": max(0, round(offset_ms / 1000)),
                    "author": str(author),
                    "text": text,
                }
            )

    return messages


def youtube_author_lookups(messages: list[dict], max_delta_seconds: int) -> tuple[dict[tuple[str, int], str], dict[str, str]]:
    timed_lookup = {}
    text_authors: dict[str, set[str]] = {}
    for message in messages:
        text = str(message.get("text") or "")
        seconds = int(message.get("seconds") or 0)
        author = str(message.get("author") or "")
        if not text or not author:
            continue
        text_authors.setdefault(text, set()).add(author)
        for delta in range(-max_delta_seconds, max_delta_seconds + 1):
            timed_lookup.setdefault((text, seconds + delta), author)

    text_lookup = {
        text: next(iter(authors))
        for text, authors in text_authors.items()
        if len(authors) == 1
    }
    return timed_lookup, text_lookup


def load_static_chat_messages(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = data.get("messages")
    return messages if isinstance(messages, list) else []


def event_start(event: dict) -> datetime | None:
    raw_started_at = event.get("startedAt") or event.get("scheduledFor")
    if raw_started_at is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw_started_at), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def normalize_messages(
    raw_messages: list[dict],
    event: dict,
    author_aliases: dict[str, str],
    youtube_timed_authors: dict[tuple[str, int], str],
    youtube_text_authors: dict[str, str],
    twitch_timed_authors: dict[tuple[str, int], str],
    twitch_text_authors: dict[str, str],
) -> list[dict]:
    start = event_start(event)
    normalized = []
    for raw in raw_messages:
        text = str(raw.get("text") or "").strip()
        author = str(raw.get("author") or "").strip()
        if not text or not author:
            continue

        message_time = parse_timestamp(str(raw.get("timestamp") or ""))
        seconds = 0
        if start and message_time:
            seconds = max(0, round((message_time - start).total_seconds()))

        platform = str(raw.get("platform") or "").strip()
        channel = str(raw.get("channelName") or "").strip()
        if platform == "YouTube" and ANON_AUTHOR_RE.match(author):
            author = youtube_timed_authors.get((text, seconds), youtube_text_authors.get(text, author))
        if platform == "Twitch" and ANON_AUTHOR_RE.match(author):
            author = twitch_timed_authors.get((text, seconds), twitch_text_authors.get(text, author))
        author = str(author_aliases.get(author) or author)
        normalized.append(
            {
                "time": format_time(seconds),
                "seconds": seconds,
                "platform": platform,
                "channel": channel,
                "author": author,
                "text": text,
            }
        )

    return sorted(normalized, key=lambda message: int(message["seconds"]))


def infer_single_youtube_supporter_alias(
    raw_messages: list[dict],
    event: dict,
    author_aliases: dict[str, str],
    youtube_timed_authors: dict[tuple[str, int], str],
    youtube_text_authors: dict[str, str],
    youtube_supporters: list[str],
) -> dict[str, str]:
    aliases = dict(author_aliases)
    unresolved_authors: set[str] = set()
    resolved_authors = set(youtube_timed_authors.values()) | set(youtube_text_authors.values()) | set(aliases.values())
    start = event_start(event)

    for raw in raw_messages:
        if str(raw.get("platform") or "").strip() != "YouTube":
            continue

        author = str(raw.get("author") or "").strip()
        text = str(raw.get("text") or "").strip()
        if not text or not ANON_AUTHOR_RE.match(author) or author in aliases:
            continue

        seconds = 0
        message_time = parse_timestamp(str(raw.get("timestamp") or ""))
        if start and message_time:
            seconds = max(0, round((message_time - start).total_seconds()))

        if youtube_timed_authors.get((text, seconds)) or youtube_text_authors.get(text):
            continue
        unresolved_authors.add(author)

    candidate_supporters = [name for name in youtube_supporters if name not in resolved_authors]
    if len(unresolved_authors) == 1 and len(candidate_supporters) == 1:
        aliases[next(iter(unresolved_authors))] = candidate_supporters[0]
    return aliases


def import_replays(
    token: str,
    cache_dir: Path,
    output_dir: Path,
    selected_numbers: set[str] | None,
    latest: int | None,
    min_session: int,
    force: bool,
    history_limit: int,
    youtube_cache_dir: Path,
    twitch_data_dir: Path,
    youtube_match_window: int,
) -> int:
    sessions = selected_sessions(session_youtube_ids(min_session), selected_numbers, latest)
    events = fetch_events_history(token, cache_dir, force, history_limit)
    events_by_youtube_id = index_events_by_youtube_id(events)
    output_dir.mkdir(parents=True, exist_ok=True)
    imported = 0

    for session in sessions:
        youtube_id = session["youtube_video_id"]
        event = events_by_youtube_id.get(youtube_id)
        if not event:
            print(f"{session['session_number']}: no Restream event matched YouTube id {youtube_id}")
            continue

        event_id = str(event.get("id") or "").strip()
        if not event_id:
            print(f"{session['session_number']}: matched Restream event has no id")
            continue

        try:
            raw_messages = fetch_chat_history(token, event_id, cache_dir, force)
        except RuntimeError as error:
            print(f"{session['session_number']}: Restream chat unavailable ({error})")
            continue

        aliases = session.get("chat_author_aliases")
        youtube_messages = parse_youtube_chat(youtube_cache_dir / f"{youtube_id}.live_chat.json")
        youtube_timed_authors, youtube_text_authors = youtube_author_lookups(youtube_messages, youtube_match_window)
        twitch_messages = load_static_chat_messages(twitch_data_dir / f"{session['session_number']}.json")
        twitch_timed_authors, twitch_text_authors = youtube_author_lookups(twitch_messages, youtube_match_window)
        aliases = infer_single_youtube_supporter_alias(
            raw_messages,
            event,
            aliases if isinstance(aliases, dict) else {},
            youtube_timed_authors,
            youtube_text_authors,
            session.get("youtube_supporters", []),
        )
        messages = normalize_messages(
            raw_messages,
            event,
            aliases,
            youtube_timed_authors,
            youtube_text_authors,
            twitch_timed_authors,
            twitch_text_authors,
        )
        if not messages:
            print(f"{session['session_number']}: Restream event {event_id} has no chat messages")
            continue

        platforms = sorted({message["platform"] for message in messages if message.get("platform")})
        output = {
            "session_number": session["session_number"],
            "youtube_video_id": youtube_id,
            "restream_event_id": event_id,
            "source": "restream",
            "platforms": platforms,
            "message_count": len(messages),
            "messages": messages,
        }
        output_path = output_dir / f"{session['session_number']}.json"
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            f"{session['session_number']}: imported {len(messages)} Restream messages "
            f"from {', '.join(platforms) or 'unknown platform'}"
        )
        imported += 1

    return imported


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Restream aggregated chat history into static session chat replay data."
    )
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0015")
    parser.add_argument("--token", default="")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--latest", type=int, help="Only process the latest N ended sessions.")
    parser.add_argument("--min-session", type=int, default=15)
    parser.add_argument("--force", action="store_true", help="Refresh cached Restream event and chat responses.")
    parser.add_argument("--history-limit", type=int, default=100)
    parser.add_argument("--youtube-cache-dir", type=Path, default=DEFAULT_YOUTUBE_CACHE_DIR)
    parser.add_argument("--twitch-data-dir", type=Path, default=DEFAULT_TWITCH_DATA_DIR)
    parser.add_argument("--youtube-match-window", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    load_env_file(ENV_PATH)
    args = parse_args()
    try:
        token = restream_token(args.token)
    except RuntimeError as error:
        print(f"Restream chat unavailable ({error})")
        return 1
    if not token:
        fail("set RESTREAM_ACCESS_TOKEN or RESTREAM_REFRESH_TOKEN in .env, or pass --token")

    selected_numbers = set(args.sessions) if args.sessions else None
    try:
        imported = import_replays(
            token=token,
            cache_dir=args.cache_dir,
            output_dir=args.output_dir,
            selected_numbers=selected_numbers,
            latest=args.latest,
            min_session=args.min_session,
            force=args.force,
            history_limit=args.history_limit,
            youtube_cache_dir=args.youtube_cache_dir,
            twitch_data_dir=args.twitch_data_dir,
            youtube_match_window=args.youtube_match_window,
        )
    except RuntimeError as error:
        print(f"Restream chat unavailable ({error})")
        return 1
    print(f"imported: {imported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
