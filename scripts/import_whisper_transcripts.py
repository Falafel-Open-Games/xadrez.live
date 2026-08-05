#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import tomllib
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DEFAULT_AUDIO_CACHE_DIR = Path("/tmp/xadrez-whisper-audio")
DEFAULT_WHISPER_CACHE_DIR = Path("/tmp/xadrez-whisper-transcripts")
DEFAULT_OUTPUT_DIR = ROOT / "data" / "fcz" / "transcripts"
DEFAULT_INITIAL_PROMPT = (
    "Transcrição em português brasileiro de uma live de xadrez. "
    "Vocabulário esperado: Lichess, lichess.org, Chess.com, Stockfish, YouTube, Twitch, Restream, GoatCounter, "
    "roque, fianchetto, Sicilian Defense, Scandinavian Defense, Puzzle do dia, Puzzle Streak, Puzzle Storm, "
    "Puzzle Racer, blunder, rating, mate, xeque, xeque-mate, blitz, rapid, en passant. "
    "Frases comuns: puzzle do dia, resposta com a dama, a resposta é, qual é a resposta. "
    "Peão é a peça de xadrez; em frases como esse peão, um peão, peão passado, peão pendurado, "
    "peão de e4 ou tomar o peão, não transcreva como espião. "
    "Em xadrez, peça pendurada significa hanging piece: se a fala soar como hanging, hang, reng, heng, "
    "renguem, hanging bishop ou hang em bishop perto de peça, bispo, cavalo, torre, dama ou peão, "
    "prefira peça pendurada ou a peça específica pendurada, como bispo pendurado. "
    "Em frases como bispo hanging, bispo hang ou hanging bishop, transcreva como bispo pendurado. "
    "Quando for o lance ou ameaça ao rei em uma frase em português, prefira xeque; mantenha check em nomes "
    "ou frases em inglês, como Force Online Check e checkmate patterns. "
    "Quando for o fim da partida, mate no rei, ou ideia de mate em frase em português, prefira xeque-mate; "
    "mantenha checkmate apenas em títulos, nomes de exercícios ou frases em inglês, como Checkmate Patterns. "
    "En passant é o nome do lance especial de peão; não transcreva como empassant, impassant ou em passando. "
    "Quando a fala se referir ao site ou plataforma de xadrez, transcreva como Lichess, não como lixar, lixares, "
    "lixés ou outras aproximações fonéticas. "
    "Restream é o nome da plataforma de transmissão, não transcreva como restring."
)
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".opus", ".ogg", ".webm", ".wav"}
WHISPER_PROGRESS_RE = re.compile(r"^\[(?P<start>[0-9:.]+)\s+-->\s+(?P<end>[0-9:.]+)\]")


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


def selected_sessions(
    all_sessions: list[tuple[str, str, Path]], numbers: set[str] | None, latest: int | None
) -> list[tuple[str, str, Path]]:
    sessions = all_sessions
    if numbers is not None:
        sessions = [session for session in sessions if session[1] in numbers]
    elif latest is not None and latest > 0:
        sessions = sessions[-latest:]
    return sessions


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def log(message: str) -> None:
    print(message, flush=True)


def run_streaming(command: list[str], on_output_line=None, on_heartbeat=None) -> int:
    if on_output_line is None:
        proc = subprocess.Popen(command, cwd=ROOT)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.send_signal(2)
            proc.wait()
            raise

    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        while proc.poll() is None:
            events = selector.select(timeout=1)
            if not events:
                if on_heartbeat is not None:
                    on_heartbeat(proc)
                continue

            line = proc.stdout.readline()
            if not line:
                continue
            print(line, end="", flush=True)
            on_output_line(line)

        for line in proc.stdout:
            print(line, end="", flush=True)
            on_output_line(line)
        return proc.wait()
    except KeyboardInterrupt:
        proc.send_signal(2)
        proc.wait()
        raise


def parse_timestamp_seconds(timestamp: str) -> float | None:
    parts = timestamp.split(":")
    try:
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return None


