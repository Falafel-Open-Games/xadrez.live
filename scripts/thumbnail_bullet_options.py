#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from update_youtube_chapters import ENV_PATH, load_env_file
from wrap_session import read_session, write_session
from youtube_title_options import (
    CHOICES_PATH,
    OPENAI_RESPONSES_URL,
    read_choices,
    response_text,
    session_context,
    unique_options,
    write_choices,
)


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
MAX_BULLETS = 3
MAX_BULLET_LENGTH = 28
FORBIDDEN_BULLET_RE = re.compile(
    r"\bpts?\b|^\d+\s*pontos?$|\bstorm\b|\bstreak\b|\bpuzzles?\b|\bpuzzle\b|\btreino\b|\bprática\b",
    re.I,
)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def clean_bullet(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" -|:;.\"'")
    if len(value) <= MAX_BULLET_LENGTH:
        return value
    return value[:MAX_BULLET_LENGTH].rsplit(" ", 1)[0].strip() or value[:MAX_BULLET_LENGTH].strip()


def valid_bullet(value: str) -> bool:
    if not value:
        return False
    if FORBIDDEN_BULLET_RE.search(value):
        return False
    if re.fullmatch(r"[\d\s:/+-]+", value):
        return False
    return True


def clean_bullet_set(values: list[Any]) -> list[str]:
    bullets = []
    for value in values:
        bullet = clean_bullet(str(value))
        if valid_bullet(bullet):
            bullets.append(bullet)
    return unique_options(bullets, MAX_BULLETS)


def complete_bullet_set(values: list[Any], extras: list[str] | None = None) -> list[str]:
    bullets = clean_bullet_set(values)
    if len(bullets) < MAX_BULLETS:
        bullets = clean_bullet_set([*bullets, *(extras or []), "rapid 10+0", "análise real"])
    return bullets


def cache_item(session: str) -> dict[str, Any]:
    data = read_choices()
    sessions = data.setdefault("sessions", {})
    session_data = sessions.setdefault(session, {})
    item = session_data.setdefault("thumbnail_bullets", {})
    return item


def cached_options(session: str) -> list[list[str]]:
    item = cache_item(session)
    options = item.get("options")
    if not isinstance(options, list):
        return []
    cleaned = []
    for option in options:
        if isinstance(option, list):
            bullets = clean_bullet_set(option)
            if len(bullets) == MAX_BULLETS:
                cleaned.append(bullets)
    if cleaned != options:
        remember_options(session, cleaned)
    return cleaned


def selected_bullets(session: str) -> list[str]:
    item = cache_item(session)
    selected = item.get("selected")
    bullets = clean_bullet_set(selected) if isinstance(selected, list) else []
    return bullets if len(bullets) == MAX_BULLETS else []


def remember_options(session: str, options: list[list[str]]) -> None:
    data = read_choices()
    item = data.setdefault("sessions", {}).setdefault(session, {}).setdefault("thumbnail_bullets", {})
    item["options"] = options
    write_choices(data)


def remember_selected(session: str, bullets: list[str]) -> None:
    if len(clean_bullet_set(bullets)) != MAX_BULLETS:
        fail(f"thumbnail requires exactly {MAX_BULLETS} valid bullets")
    data = read_choices()
    item = data.setdefault("sessions", {}).setdefault(session, {}).setdefault("thumbnail_bullets", {})
    options = item.get("options") if isinstance(item.get("options"), list) else []
    if bullets and bullets not in options:
        item["options"] = [bullets, *options]
    item["selected"] = bullets
    write_choices(data)


def current_thumbnail_notes(session: str) -> list[str]:
    _path, data, _body = read_session(session)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return []
    raw = extra.get("thumbnail_notes")
    if not isinstance(raw, list):
        return []
    bullets = clean_bullet_set(raw)
    return bullets if len(bullets) == MAX_BULLETS else []


def write_thumbnail_notes(session: str, bullets: list[str]) -> bool:
    if len(clean_bullet_set(bullets)) != MAX_BULLETS:
        fail(f"thumbnail requires exactly {MAX_BULLETS} valid bullets")
    path, data, body = read_session(session)
    extra = data.setdefault("extra", {})
    if not isinstance(extra, dict):
        fail(f"{session}: [extra] is not a table")
    previous = current_thumbnail_notes(session)
    extra["thumbnail_notes"] = bullets
    write_session(path, data, body)
    return previous != bullets


