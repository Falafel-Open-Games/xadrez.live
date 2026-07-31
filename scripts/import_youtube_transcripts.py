#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DEFAULT_CACHE_DIR = Path("/tmp/xadrez-transcripts")
DEFAULT_OUTPUT_DIR = ROOT / "data" / "transcripts"


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


def session_youtube_ids() -> list[tuple[str, str, Path]]:
    sessions: list[tuple[str, str, Path]] = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        data = tomllib.loads(extract_front_matter(path.read_text(encoding="utf-8"), path))
        extra = data.get("extra")
        if not isinstance(extra, dict):
            continue

        youtube_id = str(extra.get("youtube_video_id") or "").strip()
        status = str(extra.get("status") or "").strip().lower()
        status_tone = str(extra.get("status_tone") or "").strip().lower()
        is_ended = status == "encerrada" or status_tone in {"ended", "completed"}
        if youtube_id and youtube_id != "REPLACE_WITH_YOUTUBE_VIDEO_ID" and is_ended:
            sessions.append((youtube_id, path.stem, path))

    return sessions


def selected_sessions(all_sessions: list[tuple[str, str, Path]], numbers: set[str] | None, latest: int | None) -> list[tuple[str, str, Path]]:
    sessions = all_sessions
    if numbers is not None:
        sessions = [session for session in sessions if session[1] in numbers]
    elif latest is not None and latest > 0:
        sessions = sessions[-latest:]
    return sessions


def download_transcript(
    youtube_id: str,
    cache_dir: Path,
    language: str,
    yt_dlp: str,
    force: bool,
) -> Path | None:
    transcript_path = cache_dir / f"{youtube_id}.{language}.json3"
    if transcript_path.exists() and not force:
        return transcript_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            yt_dlp,
            "--skip-download",
            "--write-auto-subs",
            "--sub-langs",
            language,
            "--sub-format",
            "json3",
            "--paths",
            str(cache_dir),
            "--output",
            "%(id)s",
            f"https://www.youtube.com/watch?v={youtube_id}",
        ],
        check=False,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        last_line = (proc.stderr.strip().splitlines() or proc.stdout.strip().splitlines() or ["yt-dlp failed"])[-1]
        print(f"{youtube_id}: transcript unavailable ({last_line})")
        return transcript_path if transcript_path.exists() else None

    if not transcript_path.exists():
        print(f"{youtube_id}: no {language} transcript file")
        return None

    return transcript_path


def event_text(event: dict) -> str:
    parts = []
    for segment in event.get("segs") or []:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("utf8") or "")
        if text:
            parts.append(text)
    return clean_text("".join(parts))


def clean_text(text: str) -> str:
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def sentenceish(text: str) -> bool:
    return text.endswith((".", "!", "?", ":"))


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def parse_transcript(transcript_path: Path, max_block_seconds: int) -> list[dict]:
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    blocks = []
    current_parts: list[str] = []
    current_start_seconds = 0
    current_end_seconds = 0

    def flush() -> None:
        nonlocal current_parts, current_start_seconds, current_end_seconds
        text = clean_text(" ".join(current_parts))
        if text:
            blocks.append(
                {
                    "time": format_time(current_start_seconds),
                    "seconds": current_start_seconds,
                    "text": text,
                }
            )
        current_parts = []
        current_start_seconds = 0
        current_end_seconds = 0

    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue

        text = event_text(event)
        if not text:
            continue

        start_seconds = max(0, round(int(event.get("tStartMs") or 0) / 1000))
        duration_seconds = max(0, round(int(event.get("dDurationMs") or 0) / 1000))
        end_seconds = start_seconds + duration_seconds

        if not current_parts:
            current_start_seconds = start_seconds

        current_parts.append(text)
        current_end_seconds = max(current_end_seconds, end_seconds)

        elapsed = current_end_seconds - current_start_seconds
        if elapsed >= max_block_seconds and sentenceish(text):
            flush()
        elif elapsed >= max_block_seconds * 2:
            flush()

    flush()
    return blocks


def import_transcripts(
    cache_dir: Path,
    output_dir: Path,
    selected_numbers: set[str] | None,
    language: str,
    yt_dlp: str,
    force: bool,
    max_block_seconds: int,
    latest: int | None,
) -> int:
    sessions = selected_sessions(session_youtube_ids(), selected_numbers, latest)
    output_dir.mkdir(parents=True, exist_ok=True)
    updated = 0
    unchanged = 0
    unavailable = 0

    for youtube_id, session_number, _ in sessions:
        transcript_path = download_transcript(youtube_id, cache_dir, language, yt_dlp, force)
        if not transcript_path:
            unavailable += 1
            continue

        blocks = parse_transcript(transcript_path, max_block_seconds)
        if not blocks:
            print(f"{session_number}: no parseable transcript blocks in {transcript_path}")
            unavailable += 1
            continue

        output_path = output_dir / f"{session_number}.json"
        output = {
            "session_number": session_number,
            "youtube_video_id": youtube_id,
            "language": language,
            "block_count": len(blocks),
            "blocks": blocks,
        }
        content = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        if output_path.exists() and output_path.read_text(encoding="utf-8") == content:
            print(f"{session_number}: unchanged {len(blocks)} transcript blocks from {transcript_path}")
            unchanged += 1
        else:
            output_path.write_text(content, encoding="utf-8")
            print(f"{session_number}: updated {len(blocks)} transcript blocks from {transcript_path}")
            updated += 1

    print(f"summary: {updated} updated, {unchanged} unchanged, {unavailable} unavailable")
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and import YouTube automatic transcripts into static session transcript data."
    )
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0038")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--language", default="pt-orig")
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--latest", type=int, help="Only process the latest N ended sessions.")
    parser.add_argument("--max-block-seconds", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_numbers = set(args.sessions) if args.sessions else None
    updated = import_transcripts(
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        selected_numbers=selected_numbers,
        language=args.language,
        yt_dlp=args.yt_dlp,
        force=args.force,
        max_block_seconds=args.max_block_seconds,
        latest=args.latest,
    )
    print(f"updated: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
