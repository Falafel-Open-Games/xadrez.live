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


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
HIGHLIGHTS_DIR = ROOT / "data" / "fcz" / "highlights"
TIMELINE_DIR = ROOT / "data" / "fcz" / "lichess_blunders"
CHOICES_PATH = ROOT / "data" / "fcz" / "session_editorial_choices.json"
ENV_PATH = ROOT / ".env"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_SUMMARY_LENGTH = 64
RETRY_CHOICE = "__retry_with_guidance__"
RETRY_LABEL = "Nenhuma opção serve; orientar nova tentativa"
GENERIC_SUMMARY_PATTERNS = [
    r"^puzzles?\s+e\s+rapid$",
    r"^puzzle\s+do\s+dia\s+seguido\s+de\s+partida\s+rapid$",
    r"^treino\s+de\s+puzzles?\s+e\s+(?:uma\s+)?partida\s+rapid$",
    r"^puzzles?,?\s+rapid\s+e\s+progresso\s+(?:real|honesto)$",
    r"^mais\s+uma\s+sess[aã]o\s+de\s+xadrez\s+real$",
]
SUMMARY_STOPWORDS = {
    "a",
    "as",
    "com",
    "da",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "na",
    "no",
    "o",
    "os",
    "uma",
    "um",
}
WEAK_SUMMARY_TOPIC_WORDS = {
    "partida",
    "partidas",
    "pratica",
    "puzzle",
    "puzzles",
    "rapid",
    "rapida",
    "rapidas",
    "sessao",
    "treino",
    "xadrez",
}
PLACEHOLDER_DESCRIPTION = "Treino de puzzles e uma partida rapid."


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
        "current_summary_title": str(extra.get("summary_title") or ""),
        "description": str(extra.get("description") or ""),
        "description_notes": str(extra.get("description_notes") or ""),
        "thumbnail_notes": extra.get("thumbnail_notes") or [],
        "games": extra.get("games") or [],
        "practice_sets": extra.get("practice_sets") or [],
        "storm_attempts": extra.get("storm_attempts") or [],
        "timeline": timeline[:12] if isinstance(timeline, list) else [],
        "highlights": highlights[:4] if isinstance(highlights, list) else [],
    }


def complete_summary(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" -|:;.\"'")
    value = re.sub(r"\s*\|\s*xadrez depois dos 40\s+#?\d{4}$", "", value, flags=re.I).strip(" -|:;.")
    if len(value) <= MAX_SUMMARY_LENGTH:
        return value
    shortened = value[:MAX_SUMMARY_LENGTH].rsplit(" ", 1)[0].strip()
    return shortened or value[:MAX_SUMMARY_LENGTH].strip()


def read_choices() -> dict[str, Any]:
    data = read_json(CHOICES_PATH)
    return data if isinstance(data.get("sessions"), dict) else {"sessions": {}}


def write_choices(data: dict[str, Any]) -> None:
    CHOICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHOICES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cached_options(session: str) -> list[str]:
    item = read_choices().get("sessions", {}).get(session, {}).get("summary_titles", {})
    options = item.get("options") if isinstance(item, dict) else []
    if not isinstance(options, list):
        return []
    return [str(option) for option in options if not is_generic_summary(str(option))]


def selected_choice(session: str) -> str:
    item = read_choices().get("sessions", {}).get(session, {}).get("summary_titles", {})
    return str(item.get("selected") or "") if isinstance(item, dict) else ""


def remember_options(session: str, options: list[str]) -> None:
    data = read_choices()
    item = data.setdefault("sessions", {}).setdefault(session, {}).setdefault("summary_titles", {})
    item["options"] = options
    write_choices(data)


def remember_selected(session: str, value: str) -> None:
    data = read_choices()
    item = data.setdefault("sessions", {}).setdefault(session, {}).setdefault("summary_titles", {})
    if value and value not in item.get("options", []):
        item["options"] = [value, *(item.get("options") or [])]
    item["selected"] = value
    write_choices(data)


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


def is_generic_summary(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value).strip(" .;:-").casefold()
    if any(re.search(pattern, normalized, flags=re.I) for pattern in GENERIC_SUMMARY_PATTERNS):
        return True
    tokens = re.findall(r"[a-z0-9]+", normalized.replace("ã", "a").replace("á", "a").replace("ç", "c"))
    content_tokens = [token for token in tokens if token not in SUMMARY_STOPWORDS]
    return bool(content_tokens) and all(token in WEAK_SUMMARY_TOPIC_WORDS for token in content_tokens)