class WhisperProgressReporter:
    def __init__(self, session_number: str, progress_interval_seconds: int, heartbeat_interval_seconds: int) -> None:
        self.session_number = session_number
        self.progress_interval_seconds = max(0, progress_interval_seconds)
        self.heartbeat_interval_seconds = max(0, heartbeat_interval_seconds)
        self.started_at = time.monotonic()
        self.next_report_seconds = self.progress_interval_seconds
        self.next_heartbeat_at = self.started_at + self.heartbeat_interval_seconds
        self.latest_audio_seconds = 0.0

    def __call__(self, line: str) -> None:
        if self.progress_interval_seconds <= 0:
            return

        match = WHISPER_PROGRESS_RE.match(line)
        if not match:
            return

        end_seconds = parse_timestamp_seconds(match.group("end"))
        if end_seconds is None:
            return

        self.latest_audio_seconds = max(self.latest_audio_seconds, end_seconds)
        if self.latest_audio_seconds < self.next_report_seconds:
            return

        elapsed_seconds = max(0.1, time.monotonic() - self.started_at)
        audio_minutes = self.latest_audio_seconds / 60
        elapsed_minutes = elapsed_seconds / 60
        speed = audio_minutes / elapsed_minutes
        log(
            f"{self.session_number}: Whisper progress {format_time(round(self.latest_audio_seconds))} "
            f"transcritos em {format_time(round(elapsed_seconds))} de tempo real "
            f"({speed:.2f} min de audio/min real)"
        )
        while self.next_report_seconds <= self.latest_audio_seconds:
            self.next_report_seconds += self.progress_interval_seconds

    def heartbeat(self, proc: subprocess.Popen) -> None:
        if self.heartbeat_interval_seconds <= 0:
            return

        now = time.monotonic()
        if now < self.next_heartbeat_at:
            return

        elapsed_seconds = max(0.1, now - self.started_at)
        if self.latest_audio_seconds > 0:
            audio_minutes = self.latest_audio_seconds / 60
            elapsed_minutes = elapsed_seconds / 60
            speed = audio_minutes / elapsed_minutes
            log(
                f"{self.session_number}: Whisper still running pid={proc.pid}; "
                f"latest timestamp {format_time(round(self.latest_audio_seconds))}; "
                f"{format_time(round(elapsed_seconds))} real time; "
                f"{speed:.2f} min de audio/min real"
            )
        else:
            log(
                f"{self.session_number}: Whisper still running pid={proc.pid}; "
                f"no timestamp output yet after {format_time(round(elapsed_seconds))}"
            )

        self.next_heartbeat_at = now + self.heartbeat_interval_seconds


def cached_audio_path(youtube_id: str, audio_cache_dir: Path) -> Path | None:
    for path in sorted(audio_cache_dir.glob(f"{youtube_id}.*")):
        if path.suffix.lower() in AUDIO_EXTENSIONS:
            return path
    return None


def download_audio(
    youtube_id: str,
    audio_cache_dir: Path,
    yt_dlp: str,
    audio_format: str,
    force: bool,
) -> Path | None:
    existing = cached_audio_path(youtube_id, audio_cache_dir)
    if existing and not force:
        log(f"{youtube_id}: using cached audio {existing}")
        return existing

    audio_cache_dir.mkdir(parents=True, exist_ok=True)
    if force:
        for path in audio_cache_dir.glob(f"{youtube_id}.*"):
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                path.unlink()

    command = [
        yt_dlp,
            "--format",
            audio_format,
        "--paths",
        str(audio_cache_dir),
        "--output",
        "%(id)s.%(ext)s",
        f"https://www.youtube.com/watch?v={youtube_id}",
    ]
    log(f"{youtube_id}: downloading audio format={audio_format} to {audio_cache_dir}")
    if run_streaming(command) != 0:
        print(f"{youtube_id}: audio unavailable", file=sys.stderr)
        return cached_audio_path(youtube_id, audio_cache_dir)

    return cached_audio_path(youtube_id, audio_cache_dir)