def og_image_path(session: str) -> Path | None:
    path = CONTENT_DIR / f"{session}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return None
    end = text.find("\n+++", 4)
    if end == -1:
        return None
    data = tomllib.loads(text[4:end])
    extra = data.get("extra")
    if not isinstance(extra, dict):
        return None
    raw = str(extra.get("og_image") or "").strip()
    if not raw:
        return None
    if raw.startswith("/"):
        return ROOT / "static" / raw.removeprefix("/")
    return ROOT / raw


def fallback_options(context: dict[str, Any], count: int) -> list[list[str]]:
    options: list[list[str]] = []
    description = str(context.get("description") or "")
    lowered = description.casefold()
    for game in context.get("games") or []:
        if not isinstance(game, dict):
            continue
        opening = str(game.get("opening") or "").strip()
        result = str(game.get("result") or "").strip()
        note = str(game.get("note") or "").casefold()
        bullets = []
        if opening:
            bullets.append(opening.split(":", 1)[0])
        if result:
            bullets.append({"win": "vitória", "loss": "derrota", "draw": "empate"}.get(result, result))
        if "tempo" in note:
            bullets.append("relógio")
        if "captura" in note:
            bullets.append("captura perdida")
        if "mate" in note:
            bullets.append("mate no final")
        if "a3" in note:
            bullets.append("a3 no lance 6")
        if "bxc6" in note or "bxc6" in lowered:
            bullets.append("Bxc6 era melhor")
        if bullets:
            options.append(complete_bullet_set(bullets, ["decisão crítica", "final revisado", "meio-jogo tenso"]))

    if "mate" in lowered:
        options.append(complete_bullet_set(["mate no final", "cálculo na rapid", "vitória com brancas"]))
    if "tempo" in lowered:
        options.append(complete_bullet_set(["relógio apertou", "vantagem escapou", "final no tempo"]))
    options.append(complete_bullet_set(["partida rapid", "decisão crítica", "final revisado"]))
    return unique_bullet_sets(options, count)


def prompt_for_model(context: dict[str, Any], count: int) -> str:
    compact = {
        "session": context["session"],
        "summary_title": context["summary_title"],
        "games": [
            {
                "result": game.get("result"),
                "color": game.get("color"),
                "opening": game.get("opening"),
                "note": game.get("note"),
            }
            for game in context.get("games") or []
            if isinstance(game, dict)
        ],
        "game_timeline": [
            event
            for event in context.get("timeline") or []
            if isinstance(event, dict) and event.get("kind") in {"game_start", "game_end", "blunder"}
        ],
        "game_highlights": [
            item
            for item in context.get("highlights") or []
            if isinstance(item, dict) and str(item.get("kind") or "") in {"game", "blunder", "chat"}
        ],
    }
    return (
        "Gere opções de bullets curtos em português para a lateral de um thumbnail de live de xadrez.\n"
        "Regras:\n"
        f"- Gere exatamente {count} opções.\n"
        f"- Cada opção deve ter exatamente {MAX_BULLETS} bullets.\n"
        f"- Cada bullet deve ter no máximo {MAX_BULLET_LENGTH} caracteres.\n"
        "- Use apenas a segunda metade da live: partidas rapid, abertura, erros, mate, relógio, decisões e capivaradas.\n"
        "- Não use Puzzle do dia, Puzzle Storm, Puzzle Streak, treino, prática ou estatísticas de puzzles.\n"
        "- Não use abreviações como pts, placares crus ou bullets como 'Storm 4 6 pts'.\n"
        "- Pelo menos 2 bullets devem ser momentos concretos de xadrez quando houver dados suficientes.\n"
        "- Evite frases genéricas, coach motivational, ou resumo longo.\n"
        "- Não use hashtags, emojis, pontuação final ou número da sessão.\n"
        "- Responda apenas com JSON: uma lista de listas de strings.\n\n"
        f"Dados da sessão:\n{json.dumps(compact, ensure_ascii=False, indent=2)}"
    )


def parse_options(text: str, count: int) -> list[list[str]]:
    parsed: Any
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = []
    options = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, list):
                bullets = clean_bullet_set(item)
                if len(bullets) == MAX_BULLETS:
                    options.append(bullets)
    return unique_bullet_sets(options, count)


