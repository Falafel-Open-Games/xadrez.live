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
TRANSCRIPT_DIR = ROOT / "data" / "transcripts"
CHAT_DIR = ROOT / "data" / "chat_replays"
OUTPUT_DIR = ROOT / "data" / "highlights"
WORD_RE = re.compile(r"[a-z0-9]+")
DISPLAY_WORD_RE = re.compile(r"[\wÀ-ÿ]+(?:[-'][\wÀ-ÿ]+)?")
REFERENCE_ANCHOR_MAX_FORWARD_SECONDS = 8
REFERENCE_LEAD_IN_MAX_FORWARD_SECONDS = 20
REFERENCE_LEAD_IN_MIN_SCORE = 0.7
SOURCE_LEAD_IN_MAX_GAP_SECONDS = 30
SOURCE_LEAD_IN_MAX_WORDS = 5
REFERENCE_LEAD_IN_MAX_WORDS = 5

TRANSCRIPT_SOURCES = [
    ("openai-gpt-4o-mini-transcribe.aligned", "GPT-4o mini alinhado"),
    ("openai-gpt-4o-mini-transcribe", "GPT-4o mini"),
    ("openai-gpt-4o-transcribe.aligned", "GPT-4o alinhado"),
    ("openai-gpt-4o-transcribe", "GPT-4o"),
    ("youtube", "YouTube"),
    ("faster-whisper", "Faster Whisper CLI"),
    ("whisper-cli", "Whisper CLI"),
]
REACTION_RE = re.compile(r"\b(nossa|caramba|uau|eita|ixi|opa|não acredito|que isso|pera[ií]|calma|errei|errado)\b", re.I)
MISTAKE_RE = re.compile(
    r"\b(blunder|capivarada|moscada|pendur|perdi|derrota|imprecis|erro|errei|errado|cagada|"
    r"n[aã]o vi|deixei passar|esqueci|s[oó] agora vi|tinha pensado e esqueci)\b",
    re.I,
)
CHESS_RE = re.compile(r"\b(mate|xeque|checkmate|dama|torre|bispo|cavalo|pe[aã]o|en passant|sicilian|defense|puzzle|streak|plano)\b", re.I)
CHAT_RE = re.compile(r"\b(chat|valeu|obrigado|primeira vez|bom dia,? chat)\b", re.I)
REVIEW_RE = re.compile(
    r"\b(an[aá]lis[ea]|review|stockfish|barrinha|engine|avalia[cç][aã]o|melhor lance|best move|"
    r"boa jogada|linha principal|computer|solu[cç][aã]o)\b",
    re.I,
)
PLAN_RE = re.compile(r"\b(plano|ideia|estrat[eé]gia|vantagem|compensa|simplificar|trocar|defender|atacar)\b", re.I)
TIME_RE = re.compile(r"\b(tempo|pouco tempo|sem tempo|rel[oó]gio|flag|incremento|apurar)\b", re.I)
OPENING_RE = re.compile(
    r"\b(abertura|sicilian|defense|london|caro[- ]?kann|francesa|italiana|gambito|repert[oó]rio|"
    r"varia[cç][aã]o|linha)\b",
    re.I,
)
TRAINING_RE = re.compile(r"\b(puzzle|streak|sequ[eê]ncia|sem errar|perdi meu streak|puzzle of the day)\b", re.I)
QUESTION_RE = re.compile(r"\b(ser[aá]|talvez|por que|por qu[eê]|qual que|n[aã]o sei|d[uú]vida|acho que)\b", re.I)
RESEARCH_RE = re.compile(
    r"\b(wikipedia|wiki|não conheço|nao conheco|não sei quem|nao sei quem|quem é|quem foi|nome dele|nome dela|"
    r"enxadrista|jogador famoso|história do xadrez|historia do xadrez|checkmate pattern|"
    r"pesquis\w{0,12}.{0,40}(google|wikipedia|wiki|termo|nome|enxadrista|jogador)|"
    r"(buscar|busca|procurar).{0,40}(google|wikipedia|wiki|termo|nome|enxadrista|jogador))\b",
    re.I,
)
RESEARCH_LOOKUP_RE = re.compile(
    r"\b(wikipedia|wiki|pesquis\w{0,12}.{0,40}(google|wikipedia|wiki|termo|nome|enxadrista|jogador)|"
    r"(buscar|busca|procurar).{0,40}(google|wikipedia|wiki|termo|nome|enxadrista|jogador))\b",
    re.I,
)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(WORD_RE.findall(value))


