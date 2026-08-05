#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
CHAT_REPLAYS_DIR = ROOT / "data" / "fcz" / "chat_replays"
SELF_SUPPORTERS = {
    ("youtube", "fczuardi"),
    ("twitch", "sedentarismo"),
}
SELF_HANDLES = {handle for _platform, handle in SELF_SUPPORTERS}
BLOCKED_SUPPORTER_HANDLES = {
    "gsgsgehwge",
}
ANON_AUTHOR_RE = re.compile(r"^Person \d+$")
UNKNOWN_AUTHORS = {"unknown", "@unknown", "anonymous", "@anonymous"}


@dataclass(frozen=True)
class Supporter:
    platform: str
    name: str
    url: str


@dataclass(frozen=True)
class Session:
    number: str
    path: Path
    front_matter: str
    body: str
    extra: dict[str, Any]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def split_front_matter(text: str, path: Path) -> tuple[str, str]:
    if not text.startswith("+++\n"):
        fail(f"missing TOML front matter in {path}")

    end = text.find("\n+++", 4)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")

    front_matter = text[4:end]
    body = text[end + 4 :]
    return front_matter.rstrip(), body


def load_sessions(numbers: set[str] | None, latest: int | None) -> list[Session]:
    sessions: list[Session] = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        if numbers is not None and path.stem not in numbers:
            continue

        text = path.read_text(encoding="utf-8")
        front_matter, body = split_front_matter(text, path)
        try:
            data = tomllib.loads(front_matter)
        except tomllib.TOMLDecodeError as error:
            fail(f"malformed TOML front matter in {path}: {error}")

        extra = data.get("extra")
        if not isinstance(extra, dict):
            continue

        sessions.append(Session(path.stem, path, front_matter, body, extra))

    if numbers is None and latest is not None:
        sessions = sessions[-latest:]

    return sessions


def normalized_handle(name: str) -> str:
    return name.removeprefix("@").strip().lower()


def normalized_platform(platform: str) -> str:
    value = platform.strip().lower()
    known = {
        "youtube",
        "twitch",
        "lichess",
        "chess.com",
        "discord",
    }
    if value in known:
        return value
    return ""


def is_self(platform: str, name: str) -> bool:
    handle = normalized_handle(name)
    return (normalized_platform(platform), handle) in SELF_SUPPORTERS or handle in SELF_HANDLES


def is_blocked_supporter(name: str) -> bool:
    return normalized_handle(name) in BLOCKED_SUPPORTER_HANDLES


def inferred_url(platform: str, name: str) -> str:
    handle = name.removeprefix("@").strip()
    if not handle:
        return ""

    platform_key = normalized_platform(platform)
    if platform_key == "youtube":
        return f"https://www.youtube.com/@{quote(handle)}"
    if platform_key == "twitch":
        return f"https://www.twitch.tv/{quote(handle)}"
    if platform_key == "lichess":
        return f"https://lichess.org/@/{quote(handle)}"
    if platform_key == "chess.com":
        return f"https://www.chess.com/member/{quote(handle)}"
    return ""


def inferred_platform(platform: str, url: str) -> str:
    if platform.strip():
        return platform.strip()

    lower_url = url.lower()
    if "youtube.com" in lower_url:
        return "YouTube"
    if "twitch.tv" in lower_url:
        return "Twitch"
    if "lichess.org" in lower_url:
        return "Lichess"
    if "chess.com" in lower_url:
        return "Chess.com"
    if "discord" in lower_url:
        return "Discord"
    return platform.strip()


def display_name(platform: str, author: str) -> str:
    author = author.strip()
    if not author:
        return ""
    if normalized_platform(platform) in {"youtube", "twitch"} and not author.startswith("@"):
        return f"@{author}"
    return author


def participant_key(platform: str, name: str) -> tuple[str, str]:
    return normalized_platform(platform), normalized_handle(name)


def chat_supporters(session_number: str) -> list[Supporter]:
    path = CHAT_REPLAYS_DIR / f"{session_number}.json"
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[tuple[str, str], Supporter] = {}
    for message in data.get("messages", []):
        if not isinstance(message, dict):
            continue

        platform = str(message.get("platform") or "").strip()
        platform_key = normalized_platform(platform)
        if not platform_key:
            continue

        author = str(message.get("author") or "").strip()
        if (
            not author
            or author.lower() == "host"
            or author.lower() in UNKNOWN_AUTHORS
            or ANON_AUTHOR_RE.fullmatch(author)
            or is_self(platform, author)
            or is_blocked_supporter(author)
        ):
            continue

        name = display_name(platform, author)
        key = participant_key(platform, name)
        if not key[1] or key in rows:
            continue

        nice_platform = "YouTube" if platform_key == "youtube" else "Twitch"
        rows[key] = Supporter(nice_platform, name, inferred_url(nice_platform, name))

    return sorted(rows.values(), key=lambda item: (item.platform.lower(), item.name.casefold()))


def existing_supporters(extra: dict[str, Any]) -> list[Supporter]:
    rows = []
    for item in extra.get("supporters", []):
        if not isinstance(item, dict):
            continue
        platform = str(item.get("platform") or "").strip()
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if name and not is_self(platform, name):
            rows.append(Supporter(platform, name, url or inferred_url(platform, name)))
    return rows


