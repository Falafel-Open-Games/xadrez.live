#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time as time_module
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "xadrez.live"
CACHE_PATH = STATE_DIR / "daily_menu.json"
CONTENT_DIR = ROOT / "content" / "fcz"
DATA_DIR = ROOT / "data" / "fcz"
WRAP_INBOX_DIR = DATA_DIR / "wrap_inbox"
WRAP_SESSIONS_DIR = DATA_DIR / "wrap_sessions"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
HIGHLIGHTS_DIR = DATA_DIR / "highlights"
DOWNLOADS_DIR = Path.home() / "Downloads"
RECENT_LEGACY_RUNNING_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class Action:
    label: str
    description: str
    key: str


@dataclass(frozen=True)
class ActionState:
    action: Action
    status: Literal["ready", "done", "ongoing", "blocked"]
    detail: str = ""

    @property
    def selectable(self) -> bool:
        return self.status not in {"blocked", "ongoing"}


ACTIONS = [
    Action(
        "Pre-wrap recente",
        "resgatar chat, transcricao do YouTube e transcricao GPT mini depois que o VOD terminar",
        "pre-wrap",
    ),
    Action(
        "Wrapup da sessão",
        "aplicar TOML/chat, calibrar offset se preciso, finalizar YouTube, capivaradas, thumbnails, próxima sessão e build",
        "wrap-session",
    ),
    Action(
        "Transcrever com Faster Whisper",
        "job local lento/manual para uma sessao",
        "faster-whisper",
    ),
    Action(
        "Realinhar e gerar highlights",
        "rodar alinhamento e highlights depois que Faster Whisper terminar",
        "realign-highlights",
    ),
]


def normalize_session_number(value: str) -> str:
    value = value.strip()
    if value.isdigit() and len(value) <= 4:
        return value.zfill(4)
    return value


def latest_session_number() -> str:
    sessions = sorted(path.stem for path in CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md"))
    return sessions[-1] if sessions else ""


def load_cached_session() -> str:
    if not CACHE_PATH.exists():
        return ""
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return normalize_session_number(str(data.get("last_session") or ""))


def save_cached_session(session: str) -> None:
    session = normalize_session_number(session)
    if not session:
        return
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"last_session": session}, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def session_path(session: str) -> Path:
    return CONTENT_DIR / f"{session}.md"


def read_front_matter(session: str) -> dict:
    path = session_path(session)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return {}
    end = text.find("\n+++", 4)
    if end == -1:
        return {}
    try:
        return tomllib.loads(text[4:end])
    except tomllib.TOMLDecodeError:
        return {}


def session_extra(session: str) -> dict:
    data = read_front_matter(session)
    extra = data.get("extra")
    return extra if isinstance(extra, dict) else {}


def has_youtube_id(session: str) -> bool:
    youtube_id = str(session_extra(session).get("youtube_video_id") or "").strip()
    return bool(youtube_id) and youtube_id != "REPLACE_WITH_YOUTUBE_VIDEO_ID"


def has_wrap_input(session: str, suffix: str) -> bool:
    return (WRAP_INBOX_DIR / f"{session}{suffix}").exists() or (DOWNLOADS_DIR / f"{session}{suffix}").exists()


def has_wrap_toml(session: str) -> bool:
    return has_wrap_input(session, ".toml")


def has_wrap_chat(session: str) -> bool:
    return has_wrap_input(session, "-chat.json")


def wrap_state_path(session: str) -> Path:
    return WRAP_SESSIONS_DIR / f"{session}.json"


def load_wrap_state(session: str) -> dict:
    path = wrap_state_path(session)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def recent_legacy_wrap_state(session: str) -> bool:
    path = wrap_state_path(session)
    if not path.exists():
        return False
    try:
        age_seconds = time_module.time() - path.stat().st_mtime
    except OSError:
        return False
    return 0 <= age_seconds <= RECENT_LEGACY_RUNNING_SECONDS


def transcript_path(session: str, suffix: str) -> Path:
    return TRANSCRIPTS_DIR / f"{session}.{suffix}.json"


def has_faster_whisper_transcript(session: str) -> bool:
    return transcript_path(session, "faster-whisper").exists()


def has_highlights(session: str) -> bool:
    path = HIGHLIGHTS_DIR / f"{session}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    highlights = data.get("highlights")
    return isinstance(highlights, list) and bool(highlights)