def display_word_tokens(value: str) -> list[tuple[str, str]]:
    tokens = []
    for match in DISPLAY_WORD_RE.finditer(value):
        display = match.group(0)
        normalized = normalize_text(display)
        if normalized:
            tokens.append((normalized, display))
    return tokens


def partial_sequence_match(source_tokens: list[str], reference_tokens: list[str]) -> tuple[float, int]:
    if not source_tokens or not reference_tokens:
        return 0.0, 0
    window_size = min(len(reference_tokens), max(4, len(source_tokens)))
    source_text = " ".join(source_tokens)
    source_set = set(source_tokens)
    best = 0.0
    best_start = 0
    for start in range(0, max(1, len(reference_tokens) - window_size + 1)):
        candidate_tokens = reference_tokens[start : start + window_size]
        candidate_text = " ".join(candidate_tokens)
        candidate_set = set(candidate_tokens)
        sequence_score = SequenceMatcher(None, source_text, candidate_text).ratio()
        overlap_score = 0.0
        if source_set and candidate_set:
            overlap_score = 2 * len(source_set & candidate_set) / (len(source_set) + len(candidate_set))
        score = sequence_score * 0.65 + overlap_score * 0.35
        if score > best:
            best = score
            best_start = start
    return best, best_start


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def format_time(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def first_sentence(text: str, max_length: int = 180) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_length:
        return cleaned
    boundary = cleaned.rfind(". ", 0, max_length)
    if boundary < 60:
        boundary = cleaned.rfind(" ", 0, max_length)
    if boundary < 40:
        return cleaned[: max_length - 1].rstrip() + "…"
    return cleaned[:boundary].rstrip() + "…"


def transcript_data(session: str) -> tuple[str, str, list[dict[str, Any]]]:
    for suffix, label in TRANSCRIPT_SOURCES:
        data = read_json(TRANSCRIPT_DIR / f"{session}.{suffix}.json")
        if data and isinstance(data.get("blocks"), list) and data["blocks"]:
            return suffix, label, [block for block in data["blocks"] if isinstance(block, dict)]
    return "", "", []


def preferred_transcript_source(session: str) -> tuple[str, Path | None]:
    for suffix, _label in TRANSCRIPT_SOURCES:
        path = TRANSCRIPT_DIR / f"{session}.{suffix}.json"
        data = read_json(path)
        if data and isinstance(data.get("blocks"), list) and data["blocks"]:
            return suffix, path
    return "", None


def chat_messages(session: str) -> list[dict[str, Any]]:
    data = read_json(CHAT_DIR / f"{session}.json")
    if not data or not isinstance(data.get("messages"), list):
        return []
    return [message for message in data["messages"] if isinstance(message, dict)]


def available_sessions() -> list[str]:
    sessions = set()
    for path in TRANSCRIPT_DIR.glob("*.json"):
        match = re.match(r"^(\d{4})\.", path.name)
        if match:
            sessions.add(match.group(1))
    for path in CHAT_DIR.glob("*.json"):
        match = re.match(r"^(\d{4})\.json$", path.name)
        if match:
            sessions.add(match.group(1))
    return sorted(sessions)


def window_items(items: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    return [item for item in items if start <= int(item.get("seconds") or 0) < end]


def token_times(items: list[dict[str, Any]], index: int, token_count: int) -> list[int]:
    start_seconds = int(items[index].get("seconds") or 0)
    if index + 1 < len(items):
        end_seconds = int(items[index + 1].get("seconds") or start_seconds)
    else:
        end_seconds = start_seconds + 60
    end_seconds = max(start_seconds + 1, min(end_seconds, start_seconds + 120))
    if token_count <= 1:
        return [start_seconds]
    return [
        round(start_seconds + (end_seconds - start_seconds) * token_index / token_count)
        for token_index in range(token_count)
    ]


def reference_anchor(
    summary_text: str,
    fallback_seconds: int,
    reference_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    query_tokens = normalize_text(summary_text).split()[:18]
    if len(query_tokens) < 4:
        return None

    best_score = 0.0
    best_match: dict[str, Any] | None = None
    for index, item in enumerate(reference_items):
        item_seconds = int(item.get("seconds") or 0)
        if abs(item_seconds - fallback_seconds) > 240:
            continue
        item_text = str(item.get("text") or "")
        item_display_tokens = display_word_tokens(item_text)
        item_tokens = [token for token, _display in item_display_tokens]
        score, token_start = partial_sequence_match(query_tokens, item_tokens)
        if score <= best_score:
            continue
        times = token_times(reference_items, index, len(item_tokens))
        lead_in_tokens = [
            display
            for _token, display in item_display_tokens[max(0, token_start - REFERENCE_LEAD_IN_MAX_WORDS) : token_start]
        ]
        best_score = score
        best_match = {
            "seconds": times[min(token_start, len(times) - 1)] if times else item_seconds,
            "lead_in": " ".join(lead_in_tokens),
            "score": round(score, 4),
        }

    if best_match is None or best_score < 0.45:
        return None
    return best_match


def source_lead_in(anchor_seconds: int, transcript_items: list[dict[str, Any]], word_count: int = 5) -> str:
    previous_items = [
        item
        for item in transcript_items
        if int(item.get("seconds") or 0) < anchor_seconds
        and anchor_seconds - int(item.get("seconds") or 0) <= SOURCE_LEAD_IN_MAX_GAP_SECONDS
    ]
    if not previous_items:
        return ""

    text = " ".join(str(previous_items[-1].get("text") or "").split())
    sentence_parts = re.split(r"(?<=[.!?])\s+", text)
    candidate = sentence_parts[-1] if sentence_parts else text
    words = [display for _token, display in display_word_tokens(candidate)]
    if len(words) < 4 and len(sentence_parts) > 1:
        words = [display for _token, display in display_word_tokens(sentence_parts[-2])]
    return " ".join(words[-SOURCE_LEAD_IN_MAX_WORDS:])


def score_window(transcript_items: list[dict[str, Any]], chat_items: list[dict[str, Any]]) -> tuple[float, list[str]]:
    text = " ".join(str(item.get("text") or "") for item in transcript_items + chat_items)
    score = 0.0
    signals = []

    if chat_items:
        score += min(2.0, len(chat_items) * 0.35)
        signals.append(f"{len(chat_items)} mensagem(ns) no chat")
    if transcript_items and chat_items:
        score += 0.7
        signals.append("chat e fala no mesmo trecho")
    if REACTION_RE.search(text):
        score += 0.8
        signals.append("reação forte na fala")
    if MISTAKE_RE.search(text):
        score += 0.9
        signals.append("erro ou momento perdido")
    if CHESS_RE.search(text):
        score += 0.4
        signals.append("tema claro de xadrez")
    if CHAT_RE.search(text):
        score += 0.5
        signals.append("interação com o chat")
    if REVIEW_RE.search(text):
        score += 1.2
        signals.append("review ou melhor lance")
    if PLAN_RE.search(text):
        score += 0.7
        signals.append("plano ou estratégia")
    if TIME_RE.search(text):
        score += 0.6
        signals.append("pressão no relógio")
    if PLAN_RE.search(text) and TIME_RE.search(text):
        score += 0.5
        signals.append("plano sob pressão de tempo")
    if OPENING_RE.search(text):
        score += 0.8
        signals.append("abertura ou repertório")
    if TRAINING_RE.search(text):
        score += 0.8
        signals.append("treino ou puzzle streak")
    if QUESTION_RE.search(text) and (CHESS_RE.search(text) or REVIEW_RE.search(text) or OPENING_RE.search(text)):
        score += 0.4
        signals.append("raciocínio em voz alta")
    if RESEARCH_RE.search(text):
        score += 1.4
        signals.append("pesquisa ou contexto externo")
    if RESEARCH_LOOKUP_RE.search(text):
        score += 1.0
        signals.append("consulta em fonte externa")

    return score, signals


def highlight_kind(signals: list[str], text: str) -> str:
    if "pesquisa ou contexto externo" in signals:
        return "research"
    if "plano sob pressão de tempo" in signals or ("pressão no relógio" in signals and MISTAKE_RE.search(text)):
        return "time-pressure"
    if "treino ou puzzle streak" in signals:
        return "training"
    if "abertura ou repertório" in signals:
        return "opening"
    if "review ou melhor lance" in signals:
        return "review"
    if MISTAKE_RE.search(text):
        return "mistake"
    if "interação com o chat" in signals or "chat e fala no mesmo trecho" in signals:
        return "chat"
    if "tema claro de xadrez" in signals:
        return "chess"
    return "moment"


def suggest_highlights(session: str, limit: int, window_seconds: int, step_seconds: int) -> dict[str, Any]:
    transcript_source, transcript_label, transcript_items = transcript_data(session)
    reference_data = read_json(TRANSCRIPT_DIR / f"{session}.faster-whisper.json")
    reference_items = []
    if reference_data and isinstance(reference_data.get("blocks"), list):
        reference_items = [block for block in reference_data["blocks"] if isinstance(block, dict)]
    chat_items = chat_messages(session)
    if not transcript_items and not chat_items:
        fail(f"{session}: no transcript or chat data")

    max_seconds = max(
        [int(item.get("seconds") or 0) for item in transcript_items + chat_items],
        default=0,
    )
    candidates = []
    for start in range(0, max_seconds + 1, step_seconds):
        end = start + window_seconds
        window_transcript = window_items(transcript_items, start, end)
        window_chat = window_items(chat_items, start, end)
        score, signals = score_window(window_transcript, window_chat)
        if score < 1.4:
            continue

        text = " ".join(str(item.get("text") or "") for item in window_transcript)
        chat_text = " ".join(str(item.get("text") or "") for item in window_chat)
        combined_text = " ".join([text, chat_text]).strip()
        kind = highlight_kind(signals, combined_text)
        summary_text = text or chat_text or combined_text
        anchor_item = next(iter(window_transcript or window_chat), None)
        if kind == "research":
            research_item = next(
                (item for item in window_transcript if RESEARCH_RE.search(str(item.get("text") or ""))),
                None,
            )
            if research_item:
                summary_text = str(research_item.get("text") or summary_text)
                anchor_item = research_item
        anchor_seconds = int(anchor_item.get("seconds") or start) if anchor_item else start
        anchor_preroll_seconds = 0 if transcript_source.endswith(".aligned") else 8
        start_seconds = max(0, anchor_seconds - anchor_preroll_seconds)
        candidates.append(
            {
                "start_seconds": start_seconds,
                "end_seconds": min(end, max_seconds),
                "time": format_time(start_seconds),
                "duration": format_time(min(window_seconds, max(0, max_seconds - start))),
                "kind": kind,
                "score": round(score, 2),
                "summary": first_sentence(summary_text),
                "reason": "; ".join(signals),
                "signals": signals,
                "chat_count": len(window_chat),
                "transcript_count": len(window_transcript),
                "_anchor_seconds": anchor_seconds,
                "_can_refine_anchor": bool(window_transcript),
                "_summary_text": summary_text,
            }
        )

    ranked_candidates = sorted(candidates, key=lambda item: (-float(item["score"]), int(item["start_seconds"])))
    selected = []

    research_candidates = [candidate for candidate in ranked_candidates if candidate["kind"] == "research"]
    research_candidates.sort(
        key=lambda item: (
            "consulta em fonte externa" not in item["signals"],
            -float(item["score"]),
            int(item["start_seconds"]),
        )
    )
    best_research = research_candidates[0] if research_candidates else None
    if best_research:
        selected.append(best_research)

    for candidate in ranked_candidates:
        if any(abs(int(candidate["start_seconds"]) - int(existing["start_seconds"])) < window_seconds for existing in selected):
            continue
        if sum(1 for existing in selected if existing["kind"] == candidate["kind"]) >= 2:
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break

    for candidate in ranked_candidates:
        if len(selected) >= limit:
            break
        if any(abs(int(candidate["start_seconds"]) - int(existing["start_seconds"])) < window_seconds for existing in selected):
            continue
        selected.append(candidate)

    for item in selected:
        anchor_seconds = int(item.pop("_anchor_seconds", item["start_seconds"]))
        can_refine_anchor = bool(item.pop("_can_refine_anchor", False))
        summary_text = str(item.pop("_summary_text", item["summary"]))
        if transcript_source.endswith(".aligned") and reference_items and can_refine_anchor:
            reference_match = reference_anchor(summary_text, anchor_seconds, reference_items)
            reference_seconds = int(reference_match["seconds"]) if reference_match is not None else None
            refined_anchor = False
            if (
                reference_match is not None
                and reference_seconds is not None
                and anchor_seconds <= reference_seconds <= anchor_seconds + REFERENCE_ANCHOR_MAX_FORWARD_SECONDS
            ):
                item["start_seconds"] = reference_seconds
                item["time"] = format_time(reference_seconds)
                refined_anchor = True
            if (
                reference_match is not None
                and reference_seconds is not None
                and reference_match["lead_in"]
                and (refined_anchor or float(reference_match["score"]) >= REFERENCE_LEAD_IN_MIN_SCORE)
                and anchor_seconds <= reference_seconds <= anchor_seconds + REFERENCE_LEAD_IN_MAX_FORWARD_SECONDS
            ):
                item["lead_in"] = source_lead_in(anchor_seconds, transcript_items) or reference_match["lead_in"]
        if transcript_source.endswith(".aligned") and can_refine_anchor and not item.get("lead_in"):
            lead_in = source_lead_in(anchor_seconds, transcript_items)
            if lead_in:
                item["lead_in"] = lead_in

    selected.sort(key=lambda item: int(item["start_seconds"]))
    return {
        "session_number": session,
        "source": "heuristic",
        "transcript_source": transcript_source,
        "transcript_label": transcript_label,
        "limit": limit,
        "window_seconds": window_seconds,
        "step_seconds": step_seconds,
        "highlights": selected,
    }


def write_json_if_changed(path: Path, data: dict[str, Any]) -> bool:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def output_is_current(session: str, output_path: Path, args: argparse.Namespace) -> bool:
    if not output_path.exists():
        return False

    try:
        output = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(output, dict):
        return False

    transcript_source, transcript_path = preferred_transcript_source(session)
    expected = {
        "source": "heuristic",
        "transcript_source": transcript_source,
        "limit": args.limit,
        "window_seconds": args.window_seconds,
        "step_seconds": args.step_seconds,
    }
    if any(output.get(key) != value for key, value in expected.items()):
        return False

    output_mtime = output_path.stat().st_mtime
    input_paths = [path for path in [transcript_path, CHAT_DIR / f"{session}.json"] if path is not None and path.exists()]
    return all(output_mtime >= path.stat().st_mtime for path in input_paths)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suggest candidate session highlights from chat and transcript data.")
    parser.add_argument("sessions", nargs="*", help="Session number(s), e.g. 0047")
    parser.add_argument("--all", action="store_true", help="Process every session with local chat or transcript data.")
    parser.add_argument("--latest", type=int, help="Only process the latest N sessions with local chat or transcript data.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--window-seconds", type=int, default=90)
    parser.add_argument("--step-seconds", type=int, default=30)
    parser.add_argument("--force", action="store_true", help="Recompute even when the highlight output is current.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.all:
        sessions = available_sessions()
    elif args.latest is not None and args.latest > 0:
        sessions = available_sessions()[-args.latest :]
    else:
        sessions = args.sessions
    if not sessions:
        fail("provide at least one session or use --all/--latest")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    changed_count = 0
    current_count = 0
    failed_count = 0
    for session in sessions:
        output_path = args.output_dir / f"{session}.json"
        if not args.force and output_is_current(session, output_path, args):
            current_count += 1
            print(f"{session}: current {output_path}")
            continue

        try:
            output = suggest_highlights(session, args.limit, args.window_seconds, args.step_seconds)
        except SystemExit:
            failed_count += 1
            if not args.all and args.latest is None:
                raise
            continue

        changed = write_json_if_changed(output_path, output)
        if changed:
            changed_count += 1
        verb = "updated" if changed else "unchanged"
        print(f"{session}: {verb} {len(output['highlights'])} highlight candidate(s) in {output_path}")

    print(
        f"done: {len(sessions) - failed_count} processed, "
        f"{changed_count} changed, {current_count} current, {failed_count} failed"
    )
    return 1 if failed_count and not args.all and args.latest is None else 0


if __name__ == "__main__":
    raise SystemExit(main())