def filter_summary_options(values: list[str], count: int) -> list[str]:
    filtered = [value for value in values if not is_generic_summary(value)]
    return unique_options(filtered, count)


def fallback_options(context: dict[str, Any], count: int) -> list[str]:
    hooks = []
    for game in context.get("games") or []:
        if isinstance(game, dict):
            opening = str(game.get("opening") or "").strip()
            note = str(game.get("note") or "").strip()
            result = str(game.get("result") or "").strip()
            if opening and result:
                hooks.append(f"{opening}: {result}")
            elif opening:
                hooks.append(opening)
            if note:
                for line in note.splitlines():
                    line = line.strip()
                    if line:
                        hooks.append(line)
                        break
    for value in context.get("thumbnail_notes") or []:
        if isinstance(value, str) and value.strip():
            hooks.append(value)
    description = str(context.get("description") or "").strip()
    if description and description != PLACEHOLDER_DESCRIPTION:
        hooks.append(description)
    return filter_summary_options([complete_summary(hook) for hook in hooks], count)


def prompt_for_model(context: dict[str, Any], count: int, guidance: str = "") -> str:
    compact = {
        "session": context["session"],
        "current_summary_title": context["current_summary_title"],
        "description": context["description"],
        "description_notes": context["description_notes"],
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
        "storm_attempts": [
            {"score": attempt.get("score"), "note": attempt.get("note")}
            for attempt in context.get("storm_attempts") or []
            if isinstance(attempt, dict)
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
            {"time": item.get("time"), "kind": item.get("kind"), "summary": item.get("summary")}
            for item in context.get("highlights") or []
            if isinstance(item, dict)
        ],
    }
    guidance_block = ""
    if guidance:
        guidance_block = (
            "\n\nOrientação humana para esta nova tentativa:\n"
            f"{guidance}\n"
            "Use essa orientação para escolher o enfoque editorial, mas ainda respeite os dados da sessão."
        )
    return (
        "Gere subtítulos editoriais curtos em português para a página de arquivo de uma sessão pessoal de xadrez.\n"
        "O texto escolhido aparece como subtítulo da sessão no site, logo abaixo de 'Sessão #NNNN'.\n"
        "Regras:\n"
        f"- Gere exatamente {count} opções.\n"
        "- Não inclua número da sessão.\n"
        "- Não inclua sufixo de canal, hashtag ou chamada para clique.\n"
        "- Não use ponto final.\n"
        f"- Máximo de {MAX_SUMMARY_LENGTH} caracteres por opção.\n"
        "- Prefira linguagem de caderno/arquivo, não título de YouTube.\n"
        "- Seja concreto e fiel: abertura, erro recorrente, virada, mate, tempo, puzzle ou tema de estudo.\n"
        "- Responda apenas com uma lista JSON de strings.\n\n"
        f"Dados da sessão:\n{json.dumps(compact, ensure_ascii=False, indent=2)}"
        f"{guidance_block}"
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


def parse_options(text: str, count: int) -> list[str]:
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
    return filter_summary_options([complete_summary(option) for option in options], count)


def openai_options(context: dict[str, Any], count: int, model: str, api_key: str, timeout: int, guidance: str = "") -> list[str]:
    body = {"model": model, "store": False, "input": prompt_for_model(context, count, guidance)}
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "xadrez-live-session-summary-options/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"warning: OpenAI summary generation failed with HTTP {error.code}: {detail[:400]}", file=sys.stderr)
        return []
    except urllib.error.URLError as error:
        print(f"warning: OpenAI summary generation failed: {error.reason}", file=sys.stderr)
        return []
    except TimeoutError:
        fail(f"OpenAI summary generation timed out after {timeout}s; retry when the API is responsive or increase --timeout")
    return parse_options(response_text(payload), count)


def options_with_default(options: list[str], default: str) -> list[str]:
    if not default or is_generic_summary(default):
        return options
    return unique_options([default, *options], len(options) + 1)


def choose_with_gum(options: list[str], default: str, allow_retry: bool) -> str:
    command = ["gum", "choose", "--header", "Escolha o subtítulo da página"]
    if default:
        command.extend(["--selected", default])
    choices = [*options]
    if allow_retry:
        choices.append(RETRY_LABEL)
    result = subprocess_run([*command, *choices])
    if result.strip() == RETRY_LABEL:
        return RETRY_CHOICE
    return result.strip()


def subprocess_run(command: list[str]) -> str:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, check=False)
    return result.stdout if result.returncode == 0 else ""


