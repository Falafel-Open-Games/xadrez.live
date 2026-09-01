#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo


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
DEFAULT_LOCAL_RECORDING_DIR = Path(os.environ.get("XADREZ_LOCAL_RECORDING_DIR", "/home/fcz/Videos/xadrez-live"))
DEFAULT_LOCAL_RECORDING_MAX_AGE_HOURS = int(os.environ.get("XADREZ_LOCAL_RECORDING_MAX_AGE_HOURS", "12"))
LOCAL_TZ = ZoneInfo(os.environ.get("XADREZ_LOCAL_TIMEZONE", "America/Sao_Paulo"))
MEDIA_EXTENSIONS = {".m4a", ".mp3", ".opus", ".ogg", ".webm", ".wav", ".mp4", ".mkv", ".mov", ".m4v"}


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


def session_date(session: str) -> str:
    data = read_front_matter(session)
    value = data.get("date")
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "").strip()


def has_recent_local_recording(session: str) -> bool:
    max_age_hours = DEFAULT_LOCAL_RECORDING_MAX_AGE_HOURS
    if max_age_hours <= 0 or not DEFAULT_LOCAL_RECORDING_DIR.exists():
        return False

    expected_date = session_date(session)
    now = datetime.now().timestamp()
    max_age_seconds = max_age_hours * 60 * 60
    for path in DEFAULT_LOCAL_RECORDING_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue

        stat = path.stat()
        age_seconds = now - stat.st_mtime
        if age_seconds < 0 or age_seconds > max_age_seconds:
            continue

        modified_date = datetime.fromtimestamp(stat.st_mtime, LOCAL_TZ).date().isoformat()
        if expected_date and modified_date != expected_date and session not in path.name:
            continue
        return True
    return False


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


def wrap_pid_is_alive(wrap_state: dict) -> bool:
    try:
        pid = int(wrap_state.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
            if wrap_pid_is_alive(wrap_state):
                return ActionState(action, "ongoing", "wrapup process is running; wait for it to finish")
            return ActionState(action, "done", "wrap state says running but no live process was found; rerun is allowed")
        if status == "completed":
            return ActionState(action, "done", "wrap state completed; rerun is allowed")
        if status == "interrupted":
            return ActionState(action, "done", "previous wrapup was interrupted; rerun is allowed")
        if wrap_state:
            return ActionState(action, "done", "wrap state exists without completion marker; rerun is allowed")
        return ActionState(action, "ready", "userscript TOML/chat found")

    if action.key == "faster-whisper":
        if has_faster_whisper_transcript(session):
            return ActionState(action, "done", "Faster Whisper transcript exists; rerun requires confirmation")
        if has_recent_local_recording(session):
            return ActionState(action, "ready", "local recording found")
        if has_youtube_id(session):
            return ActionState(action, "ready", "YouTube video id found")
        return ActionState(action, "blocked", "missing local recording or usable youtube_video_id")

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
        anchor = prompt("Ancora da calibracao: p=puzzle-of-the-day, f=first-game", "p").strip().lower()
        anchor = {
            "f": "first-game",
            "p": "puzzle-of-the-day",
        }.get(anchor, anchor)
        extra = prompt("Argumentos extras", "")
        command = ["just", "wrap-session", session]
        if anchor:
            command.extend(["--calibration-anchor", anchor])
        command.extend(extra.split())
        return command

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
