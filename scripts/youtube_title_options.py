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

from update_youtube_chapters import (
    ENV_PATH,
    access_token,
    api_request,
    env_value,
    fetch_video_snippets,
    load_env_file,
)


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
HIGHLIGHTS_DIR = ROOT / "data" / "fcz" / "highlights"
TIMELINE_DIR = ROOT / "data" / "fcz" / "lichess_blunders"
CHOICES_PATH = ROOT / "data" / "fcz" / "youtube_editorial_choices.json"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
TITLE_SUFFIX_TEMPLATE = " | xadrez depois dos 40 #{session}"
MAX_TITLE_LENGTH = 100
MAX_HOOK_LENGTH = 180


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return {}
    end = text.find("\n+++", 4)
    if end == -1:
        return {}
    return tomllib.loads(text[4:end])


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def session_context(session: str) -> dict[str, Any]:
    path = CONTENT_DIR / f"{session}.md"
    if not path.exists():
        fail(f"session not found: {path}")
    data = read_front_matter(path)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        fail(f"missing [extra] in {path}")
    highlights = read_json(HIGHLIGHTS_DIR / f"{session}.json").get("highlights") or []
    timeline = read_json(TIMELINE_DIR / f"{session}.json").get("timeline") or []
    return {
        "session": session,
        "title": str(data.get("title") or ""),
        "summary_title": str(extra.get("summary_title") or ""),
        "description": str(extra.get("description") or ""),
        "thumbnail_notes": extra.get("thumbnail_notes") or [],
        "games": extra.get("games") or [],
        "practice_sets": extra.get("practice_sets") or [],
        "timeline": timeline[:12] if isinstance(timeline, list) else [],
        "highlights": highlights[:4] if isinstance(highlights, list) else [],
        "youtube_video_id": str(extra.get("youtube_video_id") or "").strip(),
    }


def title_suffix(session: str) -> str:
    return TITLE_SUFFIX_TEMPLATE.format(session=session)


def clean_hook(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" -|:;.\"'")
    value = value.removeprefix("Sessão ").strip()
    value = re.sub(r"\s+#?\d{4}\b", "", value).strip()
    return value


def complete_title(hook: str, session: str) -> str:
    suffix = title_suffix(session)
    hook = re.sub(r"\s+", " ", hook).strip(" -|:;.\"'")
    if hook.endswith(suffix):
        hook = hook[: -len(suffix)].strip()
    hook = re.sub(rf"(?:\s*\|\s*)?xadrez depois dos 40\s+#?{re.escape(session)}$", "", hook, flags=re.I).strip()
    hook = clean_hook(hook)
    hook = re.sub(r"(?:\s*\|\s*)+$", "", hook).strip()
    title = f"{hook}{suffix}"
    if len(title) <= MAX_TITLE_LENGTH:
        return title
    available = MAX_TITLE_LENGTH - len(suffix) - 1
    shortened = hook[:available].rsplit(" ", 1)[0].strip()
    return f"{shortened}{suffix}"


def complete_hook(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" -|:;.\"'")
    if value and value[-1] not in ".!?":
        value += "."
    if len(value) <= MAX_HOOK_LENGTH:
        return value
    shortened = value[: MAX_HOOK_LENGTH - 1].rsplit(" ", 1)[0].strip()
    return shortened + "."


def cache_key(kind: str) -> str:
    return "description_hooks" if kind == "hook" else "titles"


def read_choices() -> dict[str, Any]:
    if not CHOICES_PATH.exists():
        return {"sessions": {}}
    data = read_json(CHOICES_PATH)
    return data if isinstance(data.get("sessions"), dict) else {"sessions": {}}


def write_choices(data: dict[str, Any]) -> None:
    CHOICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHOICES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cached_options(session: str, kind: str) -> list[str]:
    data = read_choices()
    item = data.get("sessions", {}).get(session, {}).get(cache_key(kind), {})
    options = item.get("options") if isinstance(item, dict) else []
    return [str(option) for option in options] if isinstance(options, list) else []


def selected_choice(session: str, kind: str) -> str:
    data = read_choices()
    item = data.get("sessions", {}).get(session, {}).get(cache_key(kind), {})
    return str(item.get("selected") or "") if isinstance(item, dict) else ""


