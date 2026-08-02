#!/usr/bin/env python3
from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
TRANSCRIPT_DIR = ROOT / "data" / "transcripts"


def front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++"):
        return {}
    end = text.find("\n+++", 3)
    if end == -1:
        return {}
    return tomllib.loads(text[3:end])


def main() -> int:
    missing = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        data = front_matter(path)
        extra = data.get("extra")
        if not isinstance(extra, dict):
            continue

        status = str(extra.get("status") or "").strip().lower()
        status_tone = str(extra.get("status_tone") or "").strip().lower()
        is_ended = status == "encerrada" or status_tone in {"ended", "completed"}
        output_path = TRANSCRIPT_DIR / f"{path.stem}.faster-whisper.json"
        if is_ended and not output_path.exists():
            missing.append(path.stem)

    print(" ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
