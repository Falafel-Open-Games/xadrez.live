#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_whisper_transcripts import (
    DEFAULT_AUDIO_CACHE_DIR,
    DEFAULT_INITIAL_PROMPT,
    DEFAULT_OUTPUT_DIR,
    clean_text,
    download_audio,
    fail,
    format_time,
    log,
    selected_sessions,
    session_youtube_ids,
    write_json_if_changed,
)


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DEFAULT_CHUNK_DIR = Path("/tmp/xadrez-openai-transcript-chunks")
DEFAULT_RESPONSE_CACHE_DIR = Path("/tmp/xadrez-openai-transcripts")
API_URL = "https://api.openai.com/v1/audio/transcriptions"
MODEL_PRICING = {
    "gpt-4o-transcribe": {"input_per_million": 2.50, "output_per_million": 10.00},
    "gpt-4o-mini-transcribe": {"input_per_million": 1.25, "output_per_million": 5.00},
    "whisper-1": {"audio_per_minute": 0.006},
}
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def ensure_command(name: str) -> None:
    if shutil.which(name) is None:
        fail(f"{name} command not found")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def run(command: list[str]) -> None:
    proc = subprocess.run(command, cwd=ROOT)
    if proc.returncode != 0:
        fail(f"command failed: {' '.join(command)}")


def probe_duration_seconds(path: Path) -> float:
    ensure_command("ffprobe")
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        fail(f"ffprobe failed for {path}: {proc.stderr.strip()}")

    try:
        return max(0.0, float(proc.stdout.strip()))
    except ValueError:
        fail(f"ffprobe returned invalid duration for {path}: {proc.stdout.strip()}")


def chunk_audio(
    audio_path: Path,
    session_number: str,
    chunk_dir: Path,
    chunk_seconds: int,
    bitrate: str,
    force: bool,
) -> list[Path]:
    ensure_command("ffmpeg")
    session_chunk_dir = chunk_dir / session_number
    existing = sorted(session_chunk_dir.glob("chunk_*.mp3"))
    if existing and not force:
        log(f"{session_number}: using cached API audio chunks in {session_chunk_dir}")
        return existing

    session_chunk_dir.mkdir(parents=True, exist_ok=True)
    for path in session_chunk_dir.glob("chunk_*.mp3"):
        path.unlink()

    output_pattern = session_chunk_dir / "chunk_%03d.mp3"
    log(
        f"{session_number}: preparing API chunks every {format_time(chunk_seconds)} "
        f"at {bitrate} in {session_chunk_dir}"
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(audio_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            bitrate,
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-reset_timestamps",
            "1",
            str(output_pattern),
        ]
    )
    chunks = sorted(session_chunk_dir.glob("chunk_*.mp3"))
    if not chunks:
        fail(f"{session_number}: ffmpeg did not create audio chunks")
    return chunks