def remember_options(session: str, kind: str, options: list[str]) -> None:
    data = read_choices()
    sessions = data.setdefault("sessions", {})
    session_data = sessions.setdefault(session, {})
    item = session_data.setdefault(cache_key(kind), {})
    item["options"] = options
    write_choices(data)


def remember_selected(session: str, kind: str, value: str) -> None:
    data = read_choices()
    sessions = data.setdefault("sessions", {})
    session_data = sessions.setdefault(session, {})
    item = session_data.setdefault(cache_key(kind), {})
    if value and value not in item.get("options", []):
        item["options"] = [value, *(item.get("options") or [])]
    item["selected"] = value
    write_choices(data)


def fallback_options(context: dict[str, Any], count: int, kind: str) -> list[str]:
    session = context["session"]
    hooks = []
    for value in context.get("thumbnail_notes") or []:
        if isinstance(value, str) and value.strip():
            hooks.append(value)
    summary = clean_hook(str(context.get("summary_title") or ""))
    if summary:
        hooks.append(summary)
    description = str(context.get("description") or "")
    if "mate em 1" in description.casefold():
        hooks.extend(["Tinha mate em 1, mas perdi no relógio", "Mate em 1 no tabuleiro, tempo zerado"])
    if "tempo" in description.casefold():
        hooks.append("Ganhei a posição, perdi no tempo")
    for game in context.get("games") or []:
        if isinstance(game, dict):
            opening = str(game.get("opening") or "").strip()
            if opening:
                hooks.append(f"{opening} e uma lição no relógio")
    if kind == "hook":
        hooks.extend(["Mais uma sessão de xadrez real, com erros úteis para estudar", "Puzzles, partida rapid e progresso honesto no tabuleiro"])
        return unique_options([complete_hook(hook) for hook in hooks], count)
    hooks.extend(["Puzzles, rapid e progresso real", "Mais uma sessão de xadrez real"])
    return unique_options([complete_title(hook, session) for hook in hooks], count)


def prompt_for_model(context: dict[str, Any], count: int, kind: str) -> str:
    compact = {
        "session": context["session"],
        "summary_title": context["summary_title"],
        "description": context["description"],
        "thumbnail_notes": context["thumbnail_notes"],
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
        "practice_sets": [
            {
                "title": practice_set.get("title"),
                "exercises": [
                    exercise.get("title")
                    for exercise in practice_set.get("exercises", [])
                    if isinstance(exercise, dict)
                ],
            }
            for practice_set in context.get("practice_sets") or []
            if isinstance(practice_set, dict)
        ],
        "timeline": [
            {
                "time": event.get("time"),
                "kind": event.get("kind"),
                "label": event.get("label"),
                "move": event.get("move"),
                "color": event.get("color"),
                "clock": event.get("clock"),
            }
            for event in context.get("timeline") or []
            if isinstance(event, dict)
        ],
        "highlights": [
            {
                "time": item.get("time"),
                "kind": item.get("kind"),
                "summary": item.get("summary"),
            }
            for item in context.get("highlights") or []
            if isinstance(item, dict)
        ],
    }
    if kind == "hook":
        task = (
            "Gere frases de abertura humanas em português para a descrição de um VOD de uma live pessoal de xadrez.\n"
            "A frase escolhida vai aparecer logo no início da descrição, antes dos links e capítulos.\n"
        )
        specific_rules = (
            "- Não inclua número da sessão.\n"
            "- Não mencione duração do vídeo.\n"
            "- Uma frase apenas, com ponto final.\n"
            f"- Máximo de {MAX_HOOK_LENGTH} caracteres por opção.\n"
        )
    else:
        task = "Gere títulos humanos em português para um VOD de uma live pessoal de xadrez.\n"
        specific_rules = (
            f"- Cada título deve terminar com: {title_suffix(context['session'])}\n"
            f"- Máximo de {MAX_TITLE_LENGTH} caracteres por título.\n"
        )
    return (
        task +
        "Regras:\n"
        f"- Gere exatamente {count} opções.\n" +
        specific_rules +
        "- Comece com um gancho humano e concreto.\n"
        "- Evite clickbait falso; seja fiel aos dados.\n"
        "- Prefira linguagem natural, memorável e curta.\n"
        "- Use termos buscáveis quando couber naturalmente: mate em 1, abertura, puzzle, rapid, tempo.\n"
        "- Responda apenas com uma lista JSON de strings.\n\n"
        f"Dados da sessão:\n{json.dumps(compact, ensure_ascii=False, indent=2)}"
    )


