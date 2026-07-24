#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data/external_stream_sources.toml"
STREAMER_URL = "https://lichess.org/streamer"
USER_AGENT = "Mozilla/5.0"


@dataclass
class Streamer:
    display: str = ""
    language: str = ""
    headline: str = ""
    services: list[str] = field(default_factory=list)
    profile_url: str = ""
    live: bool = False
    currently_streaming: str = ""
    active_at: str = ""
    last_stream_at: str = ""


class StreamerParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.streamers: list[Streamer] = []
        self.next_url = ""
        self.current: Streamer | None = None
        self.capture = ""
        self.in_activity = False
        self.activity_label = ""

    def handle_starttag(self, tag: str, attrs_raw: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_raw}
        classes = attrs.get("class", "").split()

        if tag == "article" and "streamer" in classes:
            self.current = Streamer()
            return

        if tag == "a" and "next" in attrs.get("rel", "").split():
            self.next_url = urljoin(STREAMER_URL, html.unescape(attrs.get("href", "")))

        if self.current is None:
            return

        if tag == "span" and "live-ribbon" in classes:
            self.current.live = True
        elif tag == "h1":
            self.capture = "display"
        elif tag == "span" and "streamer-lang" in classes:
            self.capture = "language"
        elif tag == "p" and "headline" in classes:
            self.capture = "headline"
        elif tag == "div" and "service" in classes:
            self.capture = "service"
        elif tag == "p" and "at" in classes:
            self.capture = "activity"
            self.in_activity = True
            self.activity_label = ""
        elif tag == "a" and "user-link" in classes:
            self.current.profile_url = urljoin(STREAMER_URL, html.unescape(attrs.get("href", "")))
        elif tag == "time" and self.in_activity:
            timestamp = html.unescape(attrs.get("datetime", ""))
            if "Last stream" in self.activity_label:
                self.current.last_stream_at = timestamp
            elif "Active" in self.activity_label:
                self.current.active_at = timestamp

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self.current is not None:
            self.streamers.append(self.current)
            self.current = None
            self.capture = ""
            self.in_activity = False
            self.activity_label = ""
            return

        if tag == "p" and self.in_activity:
            self.in_activity = False
            self.activity_label = ""

        if self.capture and tag in {"h1", "span", "p", "div", "a"}:
            self.capture = ""

    def handle_data(self, raw_data: str) -> None:
        if self.current is None or not self.capture:
            return

        text = " ".join(html.unescape(raw_data).split())
        if not text:
            return

        if self.capture == "service":
            self.current.services.append(text)
        elif self.capture == "activity":
            self.activity_label = append_text(self.activity_label, text)
            if "Currently streaming:" in text:
                text = text.split("Currently streaming:", 1)[1].strip()
            if text and "Currently streaming:" not in self.activity_label:
                self.current.currently_streaming = append_text(self.current.currently_streaming, text)
        else:
            current = getattr(self.current, self.capture)
            setattr(self.current, self.capture, append_text(current, text))


def append_text(left: str, right: str) -> str:
    return f"{left} {right}".strip() if left else right.strip()


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except URLError as error:
        fail(f"failed to fetch {url}: {error}")


def parse_streamers(markup: str) -> tuple[list[Streamer], str]:
    parser = StreamerParser()
    parser.feed(markup)
    return parser.streamers, parser.next_url


def load_streamers(max_pages: int) -> list[Streamer]:
    url = STREAMER_URL
    seen_urls: set[str] = set()
    streamers: list[Streamer] = []

    for _page in range(max_pages):
        if not url or url in seen_urls:
            break
        seen_urls.add(url)
        page_streamers, next_url = parse_streamers(fetch_text(url))
        if not page_streamers:
            break
        streamers.extend(page_streamers)
        url = next_url

    return dedupe_streamers(streamers)


def dedupe_streamers(streamers: list[Streamer]) -> list[Streamer]:
    deduped: dict[str, Streamer] = {}
    for streamer in streamers:
        key = (streamer.profile_url or streamer.display).lower()
        if key and key not in deduped:
            deduped[key] = streamer
    return list(deduped.values())


def lichess_user(streamer: Streamer) -> str:
    path = urlparse(streamer.profile_url).path.rstrip("/")
    if "/@/" in path:
        return path.rsplit("/@/", 1)[1]
    return path.rsplit("/", 1)[-1] or streamer.display


def service_url(service: str) -> str:
    service = service.strip()
    if not service:
        return ""
    if service.startswith(("http://", "https://")):
        return service
    return "https://" + service


def youtube_streams_url(service: str) -> str:
    url = service_url(service)
    if not url:
        return ""
    parsed = urlparse(url)
    if "youtube.com" not in parsed.netloc.lower():
        return ""
    if parsed.path.endswith("/live"):
        return url[:-len("/live")] + "/streams"
    return url


def service_matches(service: str, wanted: str) -> bool:
    service = service.lower()
    if wanted == "youtube":
        return "youtube.com/" in service or "youtu.be/" in service
    if wanted == "twitch":
        return "twitch.tv/" in service
    return True


def language_matches(language: str, wanted: str) -> bool:
    if not wanted or wanted.lower() == "all":
        return True
    language = language.lower()
    wanted = wanted.lower()
    aliases = {
        "pt": ("portugu",),
        "pt-br": ("portugu", "br"),
        "en": ("english",),
        "es": ("espanol", "español"),
    }
    terms = aliases.get(wanted, (wanted,))
    return all(term in language for term in terms)


