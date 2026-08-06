#!/usr/bin/env python3
"""Preview or apply approved editorial spelling replacements."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Callable

from check_editorial_spelling import DEFAULT_IGNORE, ROOT, URL_RE, USERNAME_RE, WORD_RE, editorial_lines, editorial_paths


DEFAULT_CACHE = ROOT / "data" / "editorial_spelling_approvals.json"
GREEN = "\033[1;32m"
RESET = "\033[0m"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or apply approved editorial spelling replacements.")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--cache-file", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--write", action="store_true", help="Write replacements to the Markdown files.")
    return parser.parse_args()


def load_approvals(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(word).casefold(): str(replacement) for word, replacement in data.get("approved", {}).items()}


def replace_line(
    line: str,
    approvals: dict[str, str],
    confirm: Callable[[str, str, str], bool] | None = None,
) -> tuple[str, list[tuple[str, str, str]]]:
    protected = [match.span() for pattern in (URL_RE, USERNAME_RE) for match in pattern.finditer(line)]

    def is_protected(start: int, end: int) -> bool:
        return any(start < protected_end and end > protected_start for protected_start, protected_end in protected)

    changes: list[tuple[str, str, str]] = []

    def replacement(match: re.Match[str]) -> str:
        original = match.group(0)
        word = original.casefold()
        if word not in approvals or is_protected(match.start(), match.end()):
            return original
        new = approvals[word]
        if original[:1].isupper():
            new = new[:1].upper() + new[1:]
        if new == original:
            return original
        tokens = list(WORD_RE.finditer(line))
        token_index = next(index for index, token in enumerate(tokens) if token.start() == match.start())
        context_tokens = tokens[max(0, token_index - 4) : token_index + 5]
        context_start = context_tokens[0].start()
        context_end = context_tokens[-1].end()
        context = line[context_start:context_end].replace("\n", " ")
        relative_start = match.start() - context_start
        relative_end = relative_start + len(original)
        context = f"{context[:relative_start]}{GREEN}{new}{RESET}{context[relative_end:]}".strip()
        if confirm is not None and not confirm(original, new, context):
            return original
        changes.append((original, new, context))
        return new

    return WORD_RE.sub(replacement, line), changes


def main() -> int:
    args = parse_args()
    if not args.cache_file.exists():
        print(f"Cache não encontrado: {args.cache_file}")
        return 2
    approvals = load_approvals(args.cache_file)
    paths = [path if path.is_absolute() else ROOT / path for path in (args.paths or editorial_paths())]
    changed_files = 0
    changed_occurrences = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        eligible_lines = {line_number for line_number, _line in editorial_lines(path)}
        lines = text.splitlines(keepends=True)
        output: list[str] = []
        file_changes: list[tuple[int, str, str, str]] = []
        for line_number, line in enumerate(lines, start=1):
            if line_number not in eligible_lines:
                output.append(line)
                continue
            def confirm(original: str, new: str, context: str) -> bool:
                try:
                    answer = input(
                        f"{path.relative_to(ROOT)}:{line_number}: {original} -> {new} | ... {context} ... [Y/n] "
                    ).strip().casefold()
                except EOFError:
                    return False
                return answer not in {"n", "no"}

            new_line, changes = replace_line(line, approvals, confirm if args.write else None)
            output.append(new_line)
            for old, new, context in changes:
                file_changes.append((line_number, old, new, context))
        if not file_changes:
            continue
        changed_files += 1
        changed_occurrences += len(file_changes)
        for line_number, old, new, context in file_changes:
            print(f"{path.relative_to(ROOT)}:{line_number}: {old} -> {new} | ... {context} ...")
        if args.write:
            path.write_text("".join(output), encoding="utf-8")
    mode = "Aplicadas" if args.write else "Encontradas para aplicar"
    print(f"{mode}: {changed_occurrences} ocorrência(s) em {changed_files} arquivo(s).")
    if not args.write:
        print("Dry-run: use --write para gravar as substituições.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
