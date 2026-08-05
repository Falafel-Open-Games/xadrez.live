#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
OUTPUT = ROOT / "data" / "supporters.toml"
SELF_SUPPORTERS = {
    ("youtube", "fczuardi"),
    ("twitch", "sedentarismo"),
}
SELF_SUPPORTER_HANDLES = {handle for _platform, handle in SELF_SUPPORTERS}
BLOCKED_SUPPORTER_HANDLES = {
    "gsgsgehwge",
}


@dataclass
class Supporter:
    name: str
    url: str = ""
    sessions: set[str] = field(default_factory=set)
    platforms: set[str] = field(default_factory=set)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def acknowledgement_section(text: str) -> str:
    heading = re.search(r"(?m)^## Agradecimentos\s*$", text)
    if not heading:
        return ""

    start = heading.end()
    next_heading = re.search(r"(?m)^## ", text[start:])
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def front_matter_extra(text: str) -> dict:
    if not text.startswith("+++\n"):
        return {}

    end = text.find("\n+++", 4)
    if end == -1:
        return {}

    try:
        data = tomllib.loads(text[4:end])
    except tomllib.TOMLDecodeError:
        return {}

    extra = data.get("extra")
    return extra if isinstance(extra, dict) else {}


def split_people(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def inferred_url(platform: str, name: str) -> str:
    handle = name[1:] if name.startswith("@") else name
    if not handle:
        return ""

    platform = platform.strip().lower()
    if platform == "twitch":
        return f"https://www.twitch.tv/{handle}"
    if platform == "lichess":
        return f"https://lichess.org/@/{handle}"
    if platform == "youtube":
        return f"https://www.youtube.com/@{handle}"
    return ""


def parse_person(raw: str, platform: str = "") -> tuple[str, str]:
    link = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", raw)
    if link:
        return link.group(1).strip(), link.group(2).strip()

    bare_url = re.fullmatch(r"<([^>]+)>", raw)
    if bare_url:
        url = bare_url.group(1).strip()
        return url.rstrip("/").rsplit("/", 1)[-1], url

    name = raw.strip()
    return name, inferred_url(platform, name)


def platform_key(platform: str, name: str, url: str) -> str:
    platform = platform.strip()
    if platform:
        return platform
    if "youtube.com" in url:
        return "YouTube"
    if "lichess.org" in url:
        return "Lichess"
    if "chess.com" in url:
        return "Chess.com"
    if name.startswith("@"):
        return "Chat"
    return "Geral"


def normalized_handle(name: str) -> str:
    return name.removeprefix("@").strip().lower()


def normalized_platform(platform: str, url: str) -> str:
    value = platform.strip().lower()
    if value:
        return value
    if "youtube.com" in url.lower():
        return "youtube"
    if "twitch.tv" in url.lower():
        return "twitch"
    return ""


def is_self_supporter(platform: str, name: str, url: str) -> bool:
    handle = normalized_handle(name)
    return (normalized_platform(platform, url), handle) in SELF_SUPPORTERS or handle in SELF_SUPPORTER_HANDLES


def is_blocked_supporter(name: str) -> bool:
    return normalized_handle(name) in BLOCKED_SUPPORTER_HANDLES


def supporter_key(name: str, url: str) -> str:
    if url:
        return url.lower().rstrip("/")
    return name.lower()


def collect_supporters() -> dict[str, Supporter]:
    supporters: dict[str, Supporter] = {}

    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        text = path.read_text(encoding="utf-8")
        extra = front_matter_extra(text)

        for raw_supporter in extra.get("supporters", []):
            if not isinstance(raw_supporter, dict):
                continue

            platform = str(raw_supporter.get("platform") or "").strip()
            name = str(raw_supporter.get("name") or "").strip()
            url = str(raw_supporter.get("url") or "").strip()
            if not name:
                continue

            if not url:
                url = inferred_url(platform, name)
            if is_self_supporter(platform, name, url) or is_blocked_supporter(name):
                continue

            key = supporter_key(name, url)
            supporter = supporters.setdefault(key, Supporter(name=name, url=url))
            if not supporter.url and url:
                supporter.url = url
            supporter.sessions.add(path.stem)
            supporter.platforms.add(platform_key(platform, name, url))

        section = acknowledgement_section(text)
        if not section:
            continue

        for line in section.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue

            item = line[2:].strip()
            label = re.fullmatch(r"([A-Za-zÀ-ÿ0-9 ._-]+):\s*(.+)", item)
            if label:
                platform = label.group(1).strip()
                people_text = label.group(2).strip()
            else:
                platform, people_text = "", item

            for raw_person in split_people(people_text):
                name, url = parse_person(raw_person, platform)
                if not name:
                    continue
                if is_self_supporter(platform, name, url) or is_blocked_supporter(name):
                    continue

                key = supporter_key(name, url)
                supporter = supporters.setdefault(key, Supporter(name=name, url=url))
                if not supporter.url and url:
                    supporter.url = url
                supporter.sessions.add(path.stem)
                supporter.platforms.add(platform_key(platform, name, url))

    return supporters


def render(supporters: dict[str, Supporter]) -> str:
    rows = sorted(
        supporters.values(),
        key=lambda supporter: (
            -len(supporter.sessions),
            supporter.name.casefold(),
        ),
    )

    lines = [
        "# Generated by scripts/update_supporters.py; do not edit manually.",
        "",
        f"total_supporters = {len(rows)}",
        "",
    ]

    for supporter in rows:
        sessions = sorted(supporter.sessions)
        platforms = sorted(supporter.platforms)
        lines.extend(
            [
                "[[supporters]]",
                f"name = {toml_string(supporter.name)}",
                f"url = {toml_string(supporter.url)}",
                f"session_count = {len(sessions)}",
                "sessions = [" + ", ".join(toml_string(session) for session in sessions) + "]",
                "platforms = [" + ", ".join(toml_string(platform) for platform in platforms) + "]",
                "",
            ]
        )

    return "\n".join(lines)


def main() -> int:
    OUTPUT.write_text(render(collect_supporters()), encoding="utf-8")
    print(f"Updated {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
