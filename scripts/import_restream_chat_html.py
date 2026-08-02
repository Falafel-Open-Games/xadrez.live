#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import tomllib
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "restream_chat_replays"


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


def session_data(session_number: str) -> dict:
    path = CONTENT_DIR / f"{session_number}.md"
    if not path.exists():
        fail(f"{path} does not exist")
    return tomllib.loads(extract_front_matter(path.read_text(encoding="utf-8"), path))


def parse_clock_time(value: str) -> tuple[int, int, int] | None:
    parts = value.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        hour, minute, second = [int(part) for part in parts]
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return hour, minute, second


def session_start(data: dict) -> datetime | None:
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return None

    raw_date = str(data.get("date") or "")
    raw_time = str(extra.get("time") or "")
    if not raw_date or not raw_time:
        return None

    try:
        date_value = datetime.strptime(raw_date, "%Y-%m-%d")
    except ValueError:
        return None

    time_parts = raw_time.split(":")
    if len(time_parts) < 2:
        return None
    try:
        hour = int(time_parts[0])
        minute = int(time_parts[1])
    except ValueError:
        return None

    return date_value.replace(hour=hour, minute=minute, second=0, microsecond=0)


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def message_seconds(clock_time: str, start: datetime | None) -> int:
    parsed = parse_clock_time(clock_time)
    if parsed is None or start is None:
        return 0

    hour, minute, second = parsed
    message_time = start.replace(hour=hour, minute=minute, second=second)
    if message_time < start:
        message_time += timedelta(days=1)
    return max(0, round((message_time - start).total_seconds()))


def normalize_author(author: str, platform: str) -> str:
    author = author.strip()
    if platform == "Restream" and author in {"Restream", "Restream.io"}:
        return "Host"
    if platform in {"Twitch", "YouTube"} and author and not author.startswith("@"):
        return f"@{author}"
    return author