def ensure_whisper_command(whisper_cmd: str) -> list[str]:
    command = shlex.split(whisper_cmd)
    if not command:
        fail("empty Whisper command")

    executable = command[0]
    if shutil.which(executable) is None:
        fail(
            f"Whisper command not found: {executable}. "
            "Install a Whisper CLI or pass --whisper-cmd/WHISPER_CMD."
        )
    return command


def run_whisper(
    audio_path: Path,
    session_number: str,
    whisper_cache_dir: Path,
    whisper_cmd: str,
    model: str,
    language: str,
    initial_prompt: str,
    verbose: str,
    progress_interval_seconds: int,
    heartbeat_interval_seconds: int,
    force: bool,
) -> Path | None:
    whisper_cache_dir.mkdir(parents=True, exist_ok=True)
    output_json = whisper_cache_dir / f"{session_number}.json"
    if output_json.exists() and not force:
        log(f"{session_number}: using cached Whisper JSON {output_json}")
        return output_json

    command = ensure_whisper_command(whisper_cmd)
    command = [
        *command,
        str(audio_path),
        "--model",
        model,
        "--language",
        language,
        "--output_format",
        "json",
        "--output_dir",
        str(whisper_cache_dir),
        "--verbose",
        verbose,
    ]
    if initial_prompt:
        command.extend(["--initial_prompt", initial_prompt])
    log(f"{session_number}: running Whisper model={model} language={language}")
    reporter = WhisperProgressReporter(session_number, progress_interval_seconds, heartbeat_interval_seconds)
    if run_streaming(command, on_output_line=reporter, on_heartbeat=reporter.heartbeat) != 0:
        print(f"{session_number}: Whisper unavailable", file=sys.stderr)
        return None

    generated_path = whisper_cache_dir / f"{audio_path.stem}.json"
    if generated_path.exists() and generated_path != output_json:
        generated_path.replace(output_json)

    if not output_json.exists():
        print(f"{session_number}: Whisper did not write {output_json}")
        return None
    return output_json


def normalize_chess_terms(text: str) -> str:
    text = re.sub(r"\bcheckmates\b(?!\s+patterns?\b)", "xeque-mates", text, flags=re.I)
    text = re.sub(r"\bcheckmate\b(?!\s+patterns?\b)", "xeque-mate", text, flags=re.I)
    return text


def clean_text(text: str) -> str:
    return normalize_chess_terms(" ".join(text.replace("\n", " ").split()).strip())


def parse_whisper_json(path: Path, max_block_seconds: int) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = data.get("segments")
    if not isinstance(segments, list):
        return []

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

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = clean_text(str(segment.get("text") or ""))
        if not text:
            continue

        start_seconds = max(0, round(float(segment.get("start") or 0)))
        end_seconds = max(start_seconds, round(float(segment.get("end") or start_seconds)))
        if not current_parts:
            current_start_seconds = start_seconds
        current_parts.append(text)
        current_end_seconds = max(current_end_seconds, end_seconds)
        if current_end_seconds - current_start_seconds >= max_block_seconds:
            flush()

    flush()
    return blocks


def write_json_if_changed(path: Path, data: dict) -> bool:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False

    path.write_text(content, encoding="utf-8")
    return True


