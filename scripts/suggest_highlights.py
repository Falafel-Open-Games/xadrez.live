#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT_DIR = ROOT / "data" / "transcripts"
CHAT_DIR = ROOT / "data" / "chat_replays"
OUTPUT_DIR = ROOT / "data" / "highlights"

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
        if kind == "research":
            research_item = next(
                (item for item in window_transcript if RESEARCH_RE.search(str(item.get("text") or ""))),
                None,
            )
            if research_item:
                summary_text = str(research_item.get("text") or summary_text)
        candidates.append(
            {
                "start_seconds": start,
                "end_seconds": min(end, max_seconds),
                "time": format_time(start),
                "duration": format_time(min(window_seconds, max(0, max_seconds - start))),
                "kind": kind,
                "score": round(score, 2),
                "summary": first_sentence(summary_text),
                "reason": "; ".join(signals),
                "signals": signals,
                "chat_count": len(window_chat),
                "transcript_count": len(window_transcript),
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

    selected.sort(key=lambda item: int(item["start_seconds"]))
    return {
        "session_number": session,
        "source": "heuristic",
        "transcript_source": transcript_source,
        "transcript_label": transcript_label,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suggest candidate session highlights from chat and transcript data.")
    parser.add_argument("sessions", nargs="*", help="Session number(s), e.g. 0047")
    parser.add_argument("--all", action="store_true", help="Process every session with local chat or transcript data.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--window-seconds", type=int, default=90)
    parser.add_argument("--step-seconds", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sessions = available_sessions() if args.all else args.sessions
    if not sessions:
        fail("provide at least one session or use --all")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    changed_count = 0
    failed_count = 0
    for session in sessions:
        try:
            output = suggest_highlights(session, args.limit, args.window_seconds, args.step_seconds)
        except SystemExit:
            failed_count += 1
            if not args.all:
                raise
            continue

        output_path = args.output_dir / f"{session}.json"
        changed = write_json_if_changed(output_path, output)
        if changed:
            changed_count += 1
        verb = "updated" if changed else "unchanged"
        print(f"{session}: {verb} {len(output['highlights'])} highlight candidate(s) in {output_path}")

    print(f"done: {len(sessions) - failed_count} processed, {changed_count} changed, {failed_count} failed")
    return 1 if failed_count and not args.all else 0


if __name__ == "__main__":
    raise SystemExit(main())
