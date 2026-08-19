#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSCRIPT_DIR = ROOT / "data" / "fcz" / "transcripts"
WORD_RE = re.compile(r"[a-z0-9]+")


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def normalize_session_number(value: str) -> str:
    value = value.strip()
    if value.isdigit() and len(value) <= 4:
        return value.zfill(4)
    return value


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(WORD_RE.findall(value))


def token_set(value: str) -> set[str]:
    return set(normalize_text(value).split())


def partial_sequence_match(source_tokens: list[str], reference_tokens: list[str]) -> tuple[float, int]:
    if not source_tokens or not reference_tokens:
        return 0.0, 0
    if len(reference_tokens) <= len(source_tokens):
        return SequenceMatcher(None, " ".join(source_tokens), " ".join(reference_tokens)).ratio(), 0

    window_size = min(len(reference_tokens), max(6, len(source_tokens)))
    step = max(1, window_size // 4)
    source_text = " ".join(source_tokens)
    best = 0.0
    best_start = 0
    starts = set(range(0, max(1, len(reference_tokens) - window_size + 1), step))
    starts.add(max(0, len(reference_tokens) - window_size))
    for start in sorted(starts):
        candidate_text = " ".join(reference_tokens[start : start + window_size])
        score = SequenceMatcher(None, source_text, candidate_text).ratio()
        if score > best:
            best = score
            best_start = start
    return best, best_start


def overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


def read_transcript(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"{path} does not exist")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
        fail(f"{path} is not a transcript JSON with blocks")
    return data


def transcript_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_json_if_changed(path: Path, data: dict[str, Any]) -> bool:
    content = transcript_json(data)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def block_token_times(blocks: list[dict[str, Any]], index: int, token_count: int) -> list[int]:
    start_seconds = int(blocks[index].get("seconds") or 0)
    if index + 1 < len(blocks):
        end_seconds = int(blocks[index + 1].get("seconds") or start_seconds)
    else:
        end_seconds = start_seconds + 60
    end_seconds = max(start_seconds + 1, min(end_seconds, start_seconds + 120))
    if token_count <= 1:
        return [start_seconds]
    return [
        round(start_seconds + (end_seconds - start_seconds) * token_index / token_count)
        for token_index in range(token_count)
    ]


def reference_windows(blocks: list[dict[str, Any]], max_window_blocks: int) -> list[dict[str, Any]]:
    windows = []
    block_count = len(blocks)
    for start in range(block_count):
        parts = []
        normalized_tokens = []
        token_times = []
        for end in range(start, min(block_count, start + max_window_blocks)):
            block = blocks[end]
            text = str(block.get("text") or "")
            if not text:
                continue
            parts.append(text)
            block_tokens = normalize_text(text).split()
            normalized_tokens.extend(block_tokens)
            token_times.extend(block_token_times(blocks, end, len(block_tokens)))
            combined_text = " ".join(parts)
            windows.append(
                {
                    "start_index": start,
                    "end_index": end,
                    "seconds": int(blocks[start].get("seconds") or 0),
                    "time": str(blocks[start].get("time") or format_time(int(blocks[start].get("seconds") or 0))),
                    "text": combined_text,
                    "normalized": normalize_text(combined_text),
                    "normalized_tokens": normalized_tokens[:],
                    "token_times": token_times[:],
                    "tokens": token_set(combined_text),
                }
            )
    return windows


def timing_penalty(source_seconds: int, reference_seconds: int, max_penalty: float) -> float:
    delta = abs(source_seconds - reference_seconds)
    if delta <= 120:
        return 0.0
    if delta >= 1800:
        return max_penalty
    return max_penalty * ((delta - 120) / (1800 - 120))


def match_block(block: dict[str, Any], windows: list[dict[str, Any]], max_candidates: int, max_time_penalty: float) -> dict[str, Any]:
    source_text = str(block.get("text") or "")
    source_normalized = normalize_text(source_text)
    source_normalized_tokens = source_normalized.split()
    source_tokens = token_set(source_text)
    source_seconds = int(block.get("seconds") or 0)
    if not source_normalized or not source_tokens:
        return {"matched": False, "score": 0.0}

    candidates = sorted(
        windows,
        key=lambda window: overlap_score(source_tokens, window["tokens"]),
        reverse=True,
    )[:max_candidates]

    best: dict[str, Any] | None = None
    for window in candidates:
        full_text_score = SequenceMatcher(None, source_normalized, window["normalized"]).ratio()
        partial_text_score, partial_token_start = partial_sequence_match(source_normalized_tokens, window["normalized_tokens"])
        text_score = max(full_text_score, partial_text_score)
        reference_seconds = int(window["seconds"])
        token_times = window.get("token_times") or []
        if partial_text_score >= full_text_score and token_times:
            reference_seconds = int(token_times[min(partial_token_start, len(token_times) - 1)])
        overlap = overlap_score(source_tokens, window["tokens"])
        score = (text_score * 0.75 + overlap * 0.25) - timing_penalty(
            source_seconds,
            reference_seconds,
            max_time_penalty,
        )
        candidate = {
            "matched": True,
            "score": round(score, 4),
            "text_score": round(text_score, 4),
            "overlap_score": round(overlap, 4),
            "reference_seconds": reference_seconds,
            "reference_time": format_time(reference_seconds),
            "reference_start_index": int(window["start_index"]),
            "reference_end_index": int(window["end_index"]),
            "reference_token_start": int(partial_token_start),
            "original_seconds": source_seconds,
            "original_time": str(block.get("time") or format_time(source_seconds)),
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    return best or {"matched": False, "score": 0.0}


def align_transcript(
    source: dict[str, Any],
    reference: dict[str, Any],
    threshold: float,
    max_window_blocks: int,
    max_candidates: int,
    max_time_penalty: float,
    seek_preroll_seconds: int,
    include_block_metadata: bool,
) -> dict[str, Any]:
    windows = reference_windows(reference["blocks"], max_window_blocks)
    blocks = []
    aligned = 0
    deltas = []
    scores = []

    for block in source["blocks"]:
        block = dict(block)
        match = match_block(block, windows, max_candidates, max_time_penalty)
        if match.get("matched") and float(match.get("score") or 0) >= threshold:
            original_seconds = int(block.get("seconds") or 0)
            new_seconds = max(0, int(match["reference_seconds"]) - seek_preroll_seconds)
            block["seconds"] = new_seconds
            block["time"] = format_time(new_seconds)
            block["timestamp"] = block["time"]
            if include_block_metadata:
                block["timestamp_alignment"] = {
                    "source": "faster-whisper",
                    "score": match["score"],
                    "text_score": match["text_score"],
                    "overlap_score": match["overlap_score"],
                    "original_seconds": original_seconds,
                    "original_time": match["original_time"],
                    "delta_seconds": new_seconds - original_seconds,
                    "reference_start_index": match["reference_start_index"],
                    "reference_end_index": match["reference_end_index"],
                    "reference_token_start": match["reference_token_start"],
                }
            aligned += 1
            deltas.append(new_seconds - original_seconds)
            scores.append(float(match["score"]))
        elif include_block_metadata:
            block["timestamp_alignment"] = {
                "source": "original",
                "score": float(match.get("score") or 0),
                "reason": "below_threshold",
            }
        blocks.append(block)

    output = dict(source)
    output["source_id"] = f"{source.get('source_id', 'transcript')}-aligned-to-faster-whisper"
    output["timestamp_source"] = "aligned_to_faster_whisper"
    output["timestamp_reference_source_id"] = reference.get("source_id") or reference.get("source")
    output["timestamp_alignment"] = {
        "method": "partial_text_similarity_windows_with_token_time_interpolation",
        "threshold": threshold,
        "max_window_blocks": max_window_blocks,
        "max_candidates": max_candidates,
        "max_time_penalty": max_time_penalty,
        "seek_preroll_seconds": seek_preroll_seconds,
        "include_block_metadata": include_block_metadata,
        "aligned_blocks": aligned,
        "unaligned_blocks": len(blocks) - aligned,
        "block_count": len(blocks),
        "alignment_rate": round(aligned / len(blocks), 4) if blocks else 0,
        "mean_score": round(sum(scores) / len(scores), 4) if scores else 0,
        "min_delta_seconds": min(deltas) if deltas else 0,
        "max_delta_seconds": max(deltas) if deltas else 0,
        "mean_abs_delta_seconds": round(sum(abs(delta) for delta in deltas) / len(deltas), 2) if deltas else 0,
    }
    output["blocks"] = blocks
    return output


def output_is_current(output_path: Path, source_path: Path, reference_path: Path, args: argparse.Namespace) -> bool:
    if not output_path.exists():
        return False
    output_mtime = output_path.stat().st_mtime
    if output_mtime < source_path.stat().st_mtime or output_mtime < reference_path.stat().st_mtime:
        return False

    try:
        output = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(output, dict):
        return False
    alignment = output.get("timestamp_alignment")
    if not isinstance(alignment, dict):
        return False

    expected = {
        "method": "partial_text_similarity_windows_with_token_time_interpolation",
        "threshold": args.threshold,
        "max_window_blocks": args.max_window_blocks,
        "max_candidates": args.max_candidates,
        "max_time_penalty": args.max_time_penalty,
        "seek_preroll_seconds": max(0, args.seek_preroll_seconds),
        "include_block_metadata": args.include_block_metadata,
    }
    return all(alignment.get(key) == value for key, value in expected.items())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Align estimated transcript timestamps to a timed reference transcript.")
    parser.add_argument("sessions", nargs="*", help="Session numbers, e.g. 0047 or 47")
    parser.add_argument("--transcript-dir", type=Path, default=DEFAULT_TRANSCRIPT_DIR)
    parser.add_argument("--source-suffix", default="openai-gpt-4o-mini-transcribe")
    parser.add_argument("--reference-suffix", default="faster-whisper")
    parser.add_argument("--output-suffix", default="openai-gpt-4o-mini-transcribe.aligned")
    parser.add_argument("--threshold", type=float, default=0.36)
    parser.add_argument("--max-window-blocks", type=int, default=3)
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--max-time-penalty", type=float, default=0.12)
    parser.add_argument("--seek-preroll-seconds", type=int, default=8)
    parser.add_argument("--include-block-metadata", action="store_true")
    parser.add_argument("--all-existing", action="store_true", help="Align every source transcript that also has the reference transcript.")
    parser.add_argument("--latest", type=int, help="Only align the latest N matching sessions.")
    parser.add_argument("--force", action="store_true", help="Recompute even when the aligned transcript output is current.")
    args = parser.parse_args()
    args.sessions = [normalize_session_number(session) for session in args.sessions]
    if not args.sessions and not args.all_existing and args.latest is None:
        parser.error("provide at least one session or use --all-existing/--latest")
    return args


def discover_sessions(transcript_dir: Path, source_suffix: str, reference_suffix: str) -> list[str]:
    sessions = []
    for source_path in sorted(transcript_dir.glob(f"*.{source_suffix}.json")):
        session = source_path.name.split(".", 1)[0]
        if (transcript_dir / f"{session}.{reference_suffix}.json").exists():
            sessions.append(session)
    return sessions


def main() -> int:
    args = parse_args()
    sessions = args.sessions
    if args.all_existing or (args.latest is not None and args.latest > 0):
        discovered = discover_sessions(args.transcript_dir, args.source_suffix, args.reference_suffix)
        if args.latest is not None and args.latest > 0:
            discovered = discovered[-args.latest :]
        sessions = sorted(set(sessions) | set(discovered))
    if not sessions:
        print("No matching transcripts to align.")
        return 0

    for session in sessions:
        source_path = args.transcript_dir / f"{session}.{args.source_suffix}.json"
        reference_path = args.transcript_dir / f"{session}.{args.reference_suffix}.json"
        output_path = args.transcript_dir / f"{session}.{args.output_suffix}.json"
        if not source_path.exists():
            fail(f"{source_path} does not exist")
        if not reference_path.exists():
            fail(f"{reference_path} does not exist")
        if not args.force and output_is_current(output_path, source_path, reference_path, args):
            print(f"{session}: current {output_path.name}")
            continue

        source = read_transcript(source_path)
        reference = read_transcript(reference_path)
        output = align_transcript(
            source,
            reference,
            threshold=args.threshold,
            max_window_blocks=args.max_window_blocks,
            max_candidates=args.max_candidates,
            max_time_penalty=args.max_time_penalty,
            seek_preroll_seconds=max(0, args.seek_preroll_seconds),
            include_block_metadata=args.include_block_metadata,
        )
        changed = write_json_if_changed(output_path, output)
        stats = output["timestamp_alignment"]
        status = "updated" if changed else "unchanged"
        print(
            f"{session}: {status}; aligned {stats['aligned_blocks']}/{stats['block_count']} blocks "
            f"({stats['alignment_rate']:.1%}), mean |delta| {stats['mean_abs_delta_seconds']}s, "
            f"mean score {stats['mean_score']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