def import_whisper_transcripts(
    selected_numbers: set[str] | None,
    latest: int | None,
    audio_cache_dir: Path,
    whisper_cache_dir: Path,
    output_dir: Path,
    yt_dlp: str,
    audio_format: str,
    whisper_cmd: str,
    model: str,
    language: str,
    initial_prompt: str,
    verbose: str,
    force: bool,
    max_block_seconds: int,
    progress_interval_seconds: int,
    heartbeat_interval_seconds: int,
    source_id: str,
    output_suffix: str,
) -> int:
    sessions = selected_sessions(session_youtube_ids(), selected_numbers, latest)
    ensure_whisper_command(whisper_cmd)
    output_dir.mkdir(parents=True, exist_ok=True)
    updated = 0
    unchanged = 0
    unavailable = 0

    for youtube_id, session_number, _ in sessions:
        log(f"{session_number}: starting Whisper transcript fallback")
        audio_path = download_audio(youtube_id, audio_cache_dir, yt_dlp, audio_format, force)
        if not audio_path:
            unavailable += 1
            continue

        whisper_path = run_whisper(
            audio_path,
            session_number,
            whisper_cache_dir,
            whisper_cmd,
            model,
            language,
            initial_prompt,
            verbose,
            progress_interval_seconds,
            heartbeat_interval_seconds,
            force,
        )
        if not whisper_path:
            unavailable += 1
            continue

        log(f"{session_number}: parsing Whisper output {whisper_path}")
        blocks = parse_whisper_json(whisper_path, max_block_seconds)
        if not blocks:
            print(f"{session_number}: no parseable Whisper transcript blocks in {whisper_path}")
            unavailable += 1
            continue

        output_path = output_dir / f"{session_number}.{output_suffix}.json"
        output = {
            "session_number": session_number,
            "youtube_video_id": youtube_id,
            "language": language,
            "source": source_id,
            "model": model,
            "whisper_cmd": whisper_cmd,
            "initial_prompt": initial_prompt,
            "block_count": len(blocks),
            "blocks": blocks,
        }
        if write_json_if_changed(output_path, output):
            print(f"{session_number}: updated {len(blocks)} Whisper transcript blocks from {whisper_path}")
            updated += 1
        else:
            print(f"{session_number}: unchanged {len(blocks)} Whisper transcript blocks from {whisper_path}")
            unchanged += 1

    print(f"summary: {updated} updated, {unchanged} unchanged, {unavailable} unavailable")
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate session transcripts with a local Whisper CLI fallback.")
    parser.add_argument("sessions", nargs="*", help="Optional session numbers, e.g. 0046")
    parser.add_argument("--latest", type=int, help="Only process the latest N ended sessions.")
    parser.add_argument("--audio-cache-dir", type=Path, default=DEFAULT_AUDIO_CACHE_DIR)
    parser.add_argument("--whisper-cache-dir", type=Path, default=DEFAULT_WHISPER_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--yt-dlp", default="yt-dlp")
    parser.add_argument("--yt-dlp-format", default=os.environ.get("YT_DLP_AUDIO_FORMAT", "worstaudio/worst"))
    parser.add_argument("--whisper-cmd", default=os.environ.get("WHISPER_CMD", "whisper"))
    parser.add_argument("--model", default=os.environ.get("WHISPER_MODEL", "turbo"))
    parser.add_argument("--language", default=os.environ.get("WHISPER_LANGUAGE", "Portuguese"))
    parser.add_argument("--initial-prompt", default=os.environ.get("WHISPER_INITIAL_PROMPT", DEFAULT_INITIAL_PROMPT))
    parser.add_argument("--whisper-verbose", default=os.environ.get("WHISPER_VERBOSE", "True"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-block-seconds", type=int, default=30)
    parser.add_argument("--progress-interval-seconds", type=int, default=300)
    parser.add_argument("--heartbeat-interval-seconds", type=int, default=60)
    parser.add_argument("--source-id", default=os.environ.get("WHISPER_SOURCE_ID", "whisper"))
    parser.add_argument("--output-suffix", default=os.environ.get("WHISPER_OUTPUT_SUFFIX", "whisper-cli"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_numbers = set(args.sessions) if args.sessions else None
    updated = import_whisper_transcripts(
        selected_numbers=selected_numbers,
        latest=args.latest,
        audio_cache_dir=args.audio_cache_dir,
        whisper_cache_dir=args.whisper_cache_dir,
        output_dir=args.output_dir,
        yt_dlp=args.yt_dlp,
        audio_format=args.yt_dlp_format,
        whisper_cmd=args.whisper_cmd,
        model=args.model,
        language=args.language,
        initial_prompt=args.initial_prompt,
        verbose=args.whisper_verbose,
        force=args.force,
        max_block_seconds=args.max_block_seconds,
        progress_interval_seconds=args.progress_interval_seconds,
        heartbeat_interval_seconds=args.heartbeat_interval_seconds,
        source_id=args.source_id,
        output_suffix=args.output_suffix,
    )
    print(f"updated: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