def choose_with_prompt(options: list[str], default: str, allow_retry: bool) -> str:
    default_index = 0
    for index, option in enumerate(options, start=1):
        selected = " [atual]" if option == default else ""
        if option == default:
            default_index = index
        print(f"{index}. {option}{selected}")
    retry_index = len(options) + 1
    if allow_retry:
        print(f"{retry_index}. {RETRY_LABEL}")
    suffix = f" [{default_index}]" if default_index else ""
    raw = input(f"\nEscolha o número para o subtítulo da página{suffix}: ").strip()
    if not raw and default_index:
        return options[default_index - 1]
    if not raw.isdigit():
        return ""
    index = int(raw)
    if allow_retry and index == retry_index:
        return RETRY_CHOICE
    if not 1 <= index <= len(options):
        return ""
    return options[index - 1]


def choose_option(options: list[str], default: str = "", allow_retry: bool = False) -> str:
    options = options_with_default(options, default)
    if shutil.which("gum"):
        return choose_with_gum(options, default, allow_retry)
    return choose_with_prompt(options, default, allow_retry)


def prompt_retry_guidance() -> str:
    if shutil.which("gum"):
        result = subprocess_run(
            [
                "gum",
                "input",
                "--prompt",
                "O que faltou nas opções? ",
                "--placeholder",
                "Ex.: enfatizar que eu ignorei a dama cravada",
            ]
        )
        return result.strip()
    return input("O que faltou nas opções? ").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate, choose, and cache page summary title options.")
    parser.add_argument("session", help="Session number, e.g. 0055")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--model", default=os.environ.get("OPENAI_SUMMARY_TITLE_MODEL", "gpt-5-mini"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--no-ai", action="store_true", help="Use deterministic fallback options only.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached options and ask the model again.")
    parser.add_argument("--choose", action="store_true", help="Choose one option interactively.")
    parser.add_argument("--write", action="store_true", help="Save the chosen option to the session editorial cache.")
    parser.add_argument("--title", help="Save this exact summary title instead of generating options.")
    return parser.parse_args()


def main() -> int:
    load_env_file(ENV_PATH)
    args = parse_args()
    session = args.session.zfill(4)
    context = session_context(session)

    if args.title:
        title = complete_summary(args.title)
        remember_selected(session, title)
        print(f"saved page summary title for {session}: {title}" if args.write else title)
        return 0

    api_key = os.environ.get("OPENAI_API_KEY", "")
    options = [] if args.refresh else cached_options(session)
    if not options and api_key and not args.no_ai:
        options = openai_options(context, args.count, args.model, api_key, args.timeout)
    if len(options) < args.count:
        options = filter_summary_options(options + fallback_options(context, args.count), args.count)
    if not options:
        fail("no summary title options generated")
    if not (args.no_ai and not args.choose and not args.write):
        remember_options(session, options)

    if not args.choose and not args.write:
        for option in options:
            print(option)
        return 0

    previous = selected_choice(session) or complete_summary(str(context.get("current_summary_title") or ""))
    if is_generic_summary(previous):
        previous = ""
    title = ""
    for _ in range(3):
        title = choose_option(options, previous, allow_retry=bool(api_key and not args.no_ai))
        if title != RETRY_CHOICE:
            break
        guidance = prompt_retry_guidance()
        if not guidance:
            print("No guidance provided.")
            return 1
        refreshed = openai_options(context, args.count, args.model, api_key, args.timeout, guidance)
        if len(refreshed) < args.count:
            refreshed = filter_summary_options(refreshed + fallback_options(context, args.count), args.count)
        if not refreshed:
            print("No replacement options generated.")
            return 1
        options = refreshed
        remember_options(session, options)
    if title == RETRY_CHOICE:
        print("No option selected after retry attempts.")
        return 1
    if not title:
        print("No option selected.")
        return 1
    print(title)
    remember_selected(session, title)
    if previous and title == previous:
        print(f"page summary title already selected for {session}: {title}")
    else:
        print(f"saved page summary title for {session}: {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