def encode_multipart(fields: list[tuple[str, str]], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----xadrez-live-{uuid.uuid4().hex}"
    body = bytearray()

    def add(value: bytes) -> None:
        body.extend(value)

    for name, value in fields:
        add(f"--{boundary}\r\n".encode())
        add(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        add(value.encode())
        add(b"\r\n")

    for name, path in files:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        add(f"--{boundary}\r\n".encode())
        add(
            (
                f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        add(path.read_bytes())
        add(b"\r\n")

    add(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def transcribe_chunk(
    chunk_path: Path,
    model: str,
    language: str,
    prompt: str,
    response_format: str,
    api_key: str,
    timeout_seconds: int,
) -> dict:
    fields = [
        ("model", model),
        ("language", language),
        ("response_format", response_format),
    ]
    if response_format == "verbose_json":
        fields.append(("timestamp_granularities[]", "segment"))
    if prompt:
        fields.append(("prompt", prompt))

    body, content_type = encode_multipart(fields, [("file", chunk_path)])
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        fail(f"OpenAI API returned HTTP {error.code}: {detail}")
    except urllib.error.URLError as error:
        fail(f"OpenAI API request failed: {error}")


def usage_cost_usd(model: str, usage: dict | None, duration_seconds: float) -> float | None:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return None

    if "audio_per_minute" in pricing:
        return duration_seconds / 60 * pricing["audio_per_minute"]

    if not isinstance(usage, dict):
        return None

    input_tokens = float(usage.get("input_tokens") or 0)
    output_tokens = float(usage.get("output_tokens") or 0)
    return (
        input_tokens / 1_000_000 * pricing["input_per_million"]
        + output_tokens / 1_000_000 * pricing["output_per_million"]
    )


def parse_response_blocks(
    response: dict,
    offset_seconds: float,
    fallback_duration: float,
    segment_block_seconds: int = 30,
) -> list[dict]:
    segments = response.get("segments")
    if isinstance(segments, list) and segments:
        blocks = group_segment_blocks(segments, offset_seconds, segment_block_seconds)
        if blocks:
            return blocks

    text = clean_text(str(response.get("text") or ""))
    if not text:
        return []

    parts = split_text_blocks(text, max_chars=max_chars_for_time_window(text, fallback_duration, segment_block_seconds))
    if not parts:
        return []

    total_chars = sum(len(part) for part in parts) or 1
    consumed_chars = 0
    blocks = []
    for part in parts:
        start_seconds = max(0, round(offset_seconds + fallback_duration * consumed_chars / total_chars))
        blocks.append({"time": format_time(start_seconds), "seconds": start_seconds, "text": part})
        consumed_chars += len(part)
    return blocks


def group_segment_blocks(segments: list, offset_seconds: float, segment_block_seconds: int) -> list[dict]:
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

    max_block_seconds = max(1, segment_block_seconds)
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = clean_text(str(segment.get("text") or ""))
        if not text:
            continue
        start_seconds = max(0, round(offset_seconds + float(segment.get("start") or 0)))
        end_seconds = max(start_seconds, round(offset_seconds + float(segment.get("end") or 0)))
        if not current_parts:
            current_start_seconds = start_seconds
        current_parts.append(text)
        current_end_seconds = max(current_end_seconds, end_seconds)
        if current_end_seconds - current_start_seconds >= max_block_seconds:
            flush()

    flush()
    return blocks


def split_text_blocks(text: str, max_chars: int = 700) -> list[str]:
    sentences = [part.strip() for part in SENTENCE_RE.split(text) if part.strip()]
    if not sentences:
        return []

    blocks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        block = clean_text(" ".join(current))
        if block:
            blocks.append(block)
        current = []
        current_len = 0

    for sentence in sentences:
        if current and current_len + len(sentence) + 1 > max_chars:
            flush()
        current.append(sentence)
        current_len += len(sentence) + 1

    flush()
    return blocks


def max_chars_for_time_window(text: str, duration_seconds: float, block_seconds: int) -> int:
    if duration_seconds <= 0:
        return 700

    chars_per_second = len(text) / duration_seconds
    return max(220, round(chars_per_second * max(1, block_seconds)))


def load_cached_response(path: Path, force: bool) -> dict | None:
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def write_response_cache(path: Path, response: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def filename_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-")


def import_openai_transcripts(
    selected_numbers: set[str] | None,
    latest: int | None,
    audio_cache_dir: Path,
    chunk_dir: Path,
    response_cache_dir: Path,
    output_dir: Path,
    yt_dlp: str,
    audio_format: str,
    model: str,
    language: str,
    prompt: str,
    response_format: str,
    chunk_seconds: int,
    chunk_bitrate: str,
    segment_block_seconds: int,
    force: bool,
    api_key: str,
    timeout_seconds: int,
) -> int:
    sessions = selected_sessions(session_youtube_ids(), selected_numbers, latest)
    output_dir.mkdir(parents=True, exist_ok=True)
    updated = 0
    unchanged = 0
    unavailable = 0

    for youtube_id, session_number, _ in sessions:
        session_started_at = time.monotonic()
        total_cost = 0.0
        unknown_cost = False
        total_duration = 0.0
        all_blocks = []
        raw_usage = []
        source_id = f"openai-{filename_slug(model)}"
        output_path = output_dir / f"{session_number}.{source_id}.json"
        if output_path.exists() and not force:
            output = json.loads(output_path.read_text(encoding="utf-8"))
            print(f"{session_number}: unchanged {output.get('block_count', 0)} OpenAI transcript blocks from {output_path}")
            unchanged += 1
            continue

        log(f"{session_number}: starting OpenAI API transcript model={model} response_format={response_format}")
        audio_path = download_audio(youtube_id, audio_cache_dir, yt_dlp, audio_format, force)
        if not audio_path:
            unavailable += 1
            continue

        chunks = chunk_audio(audio_path, session_number, chunk_dir, chunk_seconds, chunk_bitrate, force)
        chunk_durations = [probe_duration_seconds(chunk) for chunk in chunks]
        total_audio_duration = sum(chunk_durations)
        log(
            f"{session_number}: sending {len(chunks)} chunks "
            f"({format_time(round(total_audio_duration))} audio total) to OpenAI"
        )

        offset_seconds = 0.0
        for index, (chunk, duration_seconds) in enumerate(zip(chunks, chunk_durations), start=1):
            cache_path = response_cache_dir / session_number / f"{model}-{response_format}-{index:03d}.json"
            response = load_cached_response(cache_path, force)
            chunk_started_at = time.monotonic()
            if response is None:
                log(
                    f"{session_number}: API chunk {index}/{len(chunks)} "
                    f"starting at {format_time(round(offset_seconds))}, "
                    f"duration {format_time(round(duration_seconds))}"
                )
                response = transcribe_chunk(chunk, model, language, prompt, response_format, api_key, timeout_seconds)
                write_response_cache(cache_path, response)
            else:
                log(f"{session_number}: using cached API response {cache_path}")

            chunk_elapsed = time.monotonic() - chunk_started_at
            chunk_cost = usage_cost_usd(model, response.get("usage"), duration_seconds)
            if chunk_cost is None:
                unknown_cost = True
                chunk_cost_text = "unknown cost"
            else:
                total_cost += chunk_cost
                chunk_cost_text = f"${chunk_cost:.4f}"

            total_duration += duration_seconds
            raw_usage.append(response.get("usage"))
            all_blocks.extend(parse_response_blocks(response, offset_seconds, duration_seconds, segment_block_seconds))
            offset_seconds += duration_seconds

            elapsed_total = time.monotonic() - session_started_at
            speed = (total_duration / 60) / max(0.01, elapsed_total / 60)
            log(
                f"{session_number}: API chunk {index}/{len(chunks)} done in {format_time(round(chunk_elapsed))}; "
                f"{format_time(round(total_duration))}/{format_time(round(total_audio_duration))} transcritos; "
                f"{speed:.2f} min de audio/min real; {chunk_cost_text}; "
                f"subtotal {'unknown' if unknown_cost else f'${total_cost:.4f}'}"
            )

        if not all_blocks:
            print(f"{session_number}: no parseable OpenAI transcript blocks")
            unavailable += 1
            continue

        elapsed_total = time.monotonic() - session_started_at
        output = {
            "session_number": session_number,
            "youtube_video_id": youtube_id,
            "language": language,
            "source": "openai-api",
            "source_id": source_id,
            "model": model,
            "response_format": response_format,
            "initial_prompt": prompt,
            "block_count": len(all_blocks),
            "audio_seconds": round(total_audio_duration, 3),
            "elapsed_seconds": round(elapsed_total, 3),
            "estimated_cost_usd": None if unknown_cost else round(total_cost, 6),
            "raw_usage": raw_usage,
            "blocks": all_blocks,
        }
        if write_json_if_changed(output_path, output):
            print(f"{session_number}: updated {len(all_blocks)} OpenAI transcript blocks")
            updated += 1
        else:
            print(f"{session_number}: unchanged {len(all_blocks)} OpenAI transcript blocks")
            unchanged += 1

        cost_text = "unknown" if unknown_cost else f"${total_cost:.4f}"
        speed = (total_audio_duration / 60) / max(0.01, elapsed_total / 60)
        print(
            f"{session_number}: OpenAI API total {format_time(round(total_audio_duration))} audio "
            f"in {format_time(round(elapsed_total))} real time "
            f"({speed:.2f} min audio/min real), cost {cost_text}"
        )

    print(f"summary: {updated} updated, {unchanged} unchanged, {unavailable} unavailable")
    return updated


def parse_args() -> argparse.Namespace:
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Generate session transcripts with OpenAI's Audio API.")
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0046")
    parser.add_argument("--latest", type=int, help="Only process the latest N ended sessions.")
    parser.add_argument("--audio-cache-dir", type=Path, default=DEFAULT_AUDIO_CACHE_DIR)
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR)
    parser.add_argument("--response-cache-dir", type=Path, default=DEFAULT_RESPONSE_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--yt-dlp-format", default=os.environ.get("YT_DLP_AUDIO_FORMAT", "worstaudio/worst"))
    parser.add_argument("--model", default=os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"))
    parser.add_argument("--response-format", default=os.environ.get("OPENAI_TRANSCRIBE_RESPONSE_FORMAT", "auto"))
    parser.add_argument("--language", default=os.environ.get("OPENAI_TRANSCRIBE_LANGUAGE", "pt"))
    parser.add_argument("--prompt", default=os.environ.get("OPENAI_TRANSCRIBE_PROMPT", DEFAULT_INITIAL_PROMPT))
    parser.add_argument("--chunk-seconds", type=int, default=int(os.environ.get("OPENAI_TRANSCRIBE_CHUNK_SECONDS", "1200")))
    parser.add_argument("--chunk-bitrate", default=os.environ.get("OPENAI_TRANSCRIBE_CHUNK_BITRATE", "32k"))
    parser.add_argument(
        "--segment-block-seconds",
        type=int,
        default=int(os.environ.get("OPENAI_TRANSCRIBE_SEGMENT_BLOCK_SECONDS", "30")),
    )
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("OPENAI_TRANSCRIBE_TIMEOUT_SECONDS", "600")))
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.api_key:
        fail("OPENAI_API_KEY is required, or pass --api-key")
    if args.chunk_seconds <= 0:
        fail("--chunk-seconds must be positive")
    response_format = args.response_format
    if response_format == "auto":
        response_format = "verbose_json" if args.model == "whisper-1" else "json"
    if response_format not in {"json", "text", "verbose_json"}:
        fail("--response-format must be auto, json, text, or verbose_json")

    selected_numbers = set(args.sessions) if args.sessions else None
    updated = import_openai_transcripts(
        selected_numbers=selected_numbers,
        latest=args.latest,
        audio_cache_dir=args.audio_cache_dir,
        chunk_dir=args.chunk_dir,
        response_cache_dir=args.response_cache_dir,
        output_dir=args.output_dir,
        yt_dlp=args.yt_dlp,
        audio_format=args.yt_dlp_format,
        model=args.model,
        language=args.language,
        prompt=args.prompt,
        response_format=response_format,
        chunk_seconds=args.chunk_seconds,
        chunk_bitrate=args.chunk_bitrate,
        segment_block_seconds=args.segment_block_seconds,
        force=args.force,
        api_key=args.api_key,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"updated: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
