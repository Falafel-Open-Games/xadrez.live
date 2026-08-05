#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
LICHESS_URL_RE = re.compile(r"^(https://lichess\.org/[A-Za-z0-9]{8})(?:/(white|black))?$")
COLOR_RE = re.compile(r'^color\s*=\s*"([^"]*)"')
URL_RE = re.compile(r'^(?P<prefix>\s*(?:game_url|lichess_game_url)\s*=\s*")(?P<url>https://lichess\.org/[A-Za-z0-9]{8}(?:/(?:white|black))?)(?P<suffix>"\s*)$')


@dataclass
class GameBlock:
    url_line: int | None = None
    url: str = ""
    color: str = ""


def normalize_color(value: str) -> str:
    color = value.strip().casefold()
    if color in {"white", "brancas", "branco"}:
        return "white"
    if color in {"black", "pretas", "preto"}:
        return "black"
    return ""


def normalized_lichess_url(url: str, color: str) -> str:
    match = LICHESS_URL_RE.fullmatch(url.strip())
    if not match or color not in {"white", "black"}:
        return url
    return f"{match.group(1)}/{color}"


def is_table_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def collect_blocks(lines: list[str]) -> list[GameBlock]:
    blocks: list[GameBlock] = []
    current: GameBlock | None = None
    in_extra = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[extra]":
            if current:
                blocks.append(current)
            current = GameBlock()
            in_extra = True
            continue
        if stripped == "[[extra.games]]":
            if current:
                blocks.append(current)
            current = GameBlock()
            in_extra = False
            continue
        if is_table_header(stripped) and stripped not in {"[extra]", "[[extra.games]]"}:
            if current:
                blocks.append(current)
            current = None
            in_extra = False
            continue

        if current is None:
            continue

        url_match = URL_RE.match(line)
        if url_match and (not in_extra or "lichess_game_url" in line):
            current.url_line = index
            current.url = url_match.group("url")
            continue

        color_match = COLOR_RE.match(stripped)
        if color_match:
            current.color = normalize_color(color_match.group(1))

    if current:
        blocks.append(current)
    return [block for block in blocks if block.url_line is not None and block.url]


def normalize_file(path: Path, write: bool) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    changes: list[str] = []

    for block in collect_blocks(lines):
        wanted = normalized_lichess_url(block.url, block.color)
        if wanted == block.url:
            continue
        assert block.url_line is not None
        lines[block.url_line] = lines[block.url_line].replace(block.url, wanted, 1)
        changes.append(f"{path.relative_to(ROOT)}:{block.url_line + 1}: {block.url} -> {wanted}")

    if write and changes:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Lichess game URLs to include the saved player color.")
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0051.")
    parser.add_argument("--write", action="store_true", help="Rewrite files instead of only checking.")
    args = parser.parse_args()

    if args.sessions:
        paths = [CONTENT_DIR / f"{session}.md" for session in args.sessions]
    else:
        paths = sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md"))

    missing = [path for path in paths if not path.exists()]
    if missing:
        for path in missing:
            print(f"missing: {path.relative_to(ROOT)}", file=sys.stderr)
        return 2

    changes = [change for path in paths for change in normalize_file(path, args.write)]
    if changes:
        action = "updated" if args.write else "would update"
        for change in changes:
            print(f"{action}: {change}")
        return 0 if args.write else 1

    print("Lichess game URLs already match saved colors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