def response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    output = payload.get("output")
    if isinstance(output, list):
        chunks = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    chunks.append(content["text"])
        if chunks:
            return "\n".join(chunks)
    return ""


def openai_options(context: dict[str, Any], count: int, model: str, api_key: str, timeout: int, kind: str) -> list[str]:
    body = {
        "model": model,
        "store": False,
        "input": prompt_for_model(context, count, kind),
    }
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "xadrez-live-youtube-title-options/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"warning: OpenAI title generation failed with HTTP {error.code}: {detail[:400]}", file=sys.stderr)
        return []
    except urllib.error.URLError as error:
        print(f"warning: OpenAI title generation failed: {error.reason}", file=sys.stderr)
        return []
    return parse_options(response_text(payload), context["session"], count, kind)


def parse_options(text: str, session: str, count: int, kind: str) -> list[str]:
    options = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            options = [str(item) for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if line:
                options.append(line.strip('"'))
    if kind == "hook":
        return unique_options([complete_hook(option) for option in options], count)
    return unique_options([complete_title(option, session) for option in options], count)


def unique_options(values: list[str], count: int) -> list[str]:
    seen = set()
    output = []
    for value in values:
        value = re.sub(r"\s+", " ", value).strip()
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        output.append(value)
        if len(output) >= count:
            break
    return output


def choice_label(kind: str) -> str:
    return "o hook da descrição" if kind == "hook" else "o título do YouTube"


def options_with_default(options: list[str], default: str) -> list[str]:
    if not default:
        return options
    return unique_options([default, *options], len(options) + 1)


def choose_with_gum(options: list[str], kind: str, default: str) -> str:
    command = ["gum", "choose", "--header", f"Escolha {choice_label(kind)}"]
    if default:
        command.extend(["--selected", default])
    result = subprocess.run(
        [*command, *options],
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def choose_with_prompt(options: list[str], kind: str, default: str) -> str:
    default_index = 0
    for index, option in enumerate(options, start=1):
        selected = " [atual]" if option == default else ""
        if option == default:
            default_index = index
        print(f"{index}. {option}{selected}")
    suffix = f" [{default_index}]" if default_index else ""
    raw = input(f"\nEscolha o número para {choice_label(kind)}{suffix}: ").strip()
    if not raw and default_index:
        return options[default_index - 1]
    if not raw.isdigit():
        return ""
    index = int(raw)
    if not 1 <= index <= len(options):
        return ""
    return options[index - 1]


def choose_option(options: list[str], kind: str, default: str = "") -> str:
    options = options_with_default(options, default)
    if shutil.which("gum"):
        return choose_with_gum(options, kind, default)
    return choose_with_prompt(options, kind, default)


def confirm(message: str) -> bool:
    if shutil.which("gum"):
        return subprocess.run(["gum", "confirm", message], check=False).returncode == 0
    return input(f"{message} Digite SIM para confirmar: ").strip() == "SIM"


def snippet_with_title(snippet: dict[str, Any], title: str) -> dict[str, Any]:
    output = {
        "title": title,
        "description": str(snippet.get("description") or ""),
        "categoryId": str(snippet.get("categoryId") or "22"),
    }
    for key in ("tags", "defaultLanguage", "defaultAudioLanguage"):
        if key in snippet:
            output[key] = snippet[key]
    return output


def youtube_snippet(context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    video_id = context.get("youtube_video_id")
    if not video_id:
        fail("session has no youtube_video_id")
    client_id = env_value("YOUTUBE_CLIENT_ID")
    client_secret = env_value("YOUTUBE_CLIENT_SECRET")
    refresh_token = env_value("YOUTUBE_REFRESH_TOKEN")
    if not client_id or not client_secret or not refresh_token:
        fail("set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN in .env")
    token = access_token(client_id, client_secret, refresh_token)
    snippet = fetch_video_snippets(token, [video_id]).get(video_id)
    if not snippet:
        fail(f"video {video_id} was not returned by YouTube")
    return str(video_id), snippet


def write_title(context: dict[str, Any], title: str, snippet: dict[str, Any] | None = None) -> None:
    video_id = context.get("youtube_video_id")
    if not video_id:
        fail("session has no youtube_video_id")
    if snippet is None:
        video_id, snippet = youtube_snippet(context)
    else:
        video_id = str(video_id)
    if str(snippet.get("title") or "") == title:
        print(f"title already current for {video_id}: {title}")
        return
    client_id = env_value("YOUTUBE_CLIENT_ID")
    client_secret = env_value("YOUTUBE_CLIENT_SECRET")
    refresh_token = env_value("YOUTUBE_REFRESH_TOKEN")
    if not client_id or not client_secret or not refresh_token:
        fail("set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN in .env")
    token = access_token(client_id, client_secret, refresh_token)
    api_request("videos", token, method="PUT", query={"part": "snippet"}, body={"id": video_id, "snippet": snippet_with_title(snippet, title)})
    print(f"updated title for {video_id}: {title}")


def publish_title_if_changed(context: dict[str, Any], title: str, assume_yes: bool) -> int:
    video_id, snippet = youtube_snippet(context)
    current_title = str(snippet.get("title") or "")
    if current_title == title:
        print(f"title already current for {video_id}: {title}")
        return 0
    if assume_yes or confirm("Publicar este título no YouTube?"):
        write_title(context, title, snippet)
        return 0
    print("Canceled.")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and optionally publish human YouTube title options.")
    parser.add_argument("session", help="Session number, e.g. 0053")
    parser.add_argument("--kind", choices=("title", "hook"), default="title")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--model", default=os.environ.get("OPENAI_TITLE_MODEL", "gpt-5-mini"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--no-ai", action="store_true", help="Use deterministic fallback options only.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached options and ask the model again.")
    parser.add_argument("--choose", action="store_true", help="Choose one option interactively.")
    parser.add_argument("--write", action="store_true", help="Publish the chosen title to YouTube.")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation when using --write.")
    parser.add_argument("--title", help="Publish this exact title instead of generating options.")
    return parser.parse_args()


def main() -> int:
    load_env_file(ENV_PATH)
    args = parse_args()
    session = args.session.zfill(4)
    context = session_context(session)

    if args.title:
        title = complete_hook(args.title) if args.kind == "hook" else complete_title(args.title, session)
        remember_selected(session, args.kind, title)
        if args.write:
            if args.kind == "hook":
                print(f"saved description hook for {session}: {title}")
                return 0
            return publish_title_if_changed(context, title, args.yes)
        else:
            print(title)
        return 0

    api_key = os.environ.get("OPENAI_API_KEY", "")
    options = [] if args.refresh else cached_options(session, args.kind)
    if not options and api_key and not args.no_ai:
        options = openai_options(context, args.count, args.model, api_key, args.timeout, args.kind)
    if len(options) < args.count:
        options = unique_options(options + fallback_options(context, args.count, args.kind), args.count)
    if not options:
        fail("no title options generated")
    if not (args.no_ai and not args.choose and not args.write):
        remember_options(session, args.kind, options)

    if not args.choose and not args.write:
        for option in options:
            print(option)
        return 0

    previous = selected_choice(session, args.kind)
    title = choose_option(options, args.kind, previous)
    if not title:
        print("No option selected.")
        return 1
    print(title)
    remember_selected(session, args.kind, title)

    if args.write:
        if args.kind == "hook":
            if previous and title == previous:
                print(f"description hook already selected for {session}: {title}")
                return 0
            print(f"saved description hook for {session}: {title}")
            return 0
        if previous and title == previous:
            print(f"title selection unchanged for {session}; skipping YouTube title update.")
            return 0
        return publish_title_if_changed(context, title, args.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