def action_state(action: Action, session: str) -> ActionState:
    if action.key == "pre-wrap":
        return ActionState(action, "ready", "rerunnable; fetches recent VOD/chat artifacts")

    if not session:
        return ActionState(action, "blocked", "choose a session first")
    if not session_path(session).exists():
        return ActionState(action, "blocked", f"missing content/fcz/{session}.md")

    if action.key == "wrap-session":
        if not has_wrap_toml(session):
            return ActionState(action, "blocked", f"missing data/fcz/wrap_inbox/{session}.toml or ~/Downloads/{session}.toml")
        if not has_wrap_chat(session):
            return ActionState(action, "blocked", f"missing data/fcz/wrap_inbox/{session}-chat.json or ~/Downloads/{session}-chat.json")
        wrap_state = load_wrap_state(session)
        status = str(wrap_state.get("status") or "").strip().lower()
        if status == "running":
            return ActionState(action, "ongoing", "wrapup state is running; wait for it to finish")
        if status == "completed":
            return ActionState(action, "done", "wrap state completed; rerun is allowed")
        if wrap_state and "completed_at" not in wrap_state and recent_legacy_wrap_state(session):
            return ActionState(action, "ongoing", "wrap state was written recently without completion marker")
        if wrap_state:
            return ActionState(action, "done", "wrap state exists; rerun is allowed")
        return ActionState(action, "ready", "userscript TOML/chat found")

    if action.key == "faster-whisper":
        if not has_youtube_id(session):
            return ActionState(action, "blocked", "missing usable youtube_video_id")
        if has_faster_whisper_transcript(session):
            return ActionState(action, "done", "Faster Whisper transcript exists; rerun requires confirmation")
        return ActionState(action, "ready", "YouTube video id found")

    if action.key == "realign-highlights":
        if not has_faster_whisper_transcript(session):
            return ActionState(action, "blocked", "missing Faster Whisper transcript")
        if has_highlights(session):
            return ActionState(action, "done", "highlights exist; rerun is allowed")
        return ActionState(action, "ready", "Faster Whisper transcript found")

    return ActionState(action, "ready")


def action_states(session: str) -> list[ActionState]:
    return [action_state(action, session) for action in ACTIONS]


def status_text(state: ActionState) -> str:
    if state.detail:
        return f"{state.status}: {state.detail}"
    return state.status


def action_label(index: int, state: ActionState) -> str:
    return f"{index}. {state.action.label} [{status_text(state)}] - {state.action.description}"


def run(command: list[str]) -> int:
    print(f"\n$ {' '.join(command)}\n")
    return subprocess.call(command)


def has_gum() -> bool:
    return shutil.which("gum") is not None


def prompt(label: str, default: str = "") -> str:
    if has_gum():
        command = ["gum", "input", "--prompt", f"{label}: "]
        if default:
            command.extend(["--value", default])
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, check=False)
        if result.returncode != 0:
            return ""
        return result.stdout.strip() or default

    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def confirm(message: str) -> bool:
    if has_gum():
        return subprocess.run(["gum", "confirm", message], check=False).returncode == 0
    return prompt(f"{message} Digite SIM para iniciar", "") == "SIM"


def choose_with_gum(states: list[ActionState], session: str) -> ActionState | None:
    labels = [action_label(index, state) for index, state in enumerate(states, start=1)]
    header = "xadrez.live rotina diaria"
    if session:
        header += f" - sessao {session}"
    result = subprocess.run(
        ["gum", "choose", "--header", header, *labels],
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    choice = result.stdout.strip()
    if result.returncode != 0 or not choice:
        return None
    for index, state in enumerate(states, start=1):
        if choice.startswith(f"{index}. "):
            return state
    return None


def choose_with_prompt(states: list[ActionState], session: str) -> ActionState | None:
    heading = "xadrez.live rotina diaria"
    if session:
        heading += f" - sessao {session}"
    print(f"{heading}\n")
    for index, state in enumerate(states, start=1):
        print(f"{index}. {state.action.label} [{state.status}]")
        print(f"   {state.action.description}")
        if state.detail:
            print(f"   {state.detail}")
    choice = prompt("\nEscolha", "1")
    if not choice.isdigit():
        return None
    index = int(choice)
    if not 1 <= index <= len(states):
        return None
    return states[index - 1]


def choose_action(states: list[ActionState], session: str) -> ActionState | None:
    if has_gum():
        return choose_with_gum(states, session)
    return choose_with_prompt(states, session)


def command_for(action: Action, session: str) -> list[str] | None:
    if action.key == "pre-wrap":
        recent = prompt("RECENT", "5")
        return ["just", "pre-wrap", recent]

    if action.key == "wrap-session":
        extra = prompt("Argumentos extras", "")
        return ["just", "wrap-session", session, *extra.split()]

    if action.key == "faster-whisper":
        if not confirm("Faster Whisper e lento e pode levar dezenas de minutos. Iniciar agora?"):
            print("Cancelado.")
            return None
        return ["just", "import-faster-whisper-transcript", session]

    if action.key == "realign-highlights":
        return ["just", "realign-highlights", session]

    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Small interactive menu for common xadrez.live daily maintenance.")
    parser.add_argument("--list-actions", action="store_true", help="Print menu actions without prompting.")
    parser.add_argument("--session", help="Session number used for readiness checks, e.g. 0071.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_actions:
        for action in ACTIONS:
            print(f"{action.key}\t{action.label}\t{action.description}")
        return 0

    default_session = normalize_session_number(args.session or load_cached_session() or latest_session_number())
    session = normalize_session_number(args.session or prompt("Sessao para checagens", default_session))
    save_cached_session(session)
    states = action_states(session)

    state = choose_action(states, session)
    if state is None:
        print("Nenhuma acao selecionada.")
        return 1
    if not state.selectable:
        if state.status == "ongoing":
            print(f"Acao em andamento: {state.detail}")
        else:
            print(f"Acao bloqueada: {state.detail}")
        return 1

    command = command_for(state.action, session)
    if command is None:
        return 1
    return run(command)


if __name__ == "__main__":
    raise SystemExit(main())