def cyrillic_ratio(value: str) -> float:
    letters = [char for char in value if char.isalpha()]
    if not letters:
        return 0.0
    cyrillic = [char for char in letters if "\u0400" <= char <= "\u04ff"]
    return len(cyrillic) / len(letters)


def content_matches_language(row: dict[str, str], wanted: str) -> bool:
    wanted = wanted.lower()
    if wanted not in ("en", "english"):
        return True

    text = " ".join(
        [
            row["latest_video_title"],
            row["display"],
            row["headline"],
        ]
    )
    return cyrillic_ratio(text) < 0.35


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def days_since(value: str) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return ""
    now = datetime.now(timezone.utc)
    return str(max(0, (now - parsed).days))


def load_existing_source_text() -> str:
    if not SOURCES.exists():
        return ""
    return SOURCES.read_text(encoding="utf-8").lower()


def latest_video(source_url: str) -> tuple[str, str]:
    if not source_url:
        return "", ""

    command = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-end",
        "1",
        "--dump-json",
        source_url,
    ]
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        return "", ""

    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        video_id = str(item.get("id") or "").strip()
        url = str(item.get("url") or item.get("webpage_url") or "").strip()
        if video_id and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={video_id}"
        title = str(item.get("title") or "").strip()
        return url, title
    return "", ""


def already_listed(services: list[str], existing_text: str) -> bool:
    normalized = existing_text.replace("https://www.", "https://").replace("http://www.", "http://")
    for service in services:
        candidates = {service_url(service), youtube_streams_url(service)}
        for candidate in candidates:
            if not candidate:
                continue
            lowered = candidate.lower().replace("https://www.", "https://").replace("http://www.", "http://")
            if lowered in normalized:
                return True
    return False


def format_row(
    streamer: Streamer,
    services: list[str],
    existing_text: str,
    include_latest_video: bool,
) -> dict[str, str]:
    youtube_sources = [youtube_streams_url(service) for service in services if youtube_streams_url(service)]
    latest_url = ""
    latest_title = ""
    if include_latest_video and youtube_sources:
        latest_url, latest_title = latest_video(youtube_sources[0])

    return {
        "days_since_last": days_since(streamer.last_stream_at),
        "language": streamer.language,
        "listed": "yes" if already_listed(services, existing_text) else "no",
        "lichess": lichess_user(streamer),
        "display": streamer.display,
        "services": ", ".join(service_url(service) for service in services),
        "source_urls": ", ".join(youtube_sources),
        "latest_video_url": latest_url,
        "latest_video_title": latest_title,
        "profile": streamer.profile_url,
        "headline": streamer.headline,
    }


def sort_key(row: dict[str, str]) -> tuple[int, str, str]:
    days = row["days_since_last"]
    return (int(days) if days.isdigit() else 99999, row["language"].lower(), row["lichess"].lower())


def print_tsv(rows: list[dict[str, str]]) -> None:
    keys = (
        "days_since_last",
        "language",
        "listed",
        "lichess",
        "display",
        "services",
        "source_urls",
        "latest_video_url",
        "latest_video_title",
        "profile",
        "headline",
    )
    print("\t".join(keys))
    for row in rows:
        print("\t".join(row[key] for key in keys))


def print_markdown(rows: list[dict[str, str]]) -> None:
    print("| Last stream days | Lang | Listed | Lichess | Display | Latest video | Source URL |")
    print("|---:|---|---|---|---|---|---|")
    for row in rows:
        source_url = row["source_urls"] or row["services"]
        latest_video_link = ""
        if row["latest_video_url"]:
            latest_label = row["latest_video_title"] or "watch"
            latest_video_link = f"[{escape_markdown_table(latest_label)}]({row['latest_video_url']})"
        print(
            "| "
            + " | ".join(
                [
                    row["days_since_last"] or "",
                    row["language"],
                    row["listed"],
                    row["lichess"],
                    row["display"],
                    latest_video_link,
                    source_url,
                ]
            )
            + " |"
        )


def escape_markdown_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover Lichess streamer directory entries for manual external-feed review."
    )
    parser.add_argument("--language", default="all", help="language filter: all, pt-BR, pt, en, es, or text match")
    parser.add_argument("--service", choices=("youtube", "twitch", "all"), default="youtube")
    parser.add_argument("--format", choices=("tsv", "markdown"), default="markdown")
    parser.add_argument("--limit-pages", type=int, default=80)
    parser.add_argument("--latest-video", action="store_true", help="probe each YouTube channel for its latest stream/video")
    parser.add_argument("--include-listed", action="store_true", help="include channels already present in external_stream_sources.toml")
    args = parser.parse_args()

    existing_text = load_existing_source_text()
    rows = []
    for streamer in load_streamers(args.limit_pages):
        if not language_matches(streamer.language, args.language):
            continue
        services = [service for service in streamer.services if service_matches(service, args.service)]
        if not services:
            continue
        row = format_row(streamer, services, existing_text, args.latest_video)
        if args.latest_video and not row["latest_video_url"]:
            continue
        if not content_matches_language(row, args.language):
            continue
        if not args.include_listed and row["listed"] == "yes":
            continue
        rows.append(row)

    rows.sort(key=sort_key)
    if args.format == "tsv":
        print_tsv(rows)
    else:
        print_markdown(rows)


if __name__ == "__main__":
    main()