def normalize_platform(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return ""
    if "youtube" in normalized or normalized in {"yt", "platform-5"}:
        return "YouTube"
    if "twitch" in normalized or normalized in {"tv", "platform-1"}:
        return "Twitch"
    if "restream" in normalized:
        return "Restream"
    return value.strip()


def detect_platform(image_sources: list[str]) -> str:
    if any("platform-5" in source for source in image_sources):
        return "YouTube"
    if any("platform-1" in source for source in image_sources):
        return "Twitch"
    if any("restream-icon" in source for source in image_sources):
        return "Restream"
    return ""


def flatten_string_values(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(flatten_string_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(flatten_string_values(item))
        return values
    return []


def json_platform(message: dict) -> str:
    platform_fields = (
        "sourcePlatform",
        "source_platform",
        "originPlatform",
        "origin_platform",
        "provider",
        "service",
        "network",
        "platform",
    )
    explicit_platforms = [normalize_platform(str(message.get(field) or "")) for field in platform_fields]
    explicit_platforms = [platform for platform in explicit_platforms if platform]

    image_fields = (
        "images",
        "imageSources",
        "image_sources",
        "icons",
        "icon",
        "platformIcon",
        "platform_icon",
        "platformImage",
        "platform_image",
    )
    image_sources = []
    for field in image_fields:
        image_sources.extend(flatten_string_values(message.get(field)))

    detected_platform = detect_platform(image_sources)
    if detected_platform and detected_platform != "Restream":
        return detected_platform

    for platform in explicit_platforms:
        if platform != "Restream":
            return platform

    return detected_platform or (explicit_platforms[0] if explicit_platforms else "")


class RestreamChatHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[dict] = []
        self.card: dict | None = None
        self.card_depth = 0
        self.capture: str | None = None
        self.capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name: value or "" for name, value in attrs}
        classes = attr.get("class", "")
        is_message_card = (
            tag == "div"
            and (
                attr.get("id", "").startswith("message-card-studio-")
                or "message-item" in classes.split()
            )
            and self.card is None
        )
        if is_message_card:
            self.card = {"author": "", "clock": "", "text": "", "images": []}
            self.card_depth = 1
            self.capture = None
            self.capture_depth = 0
            return

        if self.card is not None:
            if tag == "img" and attr.get("src"):
                self.card["images"].append(attr["src"])
                return

            self.card_depth += 1
            if self.capture is not None:
                self.capture_depth += 1

            if tag == "div" and "MuiTypography-subtitle2" in classes:
                self.capture = "author"
                self.capture_depth = 1
            elif tag == "span" and "message-sender" in classes:
                self.capture = "author"
                self.capture_depth = 1
            elif tag == "p" and "MuiTypography-caption" in classes:
                self.capture = "clock"
                self.capture_depth = 1
            elif tag == "div" and "message-time" in classes:
                self.capture = "clock"
                self.capture_depth = 1
            elif tag == "span" and "chat-text-normal" in classes:
                self.capture = "text"
                self.capture_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.card is None:
            return

        if self.capture is not None:
            self.capture_depth -= 1
            if self.capture_depth <= 0:
                self.capture = None
                self.capture_depth = 0

        self.card_depth -= 1
        if self.card_depth <= 0:
            self.add_card()
            self.card = None
            self.capture = None
            self.capture_depth = 0

    def handle_data(self, data: str) -> None:
        if self.card is None or self.capture is None:
            return
        current = str(self.card.get(self.capture) or "")
        self.card[self.capture] = f"{current}{data}"

    def add_card(self) -> None:
        assert self.card is not None
        author = " ".join(str(self.card.get("author") or "").split())
        clock = " ".join(str(self.card.get("clock") or "").split())
        text = " ".join(html.unescape(str(self.card.get("text") or "")).split())
        images = [str(source) for source in self.card.get("images", [])]
        platform = "Restream" if author in {"Restream", "Restream.io"} else detect_platform(images)

        if not author or not clock or not text:
            return
        if platform == "Restream" and author in {"Restream", "Restream.io"} and text in {
            "Read & reply to messages from multiple platforms here.",
            "The chat is ready to display messages.",
        }:
            return

        self.messages.append(
            {
                "clock": clock,
                "platform": platform,
                "channel": "",
                "author": normalize_author(author, platform),
                "text": text,
            }
        )


def parse_html(content: str) -> list[dict]:
    parser = RestreamChatHTMLParser()
    parser.feed(content)
    parser.close()
    return parser.messages


def read_input(path: str) -> str:
    if path == "-":
        import sys

        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def parse_input(content: str) -> list[dict]:
    stripped = content.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(content)
        messages = data.get("messages") if isinstance(data, dict) else data
        if not isinstance(messages, list):
            fail("JSON input must be a list or an object with a messages list")
        return [message for message in messages if isinstance(message, dict)]
    return parse_html(content)


def build_output(session_number: str, content: str) -> dict:
    data = session_data(session_number)
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    start = session_start(data)
    youtube_id = str(extra.get("youtube_video_id") or "")

    messages = []
    for parsed in parse_input(content):
        parsed = dict(parsed)
        clock = str(parsed.pop("clock", "") or "")
        seconds = int(parsed.pop("seconds", 0) or 0) if not clock else message_seconds(clock, start)
        text = str(parsed.get("text") or "").strip()
        author = str(parsed.get("author") or "").strip()
        platform = json_platform(parsed)
        if not text or not author:
            continue
        messages.append(
            {
                "time": format_time(seconds),
                "seconds": seconds,
                "platform": platform,
                "channel": str(parsed.get("channel") or ""),
                "author": normalize_author(author, platform),
                "text": text,
            }
        )

    messages = sorted(messages, key=lambda message: int(message["seconds"]))
    platforms = sorted({message["platform"] for message in messages if message.get("platform")})
    return {
        "session_number": session_number,
        "youtube_video_id": youtube_id,
        "source": "restream-html",
        "platforms": platforms,
        "message_count": len(messages),
        "messages": messages,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import pasted Restream chat HTML or userscript JSON into session chat replay data.")
    parser.add_argument("session", help="Session number, e.g. 0047")
    parser.add_argument("input_file", help="HTML/JSON file to import, or - for stdin")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = build_output(args.session, read_input(args.input_file))
    if not output["messages"]:
        fail("no Restream chat messages found in HTML")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{args.session}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{args.session}: imported {output['message_count']} Restream HTML messages "
        f"from {', '.join(output['platforms']) or 'unknown platform'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
