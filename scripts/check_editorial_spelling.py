#!/usr/bin/env python3
"""Check editorial Markdown spelling with the local Hunspell dictionary."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IGNORE = ROOT / "data" / "editorial_spelling_ignore.txt"
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]+(?:['’-][A-Za-zÀ-ÿ]+)*")
URL_RE = re.compile(r"https?://[^\s>)\]}\"']+")
USERNAME_RE = re.compile(r"@[A-Za-z0-9][A-Za-z0-9_.-]*")
METADATA_NAME_RE = re.compile(r'^\s*name\s*=\s*["\']([^"\']+)["\']')
EDITORIAL_KEYS = {
    "title",
    "description",
    "summary_title",
    "tagline",
    "status",
    "note",
    "thumbnail_notes",
}


def editorial_paths() -> list[Path]:
    paths = list((ROOT / "content").glob("*.md"))
    paths.extend((ROOT / "content" / "fcz").glob("[0-9][0-9][0-9][0-9].md"))
    return sorted(paths)


def load_ignore(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip().casefold()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def without_accents(word: str) -> str:
    normalized = unicodedata.normalize("NFD", word.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def accent_only_suggestion(word: str, suggestions: list[str]) -> str:
    if not suggestions:
        return ""
    suggestion = suggestions[0]
    if suggestion.casefold() != word.casefold() and without_accents(suggestion) == without_accents(word):
        return suggestion
    return ""


def editorial_lines(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    selected: list[tuple[int, str]] = []
    in_front_matter = bool(lines and lines[0].strip() == "+++")
    in_code_block = False
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if in_front_matter:
            if line_number == 1:
                continue
            if stripped == "+++":
                in_front_matter = False
                continue
            if not stripped or stripped.startswith("#"):
                continue
            key_match = re.match(r"([A-Za-z0-9_]+)\s*=", stripped)
            if key_match and key_match.group(1) in EDITORIAL_KEYS:
                selected.append((line_number, line))
            continue
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not in_code_block:
            selected.append((line_number, line))
    return selected


def word_occurrences(paths: list[Path], ignored: set[str]) -> tuple[dict[str, list[tuple[Path, int, str]]], list[str]]:
    occurrences: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
    words: set[str] = set()
    metadata_usernames = set(ignored)
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            name_match = METADATA_NAME_RE.match(line)
            if name_match:
                metadata_usernames.update(
                    match.group(0).casefold() for match in WORD_RE.finditer(name_match.group(1))
                )
    for path in paths:
        for line_number, line in editorial_lines(path):
            editorial_line = USERNAME_RE.sub(" ", URL_RE.sub(" ", line))
            for match in WORD_RE.finditer(editorial_line):
                word = match.group(0)
                normalized = word.casefold()
                if normalized in metadata_usernames or len(normalized) <= 2 or word.isupper():
                    continue
                occurrences[normalized].append((path, line_number, word))
                words.add(normalized)
    return occurrences, sorted(words)


def hunspell_words(words: list[str], dictionary: str) -> dict[str, list[str]]:
    try:
        result = subprocess.run(
            ["hunspell", "-a", "-d", dictionary],
            input="\n".join(words) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("hunspell não está instalado") from error
    if result.returncode not in (0, 1):
        detail = result.stderr.strip() or f"código {result.returncode}"
        raise RuntimeError(f"não foi possível abrir o dicionário {dictionary}: {detail}")

    unknown: dict[str, list[str]] = {}
    responses = [line for line in result.stdout.splitlines() if line and not line.startswith("@(#)")]
    if len(responses) < len(words):
        detail = result.stderr.strip() or "resposta incompleta do hunspell"
        raise RuntimeError(f"não foi possível verificar o dicionário {dictionary}: {detail}")
    for word, response in zip(words, responses):
        if response.startswith("*"):
            continue
        if response.startswith("&"):
            suggestions = response.split(":", 1)[-1].strip().split(", ")
            unknown[word] = suggestions
        elif response.startswith("#"):
            unknown[word] = []
    return unknown


def hunspell_misspelled(words: list[str], dictionary: str) -> set[str]:
    try:
        result = subprocess.run(
            ["hunspell", "-l", "-d", dictionary],
            input="\n".join(words) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("hunspell não está instalado") from error
    if result.returncode not in (0, 1):
        detail = result.stderr.strip() or f"código {result.returncode}"
        raise RuntimeError(f"não foi possível abrir o dicionário {dictionary}: {detail}")
    return {line.strip().casefold() for line in result.stdout.splitlines() if line.strip()}


def find_suspects(
    paths: list[Path], ignored: set[str], dictionary: str, english_dictionary: str = "en_US"
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[tuple[Path, int, str]]]]:
    occurrences, words = word_occurrences(paths, ignored)
    misspelled = hunspell_misspelled(words, dictionary)
    unknown = hunspell_words(sorted(misspelled), dictionary)
    if english_dictionary:
        try:
            english_unknown = hunspell_misspelled(words, english_dictionary)
        except RuntimeError as error:
            print(f"Aviso: filtro inglês indisponível: {error}", file=sys.stderr)
        else:
            unknown = {word: suggestions for word, suggestions in unknown.items() if word in english_unknown}
    easy = {
        word: suggestion
        for word, suggestions in unknown.items()
        if (suggestion := accent_only_suggestion(word, suggestions))
    }
    unknown = {word: suggestions for word, suggestions in unknown.items() if word not in easy}
    return easy, unknown, occurrences


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check editorial Markdown spelling with Hunspell.")
    parser.add_argument("paths", nargs="*", type=Path, help="Optional Markdown files; defaults to editorial content.")
    parser.add_argument("--dictionary", default="pt_BR", help="Hunspell dictionary name (default: pt_BR).")
    parser.add_argument("--english-dictionary", default="en_US", help="Optional dictionary used to allow exact English words.")
    parser.add_argument("--no-english-filter", action="store_true", help="Do not filter words accepted by the English dictionary.")
    parser.add_argument("--ignore-file", type=Path, default=DEFAULT_IGNORE)
    parser.add_argument("--all", action="store_true", help="Print every occurrence instead of grouping by word.")
    parser.add_argument("--limit", type=int, default=80, help="Maximum grouped findings to print (default: 80).")
    parser.add_argument("--fail-on-findings", action="store_true", help="Exit with code 1 when findings exist.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = [path if path.is_absolute() else ROOT / path for path in (args.paths or editorial_paths())]
    try:
        easy, unknown, occurrences = find_suspects(
            paths,
            load_ignore(args.ignore_file),
            args.dictionary,
            "" if args.no_english_filter else args.english_dictionary,
        )
    except RuntimeError as error:
        print(f"Erro: {error}", file=sys.stderr)
        print("Instale um dicionário pt_BR e rode novamente com --dictionary pt_BR.", file=sys.stderr)
        return 2

    if easy:
        print("Possíveis correções simples (somente acentos):")
        for word in sorted(easy):
            locations = ", ".join(
                f"{path.relative_to(ROOT)}:{line_number}"
                for path, line_number, _original in occurrences[word][:3]
            )
            extra = f" (+{len(occurrences[word]) - 3})" if len(occurrences[word]) > 3 else ""
            print(f"{word} -> {easy[word]} ({len(occurrences[word])}x); {locations}{extra}")
        print()

    findings = sum(len(occurrences[word]) for word in unknown)
    if args.all:
        for word in sorted(unknown):
            suggestions = ", ".join(unknown[word]) or "sem sugestão"
            for path, line_number, original in occurrences[word]:
                print(f"{path.relative_to(ROOT)}:{line_number}: {original} -> {suggestions}")
    else:
        words_to_print = sorted(unknown)[: max(0, args.limit)]
        for word in words_to_print:
            suggestions = ", ".join(unknown[word]) or "sem sugestão"
            locations = ", ".join(
                f"{path.relative_to(ROOT)}:{line_number}"
                for path, line_number, _original in occurrences[word][:3]
            )
            extra = f" (+{len(occurrences[word]) - 3})" if len(occurrences[word]) > 3 else ""
            print(f"{word} ({len(occurrences[word])}x) -> {suggestions}; {locations}{extra}")
        omitted = len(unknown) - len(words_to_print)
        if omitted > 0:
            print(f"... {omitted} palavra(s) única(s) omitida(s); use --all ou --limit N.", file=sys.stderr)
    print(f"{findings} ocorrência(s), {len(unknown)} palavra(s) única(s).", file=sys.stderr)
    return 1 if args.fail_on_findings and findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