def unique_bullet_sets(values: list[list[str]], count: int) -> list[list[str]]:
    seen = set()
    output = []
    for bullets in values:
        cleaned = clean_bullet_set(bullets)
        if len(cleaned) != MAX_BULLETS:
            continue
        key = tuple(bullet.casefold() for bullet in cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
        if len(output) >= count:
            break
    return output


def openai_options(context: dict[str, Any], count: int, model: str, api_key: str, timeout: int) -> list[list[str]]:
    body = {
        "model": model,
        "store": False,
        "input": prompt_for_model(context, count),
    }
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "xadrez-live-thumbnail-bullet-options/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"warning: OpenAI thumbnail bullet generation failed with HTTP {error.code}: {detail[:400]}", file=sys.stderr)
        return []
    except urllib.error.URLError as error:
        print(f"warning: OpenAI thumbnail bullet generation failed: {error.reason}", file=sys.stderr)
        return []
    return parse_options(response_text(payload), count)


def label_option(bullets: list[str]) -> str:
    return " | ".join(bullets)


def choose_with_gum(options: list[list[str]], default: list[str]) -> list[str]:
    labels = [label_option(option) for option in options]
    command = ["gum", "choose", "--header", "Escolha os bullets do thumbnail"]
    if default:
        command.extend(["--selected", label_option(default)])
    result = subprocess.run([*command, *labels], text=True, stdout=subprocess.PIPE, check=False)
    selected = result.stdout.strip() if result.returncode == 0 else ""
    for option in options:
        if label_option(option) == selected:
            return option
    return []


def choose_with_prompt(options: list[list[str]], default: list[str]) -> list[str]:
    default_index = 0
    for index, option in enumerate(options, start=1):
        selected = " [atual]" if option == default else ""
        if option == default:
            default_index = index
        print(f"{index}. {label_option(option)}{selected}")
    suffix = f" [{default_index}]" if default_index else ""
    raw = input(f"\nEscolha o número para os bullets do thumbnail{suffix}: ").strip()
    if not raw and default_index:
        return options[default_index - 1]
    if not raw.isdigit():
        return []
    index = int(raw)
    if not 1 <= index <= len(options):
        return []
    return options[index - 1]


def choose_option(options: list[list[str]], default: list[str]) -> list[str]:
    if default and default not in options:
        options = [default, *options]
    if shutil.which("gum"):
        return choose_with_gum(options, default)
    return choose_with_prompt(options, default)


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate, choose, and apply post thumbnail bullet options.")
    parser.add_argument("session", help="Session number, e.g. 0055")
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--model", default=os.environ.get("OPENAI_TITLE_MODEL", "gpt-5-mini"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--no-ai", action="store_true", help="Use deterministic fallback options only.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached options and ask the model again.")
    parser.add_argument("--choose", action="store_true", help="Choose one option interactively.")
    parser.add_argument("--write", action="store_true", help="Write selected bullets to session thumbnail_notes.")
    parser.add_argument("--generate", action="store_true", help="Generate post thumbnail if bullets changed or image is missing.")
    parser.add_argument("--force-generate", action="store_true", help="Generate post thumbnail even if bullets and image are unchanged.")
    return parser.parse_args()


def main() -> int:
    load_env_file(ENV_PATH)
    args = parse_args()
    session = args.session.zfill(4)
    context = session_context(session)
    api_key = os.environ.get("OPENAI_API_KEY", "")

    options = [] if args.refresh else cached_options(session)
    if not options and api_key and not args.no_ai:
        options = openai_options(context, args.count, args.model, api_key, args.timeout)
    if len(options) < args.count:
        options = unique_bullet_sets(options + fallback_options(context, args.count), args.count)
    if not options:
        fail("no thumbnail bullet options generated")
    if not (args.no_ai and not args.choose and not args.write):
        remember_options(session, options)

    if not args.choose and not args.write:
        for option in options:
            print(label_option(option))
        return 0

    current_notes = current_thumbnail_notes(session)
    previous = selected_bullets(session) or current_notes
    selected = choose_option(options, previous)
    if not selected:
        print("No option selected.")
        return 1
    print(label_option(selected))
    old_selected = selected_bullets(session)
    selection_changed = selected != old_selected
    image_content_changed = selected != current_notes
    remember_selected(session, selected)

    notes_changed = False
    if args.write:
        notes_changed = write_thumbnail_notes(session, selected)
        if notes_changed:
            print(f"{session}: updated thumbnail_notes")
        else:
            print(f"{session}: thumbnail_notes unchanged")

    image_path = og_image_path(session)
    missing_image = image_path is None or not image_path.exists()
    should_generate = args.force_generate or (args.generate and (image_content_changed or notes_changed or missing_image))
    if should_generate:
        run(["just", "post-thumb", session])
    elif args.generate:
        if selection_changed:
            print(f"{session}: remembered thumbnail bullet selection")
        print(f"{session}: thumbnail bullets unchanged and local thumbnail exists; skipping post-thumb")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
