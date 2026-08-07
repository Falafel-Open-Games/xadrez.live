#!/usr/bin/env python3
"""Suggest a replay offset from a manually observed first-game clock anchor."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.update_lichess_blunder_events import (
    CLK_RE,
    body_tokens,
    fetch_game,
    pgn_headers,
    session_game_refs,
    time_control,
    token_is_move_number,
)


CONTENT_DIR = ROOT / "content" / "fcz"
TIMELINE_DIR = ROOT / "data" / "fcz" / "lichess_blunders"
TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


def read_front_matter(path: Path) -> dict[str, Any]:
    import tomllib

    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return {}
    end = text.find("\n+++", 4)
    if end == -1:
        return {}
    return tomllib.loads(text[4:end])


def parse_timestamp(value: str) -> int | None:
    match = TIME_RE.fullmatch(value.strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    minutes = int(minutes)
    seconds = int(seconds)
    if seconds >= 60 or minutes >= 60:
        return None
    return int(hours or 0) * 3600 + minutes * 60 + seconds


def format_timestamp(seconds: int) -> str:
    minutes, seconds = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def second_white_move_elapsed(pgn: str) -> tuple[int, str]:
    headers = pgn_headers(pgn)
    initial, increment = time_control(headers)
    if not initial:
        raise RuntimeError("time control da primeira partida não permite calcular o relógio")

    consumed = {"white": 0, "black": 0}
    white_clock = ""
    ply = 0
    tokens = body_tokens(pgn)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("{") or token_is_move_number(token) or token in {"1-0", "0-1", "1/2-1/2", "*"}:
            index += 1
            continue
        ply += 1
        color = "white" if ply % 2 == 1 else "black"
        lookahead = index + 1
        while lookahead < len(tokens) and tokens[lookahead].startswith("{"):
            for comment in [tokens[lookahead].strip("{} ")]:
                clock_match = CLK_RE.search(comment)
                if clock_match:
                    if ply == 3 and color == "white":
                        white_clock = clock_match.group(1)
                    moves_made = (ply + 1) // 2 if color == "white" else ply // 2
                    consumed[color] = max(0, initial + moves_made * increment - _clock_seconds(clock_match.group(1)))
            lookahead += 1
        index = lookahead
        if ply == 3:
            if not white_clock:
                raise RuntimeError("segundo movimento das brancas não tem relógio no PGN")
            return consumed["white"] + consumed["black"], white_clock
    raise RuntimeError("PGN não tem o segundo movimento das brancas com relógio")


def _clock_seconds(value: str) -> int:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def first_game_anchor(session: str) -> tuple[Path, int, int, int, str]:
    content_path = CONTENT_DIR / f"{session}.md"
    timeline_path = TIMELINE_DIR / f"{session}.json"
    if not content_path.exists():
        raise RuntimeError(f"sessão não encontrada: {session}")
    if not timeline_path.exists():
        raise RuntimeError(f"timeline não encontrada: {timeline_path}")

    front_matter = read_front_matter(content_path)
    extra = front_matter.get("extra")
    configured_offset = 0
    if isinstance(extra, dict):
        try:
            configured_offset = int(extra.get("lichess_video_offset_seconds") or 0)
        except (TypeError, ValueError):
            pass

    data = json.loads(timeline_path.read_text(encoding="utf-8"))
    starts = [
        event
        for event in data.get("timeline", [])
        if isinstance(event, dict)
        and event.get("kind") == "game_start"
        and int(event.get("game_index") or 0) == 1
    ]
    if not starts:
        raise RuntimeError(f"a timeline de {session} não tem início da primeira partida")
    generated_seconds = int(starts[0]["seconds"])
    raw_seconds = generated_seconds - configured_offset
    refs = session_game_refs(content_path)
    if not refs:
        raise RuntimeError(f"a sessão {session} não tem uma partida Lichess válida")
    try:
        payload = fetch_game(refs[0].game_id, "", 20)
    except OSError as error:
        raise RuntimeError(f"não foi possível buscar o PGN de {refs[0].game_id}: {error}") from error
    elapsed, white_clock = second_white_move_elapsed(str(payload.get("pgn") or ""))
    return content_path, raw_seconds + elapsed, configured_offset, elapsed, white_clock


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sugere um offset comparando o início bruto da primeira partida com o relógio observado no vídeo."
    )
    parser.add_argument("session", help="Número da sessão, por exemplo 0052")
    args = parser.parse_args()
    session = str(args.session).zfill(4)

    try:
        _, raw_anchor, configured_offset, elapsed, white_clock = first_game_anchor(session)
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        parser.error(str(error))

    print(f"Sessão {session}")
    print(f"Tempo estimado após o segundo lance das brancas: +{elapsed}s")
    print(f"Âncora bruta calculada para essa jogada: {format_timestamp(raw_anchor)}")
    if configured_offset:
        print(f"Offset atualmente configurado: {configured_offset:+d}s")
    clock_parts = white_clock.split(":")
    expected_clock = ":".join(clock_parts[-2:])
    print(
        "Informe o timestamp do vídeo em que as brancas finalizam o segundo movimento "
        f"e o relógio branco mostra aproximadamente {expected_clock}."
    )
    print("Formato aceito: MM:SS ou H:MM:SS")

    while True:
        observed = input("Timestamp observado: ").strip()
        observed_seconds = parse_timestamp(observed)
        if observed_seconds is not None:
            break
        print("Timestamp inválido. Use, por exemplo, 28:42.")

    suggested = observed_seconds - raw_anchor
    print()
    print(f"Offset sugerido: {suggested:+d}s")
    print(f"Com esse offset, a âncora ficaria em {format_timestamp(raw_anchor + suggested)}.")
    print("Nenhum arquivo foi alterado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
