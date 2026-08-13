#!/usr/bin/env python3
"""Suggest a replay offset from a manually observed video anchor."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.update_lichess_blunder_events import (
    CLK_RE,
    body_tokens,
    fetch_game,
    pgn_headers,
    session_start_utc_from_path,
    session_game_refs,
    time_control,
    token_is_move_number,
)


CONTENT_DIR = ROOT / "content" / "fcz"
TIMELINE_DIR = ROOT / "data" / "fcz" / "lichess_blunders"
TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


class NoCalibrationData(RuntimeError):
    pass


def read_front_matter(path: Path) -> dict[str, Any]:
    import tomllib

    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return {}
    end = text.find("\n+++", 4)
    if end == -1:
        return {}
    return tomllib.loads(text[4:end])


def write_front_matter_offset(path: Path, offset: int) -> int | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        raise RuntimeError(f"front matter TOML não encontrado em {path}")
    end = text.find("\n+++", 4)
    if end == -1:
        raise RuntimeError(f"front matter TOML sem fechamento em {path}")

    front_matter = text[4:end]
    old_match = re.search(r"(?m)^lichess_video_offset_seconds\s*=\s*([+-]?\d+)\s*$", front_matter)
    old_offset = int(old_match.group(1)) if old_match else None
    replacement = f"lichess_video_offset_seconds = {offset}"

    if old_match:
        if old_offset == offset:
            return old_offset
        front_matter = (
            front_matter[: old_match.start()]
            + replacement
            + front_matter[old_match.end() :]
        )
    else:
        extra_match = re.search(r"(?m)^\[extra\]\s*$", front_matter)
        if not extra_match:
            raise RuntimeError(f"seção [extra] não encontrada em {path}")
        status_match = re.search(r"(?m)^status_tone\s*=.*$", front_matter[extra_match.end() :])
        if status_match:
            insert_at = extra_match.end() + status_match.end()
            front_matter = front_matter[:insert_at] + f"\n{replacement}" + front_matter[insert_at:]
        else:
            insert_at = extra_match.end()
            front_matter = front_matter[:insert_at] + f"\n{replacement}" + front_matter[insert_at:]

    path.write_text(text[:4] + front_matter + text[end:], encoding="utf-8")
    return old_offset


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

    refs = session_game_refs(content_path)
    if not refs:
        raise NoCalibrationData(
            f"a sessão {session} não tem partida Lichess registrada; nada para calibrar"
        )
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
    try:
        payload = fetch_game(refs[0].game_id, "", 20)
    except OSError as error:
        raise RuntimeError(f"não foi possível buscar o PGN de {refs[0].game_id}: {error}") from error
    elapsed, white_clock = second_white_move_elapsed(str(payload.get("pgn") or ""))
    return content_path, raw_seconds + elapsed, configured_offset, elapsed, white_clock


def configured_video_offset(extra: dict[str, Any]) -> int:
    try:
        return int(extra.get("lichess_video_offset_seconds") or 0)
    except (TypeError, ValueError):
        return 0


def puzzle_of_the_day_anchor(session: str) -> tuple[Path, int, int, str]:
    content_path = CONTENT_DIR / f"{session}.md"
    if not content_path.exists():
        raise RuntimeError(f"sessão não encontrada: {session}")

    front_matter = read_front_matter(content_path)
    extra = front_matter.get("extra")
    if not isinstance(extra, dict):
        raise RuntimeError(f"seção [extra] não encontrada em {content_path}")

    raw_recorded_at = str(extra.get("puzzle_of_the_day_recorded_at") or "").strip()
    if not raw_recorded_at:
        raise NoCalibrationData(
            f"a sessão {session} não tem puzzle_of_the_day_recorded_at; nada para calibrar"
        )
    try:
        recorded_at = datetime.fromisoformat(raw_recorded_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError(f"puzzle_of_the_day_recorded_at inválido: {raw_recorded_at}") from error
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)

    refs = session_game_refs(content_path)
    session_start = session_start_utc_from_path(content_path, refs)
    if session_start is None:
        raise RuntimeError("não foi possível descobrir o início do vídeo da sessão")

    raw_anchor = round((recorded_at.astimezone(timezone.utc) - session_start).total_seconds())
    if raw_anchor < 0:
        raise RuntimeError("puzzle_of_the_day_recorded_at ficou antes do início do vídeo")
    return content_path, raw_anchor, configured_video_offset(extra), raw_recorded_at


def prompt_observed_timestamp(message: str) -> int:
    print(message)
    print("Formato aceito: MM:SS ou H:MM:SS")

    while True:
        observed = input("Timestamp observado: ").strip()
        observed_seconds = parse_timestamp(observed)
        if observed_seconds is not None:
            return observed_seconds
        print("Timestamp inválido. Use, por exemplo, 28:42.")


def apply_suggested_offset(content_path: Path, raw_anchor: int, observed_seconds: int, no_write: bool) -> None:
    suggested = observed_seconds - raw_anchor
    print()
    print(f"Offset sugerido: {suggested:+d}s")
    print(f"Com esse offset, a âncora ficaria em {format_timestamp(raw_anchor + suggested)}.")
    if no_write:
        print("Nenhum arquivo foi alterado.")
        return
    try:
        previous = write_front_matter_offset(content_path, suggested)
    except RuntimeError as error:
        raise RuntimeError(str(error)) from error
    if previous == suggested:
        print(f"Offset já estava configurado em {suggested:+d}s.")
    elif previous is None:
        print(f"Offset gravado em {content_path.relative_to(ROOT)}: {suggested:+d}s.")
    else:
        print(f"Offset atualizado em {content_path.relative_to(ROOT)}: {previous:+d}s -> {suggested:+d}s.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sugere um offset comparando uma âncora bruta da sessão com o timestamp observado no vídeo."
    )
    parser.add_argument("session", help="Número da sessão, por exemplo 0052")
    parser.add_argument(
        "--anchor",
        choices=("first-game", "puzzle-of-the-day"),
        default="first-game",
        help="Âncora usada para calibrar: relógio da primeira partida ou clique no Puzzle do dia.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Só imprimir o offset sugerido, sem atualizar o Markdown da sessão.",
    )
    parser.add_argument(
        "--exit-code-on-skip",
        type=int,
        default=0,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    session = str(args.session).zfill(4)

    try:
        if args.anchor == "puzzle-of-the-day":
            content_path, raw_anchor, configured_offset, recorded_at = puzzle_of_the_day_anchor(session)
        else:
            content_path, raw_anchor, configured_offset, elapsed, white_clock = first_game_anchor(session)
    except NoCalibrationData as notice:
        print(str(notice))
        return args.exit_code_on_skip
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        parser.error(str(error))

    print(f"Sessão {session}")
    if configured_offset:
        print(f"Offset atualmente configurado: {configured_offset:+d}s")
    if args.anchor == "puzzle-of-the-day":
        print(f"Puzzle do dia registrado pelo userscript em: {recorded_at}")
        print(f"Âncora bruta calculada para esse clique: {format_timestamp(raw_anchor)}")
        observed_seconds = prompt_observed_timestamp(
            "Informe o timestamp do vídeo em que aparece o clique/registro do Puzzle do dia."
        )
    else:
        print(f"Tempo estimado após o segundo lance das brancas: +{elapsed}s")
        print(f"Âncora bruta calculada para essa jogada: {format_timestamp(raw_anchor)}")
        clock_parts = white_clock.split(":")
        expected_clock = ":".join(clock_parts[-2:])
        observed_seconds = prompt_observed_timestamp(
            "Informe o timestamp do vídeo em que as brancas finalizam o segundo movimento "
            f"e o relógio branco mostra aproximadamente {expected_clock}."
        )
    try:
        apply_suggested_offset(content_path, raw_anchor, observed_seconds, args.no_write)
    except RuntimeError as error:
        parser.error(str(error))
    print(f"Para regenerar a timeline: just update-session-capivaradas {session}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
