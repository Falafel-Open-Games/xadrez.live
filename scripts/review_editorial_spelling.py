#!/usr/bin/env python3
"""Interactively review spelling findings and save approved decisions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from check_editorial_spelling import DEFAULT_IGNORE, editorial_paths, find_suspects, load_ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "data" / "editorial_spelling_approvals.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review editorial spelling findings interactively.")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--dictionary", default="pt_BR")
    parser.add_argument("--english-dictionary", default="en_US")
    parser.add_argument("--ignore-file", type=Path, default=DEFAULT_IGNORE)
    parser.add_argument("--cache-file", type=Path, default=DEFAULT_CACHE)
    return parser.parse_args()


def load_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(word): str(replacement) for word, replacement in data.get("approved", {}).items()}


def save_cache(path: Path, approved: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"approved": dict(sorted(approved.items()))}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add_to_ignore(path: Path, word: str) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if word.casefold() in {line.strip().casefold() for line in existing}:
        return
    with path.open("a", encoding="utf-8") as handle:
        if existing and existing[-1].strip():
            handle.write("\n")
        handle.write(f"{word}\n")


def location_text(occurrences: dict[str, list[tuple[Path, int, str]]], word: str) -> str:
    return ", ".join(
        f"{path.relative_to(ROOT)}:{line_number}"
        for path, line_number, _original in occurrences[word][:5]
    )


def review_word(
    word: str,
    suggestions: list[str],
    default_replacement: str,
    occurrences: dict[str, list[tuple[Path, int, str]]],
) -> str:
    print(f"\n{word} ({len(occurrences[word])}x) -> {default_replacement or 'sem sugestão'}")
    for index, suggestion in enumerate(suggestions, start=1):
        print(f"  {index}. {suggestion}")
    print(f"  locais: {location_text(occurrences, word)}")
    while True:
        answer = input("  [s]kip [a]pprove [c]ustom [d]ictionary [q]uit: ").strip().casefold()
        if answer in {"s", "q", "d"}:
            return answer
        if answer == "c":
            replacement = input("  substituição: ").strip()
            if replacement:
                return f"a:{replacement}"
            print("  a substituição não pode ficar vazia.")
            continue
        if answer == "a" and default_replacement:
            return f"a:{default_replacement}"
        if answer.startswith("a") and answer[1:].isdigit():
            index = int(answer[1:]) - 1
            if 0 <= index < len(suggestions):
                return f"a:{suggestions[index]}"
        print("  opção inválida; use s, a, c, d, q ou aN para escolher outra sugestão.")


def main() -> int:
    args = parse_args()
    paths = [path if path.is_absolute() else ROOT / path for path in (args.paths or editorial_paths())]
    try:
        easy, unknown, occurrences = find_suspects(
            paths, load_ignore(args.ignore_file), args.dictionary, args.english_dictionary
        )
    except RuntimeError as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 2

    approved = load_cache(args.cache_file)
    groups = [(word, [replacement], replacement) for word, replacement in sorted(easy.items())]
    groups.extend((word, suggestions, suggestions[0] if suggestions else "") for word, suggestions in sorted(unknown.items()))
    for word, suggestions, default_replacement in groups:
        if word in approved:
            continue
        action = review_word(word, suggestions, default_replacement, occurrences)
        if action == "q":
            break
        if action == "d":
            add_to_ignore(args.ignore_file, word)
        elif action.startswith("a:"):
            approved[word] = action[2:]
            save_cache(args.cache_file, approved)
    print(f"Aprovadas no cache: {len(approved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
