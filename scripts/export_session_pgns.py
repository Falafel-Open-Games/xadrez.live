#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "data" / "fcz" / "lichess_game_analysis.toml"
OUTPUT_DIR = ROOT / "static" / "fcz" / "pgn"
INDEX_PATH = ROOT / "data" / "fcz" / "pgn_files.json"
GAME_ID_RE = re.compile(r"^[A-Za-z0-9]{8}$")


def load_analysis(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return []
    games = data.get("games")
    return [game for game in games if isinstance(game, dict)] if isinstance(games, list) else []


def normalize_pgn(value: Any) -> str:
    pgn = str(value or "").strip()
    if not pgn:
        return ""
    return pgn.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    entries: list[dict[str, Any]] = []
    written = 0

    for row in load_analysis(ANALYSIS_PATH):
        session_number = str(row.get("session_number") or "").strip()
        game_index = row.get("game_index")
        game_id = str(row.get("game_id") or "").strip()
        pgn = normalize_pgn(row.get("pgn"))
        if not session_number or not isinstance(game_index, int) or not GAME_ID_RE.fullmatch(game_id) or not pgn:
            continue

        relative_path = Path("fcz") / "pgn" / session_number / f"{game_index}-{game_id}.pgn"
        output_path = ROOT / "static" / relative_path
        if write_if_changed(output_path, pgn):
            written += 1
        entries.append(
            {
                "session_number": session_number,
                "game_index": game_index,
                "game_id": game_id,
                "url": "/" + relative_path.as_posix(),
            }
        )

    payload = {"games": sorted(entries, key=lambda item: (item["session_number"], item["game_index"], item["game_id"]))}
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    index_content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    index_changed = write_if_changed(INDEX_PATH, index_content)

    status = "Updated" if written or index_changed else "Unchanged"
    print(f"{status} PGN exports: {len(entries)} game(s), {written} file(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