def split_people(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_person(raw: str, platform: str) -> Supporter | None:
    link = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", raw)
    if link:
        name = link.group(1).strip()
        url = link.group(2).strip()
    else:
        bare_url = re.fullmatch(r"<([^>]+)>", raw)
        if bare_url:
            url = bare_url.group(1).strip()
            name = url.rstrip("/").rsplit("/", 1)[-1]
            platform = inferred_platform(platform, url)
        else:
            name = raw.strip()
            url = inferred_url(platform, name)

    if not name or is_self(platform, name) or is_blocked_supporter(name) or name.lower() in UNKNOWN_AUTHORS:
        return None

    return Supporter(platform, name, url)


def markdown_acknowledgements(body: str) -> list[Supporter]:
    heading = re.search(r"(?m)^## Agradecimentos\s*$", body)
    if not heading:
        return []

    start = heading.end()
    next_heading = re.search(r"(?m)^## ", body[start:])
    end = start + next_heading.start() if next_heading else len(body)
    rows: list[Supporter] = []
    for raw_line in body[start:end].splitlines():
        line = raw_line.strip()
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
            supporter = parse_person(raw_person, platform)
            if supporter:
                rows.append(supporter)

    return rows


def historical_markdown_acknowledgements(path: Path, revision: str) -> list[Supporter]:
    relative = path.relative_to(ROOT)
    proc = subprocess.run(
        ["jj", "file", "show", "-r", revision, str(relative)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        return []

    try:
        _front_matter, body = split_front_matter(proc.stdout, path)
    except SystemExit:
        return []
    return markdown_acknowledgements(body)


def merged_supporters(*groups: list[Supporter]) -> list[Supporter]:
    merged: list[Supporter] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for supporter in group:
            key = participant_key(supporter.platform, supporter.name)
            if not key[1] or key in seen:
                continue
            seen.add(key)
            url = supporter.url or inferred_url(supporter.platform, supporter.name)
            merged.append(Supporter(supporter.platform, supporter.name, url))
    return merged


def remove_extra_supporters(front_matter: str) -> str:
    lines = front_matter.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == "[[extra.supporters]]":
            index += 1
            while index < len(lines):
                stripped = lines[index].strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    break
                index += 1
            while kept and kept[-1] == "":
                kept.pop()
            continue
        kept.append(lines[index])
        index += 1
    return "\n".join(kept).rstrip()


def render_supporters(supporters: list[Supporter]) -> str:
    blocks: list[str] = []
    for supporter in supporters:
        blocks.extend(
            [
                "[[extra.supporters]]",
                f"platform = {toml_string(supporter.platform)}",
                f"name = {toml_string(supporter.name)}",
                f"url = {toml_string(supporter.url)}",
                "",
            ]
        )
    return "\n".join(blocks).rstrip()


def remove_markdown_acknowledgements(body: str) -> str:
    heading = re.search(r"(?m)^## Agradecimentos\s*$", body)
    if not heading:
        return body

    start = heading.start()
    next_heading = re.search(r"(?m)^## ", body[heading.end() :])
    end = heading.end() + next_heading.start() if next_heading else len(body)
    new_body = body[:start].rstrip() + "\n"
    if next_heading:
        new_body += "\n" + body[end:].lstrip("\n")
    return new_body


def render_session(session: Session, supporters: list[Supporter], keep_markdown: bool) -> str:
    front_matter = remove_extra_supporters(session.front_matter)
    if supporters:
        front_matter = front_matter.rstrip() + "\n\n" + render_supporters(supporters)

    body = session.body
    if supporters and not keep_markdown:
        body = remove_markdown_acknowledgements(body)

    return "+++\n" + front_matter.rstrip() + "\n+++" + body


def keys(items: list[Supporter]) -> set[tuple[str, str]]:
    return {participant_key(item.platform, item.name) for item in items}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update structured session supporters from merged chat replays."
    )
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0041")
    parser.add_argument("--latest", type=int, default=5, help="Only scan latest N sessions by default.")
    parser.add_argument("--all", action="store_true", help="Scan all sessions.")
    parser.add_argument("--dry-run", action="store_true", help="Print differences without writing files.")
    parser.add_argument("--keep-markdown", action="store_true", help="Do not remove old Markdown acknowledgements sections.")
    parser.add_argument(
        "--recover-markdown-from-rev",
        default="",
        help="Also merge Markdown acknowledgements from a previous jj revision, e.g. @-.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = set(args.sessions) if args.sessions else None
    latest = None if selected or args.all else args.latest
    changed = 0
    skipped = 0

    for session in load_sessions(selected, latest):
        current = existing_supporters(session.extra)
        manual = markdown_acknowledgements(session.body)
        if args.recover_markdown_from_rev:
            manual = merged_supporters(
                manual,
                historical_markdown_acknowledgements(session.path, args.recover_markdown_from_rev),
            )
        chat = chat_supporters(session.number)
        supporters = merged_supporters(current, manual, chat)
        if not supporters:
            log(f"{session.number}: no supporters")
            skipped += 1
            continue

        source = merged_supporters(current, manual)
        missing = keys(supporters) - keys(source)
        stale = set()
        new_text = render_session(session, supporters, args.keep_markdown)
        old_text = session.path.read_text(encoding="utf-8")
        if new_text == old_text:
            log(f"{session.number}: already up to date")
            continue

        changed += 1
        names = ", ".join(f"{item.platform}:{item.name}" for item in supporters)
        if args.dry_run:
            print(
                f"{session.number}: would update {len(supporters)} supporter(s); "
                f"missing={len(missing)} stale={len(stale)}; {names}"
            )
        else:
            session.path.write_text(new_text, encoding="utf-8")
            log(f"{session.number}: updated {len(supporters)} supporter(s); {names}")

    action = "would update" if args.dry_run else "updated"
    log(f"{action}: {changed}; skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
