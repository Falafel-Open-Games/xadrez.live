#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
DATA_DIR = ROOT / "data" / "fcz"
WORKFLOWS_DIR = DATA_DIR / "workflows"
WRAP_INBOX_DIR = DATA_DIR / "wrap_inbox"
RESTREAM_CHAT_REPLAYS_DIR = DATA_DIR / "restream_chat_replays"
YOUTUBE_METADATA_PATH = DATA_DIR / "youtube_video_metadata.toml"
DOWNLOADS_DIR = Path.home() / "Downloads"

STEP_ORDER = ["inputs", "chat", "youtube_metadata", "wrap_session", "verify", "build"]
StepStatus = Literal["pending", "running", "done", "blocked", "failed", "skipped"]


@dataclass(frozen=True)
class Step:
    key: str
    label: str


STEPS = {
    "inputs": Step("inputs", "Inputs"),
    "chat": Step("chat", "Chat"),
    "youtube_metadata": Step("youtube_metadata", "YouTube metadata"),
    "wrap_session": Step("wrap_session", "Wrapup"),
    "verify": Step("verify", "Verify"),
    "build": Step("build", "Build"),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_session_number(value: str) -> str:
    value = value.strip()
    if value.isdigit() and len(value) <= 4:
        return value.zfill(4)
    return value


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def workflow_path(session: str) -> Path:
    return WORKFLOWS_DIR / f"{session}.json"


def default_state(session: str) -> dict[str, Any]:
    return {
        "session": session,
        "workflow": "daily-wrap",
        "status": "pending",
        "current_step": "inputs",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "inputs": {},
        "decisions": {},
        "steps": {key: {"status": "pending"} for key in STEP_ORDER},
    }


def load_state(session: str) -> dict[str, Any]:
    path = workflow_path(session)
    if not path.exists():
        return default_state(session)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state(session)
    if not isinstance(data, dict):
        return default_state(session)
    state = default_state(session)
    state.update(data)
    state["inputs"] = data.get("inputs") if isinstance(data.get("inputs"), dict) else {}
    state["decisions"] = data.get("decisions") if isinstance(data.get("decisions"), dict) else {}
    steps = state["steps"] if isinstance(state.get("steps"), dict) else {}
    for key in STEP_ORDER:
        item = steps.get(key)
        if not isinstance(item, dict):
            steps[key] = {"status": "pending"}
    state["steps"] = steps
    return state


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    workflow_path(str(state["session"])).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def reset_state(session: str) -> dict[str, Any]:
    state = default_state(session)
    save_state(state)
    return state


def step_status(state: dict[str, Any], key: str) -> str:
    steps = state.get("steps")
    if not isinstance(steps, dict):
        return "pending"
    step = steps.get(key)
    if not isinstance(step, dict):
        return "pending"
    return str(step.get("status") or "pending")


def set_step(
    state: dict[str, Any],
    key: str,
    status: StepStatus,
    detail: str = "",
    **extra: Any,
) -> None:
    steps = state.setdefault("steps", {})
    if not isinstance(steps, dict):
        state["steps"] = steps = {}
    item = {"status": status, "updated_at": now_iso()}
    if detail:
        item["detail"] = detail
    item.update(extra)
    steps[key] = item
    state["current_step"] = key
    state["status"] = "in_progress" if status in {"pending", "running", "blocked", "failed"} else state.get("status", "in_progress")
    save_state(state)


def mark_done(state: dict[str, Any], key: str, detail: str = "") -> None:
    set_step(state, key, "done", detail)


def session_path(session: str) -> Path:
    return CONTENT_DIR / f"{session}.md"


def read_front_matter(session: str) -> dict[str, Any]:
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
        data = tomllib.loads(text[4:end])
    except tomllib.TOMLDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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
    return prompt(f"{message} Digite SIM para continuar", "") == "SIM"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def existing_input(candidates: list[Path]) -> Path | None:
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def wrap_toml_path(session: str) -> Path | None:
    return existing_input([WRAP_INBOX_DIR / f"{session}.toml", DOWNLOADS_DIR / f"{session}.toml"])


def userscript_chat_path(session: str) -> Path | None:
    return existing_input([WRAP_INBOX_DIR / f"{session}-chat.json", DOWNLOADS_DIR / f"{session}-chat.json"])


def restream_api_chat_path(session: str) -> Path | None:
    path = RESTREAM_CHAT_REPLAYS_DIR / f"{session}.json"
    data = read_json(path)
    messages = data.get("messages")
    return path if isinstance(messages, list) and messages else None


def command_text(command: list[str]) -> str:
    return " ".join(command)


def run_command(state: dict[str, Any], step: str, command: list[str]) -> int:
    print(f"\n$ {command_text(command)}\n")
    set_step(state, step, "running", command=command)
    result = subprocess.call(command, cwd=ROOT)
    if result == 0:
        mark_done(state, step, f"completed: {command_text(command)}")
    else:
        set_step(
            state,
            step,
            "failed",
            f"exit {result}: {command_text(command)}",
            command=command,
            exit_code=result,
        )
    return result


def refresh_artifact_inputs(state: dict[str, Any], persist: bool = True) -> dict[str, Path | None]:
    session = str(state["session"])
    artifacts = {
        "wrap_toml": wrap_toml_path(session),
        "userscript_chat": userscript_chat_path(session),
        "restream_api_chat": restream_api_chat_path(session),
    }
    inputs = state.setdefault("inputs", {})
    if isinstance(inputs, dict):
        for key, path in artifacts.items():
            if path is not None:
                inputs[key] = {"path": str(path)}
    if persist:
        save_state(state)
    return artifacts


def resolve_inputs(state: dict[str, Any]) -> bool:
    session = str(state["session"])
    if not session_path(session).exists():
        set_step(state, "inputs", "blocked", f"missing content/fcz/{session}.md")
        print(f"Missing content/fcz/{session}.md")
        return False

    artifacts = refresh_artifact_inputs(state)
    if artifacts["wrap_toml"] is None:
        set_step(
            state,
            "inputs",
            "blocked",
            f"missing data/fcz/wrap_inbox/{session}.toml or ~/Downloads/{session}.toml",
        )
        print(f"Missing wrap TOML for {session}.")
        return False

    mark_done(state, "inputs", "session page and wrap TOML found")
    return True


def import_restream_chat(state: dict[str, Any]) -> bool:
    session = str(state["session"])
    command = [
        "python3",
        "scripts/import_restream_chat_replays.py",
        "--cache-dir",
        "/tmp/xadrez-restream-chat",
        session,
    ]
    if run_command(state, "chat", command) != 0:
        return False
    if restream_api_chat_path(session) is None:
        set_step(state, "chat", "failed", f"Restream API fallback not created for {session}")
        print(f"Restream API fallback was not created for {session}.")
        return False
    return True


def youtube_metadata_entry(session: str) -> dict[str, Any]:
    if not YOUTUBE_METADATA_PATH.exists():
        return {}
    try:
        data = tomllib.loads(YOUTUBE_METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    sessions = data.get("sessions") if isinstance(data, dict) else None
    entry = sessions.get(session) if isinstance(sessions, dict) else None
    return entry if isinstance(entry, dict) else {}


def session_youtube_id(session: str) -> str:
    data = read_front_matter(session)
    extra = data.get("extra") if isinstance(data, dict) else None
    return str(extra.get("youtube_video_id") or "").strip() if isinstance(extra, dict) else ""


def resolve_youtube_metadata(state: dict[str, Any]) -> bool:
    session = str(state["session"])
    command = ["python3", "scripts/update_youtube_video_metadata.py", session]
    result = run_command(state, "youtube_metadata", command)
    if result != 0:
        return False

    entry = youtube_metadata_entry(session)
    try:
        release_timestamp = int(entry.get("release_timestamp") or 0)
        duration_seconds = int(entry.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        release_timestamp = 0
        duration_seconds = 0
    metadata_video_id = str(entry.get("youtube_video_id") or "").strip()
    expected_video_id = session_youtube_id(session)
    if (
        release_timestamp <= 0
        or duration_seconds <= 0
        or not metadata_video_id
        or (expected_video_id and metadata_video_id != expected_video_id)
    ):
        detail = (
            f"YouTube metadata unavailable for {session}; retrying is safe "
            "and required before timeline-dependent work"
        )
        set_step(
            state,
            "youtube_metadata",
            "blocked",
            detail,
            retryable=True,
            release_timestamp=release_timestamp,
            duration_seconds=duration_seconds,
        )
        print(f"{session}: {detail}")
        return False

    mark_done(
        state,
        "youtube_metadata",
        f"release timestamp and duration found ({entry.get('duration') or duration_seconds}s)",
    )
    return True


def resolve_chat(state: dict[str, Any]) -> bool:
    session = str(state["session"])
    artifacts = refresh_artifact_inputs(state)
    decisions = state.setdefault("decisions", {})
    chat_decision = decisions.setdefault("chat", {}) if isinstance(decisions, dict) else {}
    if not isinstance(chat_decision, dict):
        state["decisions"]["chat"] = chat_decision = {}

    if artifacts["userscript_chat"] is not None:
        chat_decision.update({"source": "userscript", "accepted_by_user": True})
        mark_done(state, "chat", "userscript chat JSON found")
        return True

    if artifacts["restream_api_chat"] is not None:
        if chat_decision.get("source") != "restream_api" or not chat_decision.get("accepted_by_user"):
            if not confirm("Chat JSON do userscript ausente; usar fallback da API do Restream com autores anonimizados?"):
                set_step(state, "chat", "blocked", "waiting for userscript chat JSON")
                print(f"Save {WRAP_INBOX_DIR / f'{session}-chat.json'} or {DOWNLOADS_DIR / f'{session}-chat.json'} and rerun.")
                return False
            chat_decision.update({"source": "restream_api", "accepted_by_user": True})
            save_state(state)
        mark_done(state, "chat", "Restream API fallback accepted")
        return True

    while True:
        choice = prompt(
            "Chat JSON ausente: s=salvei agora, r=importar fallback Restream API, c=cancelar",
            "c",
        ).strip().lower()
        if choice in {"s", "salvei", "saved"}:
            artifacts = refresh_artifact_inputs(state)
            if artifacts["userscript_chat"] is not None:
                chat_decision.update({"source": "userscript", "accepted_by_user": True})
                mark_done(state, "chat", "userscript chat JSON found after recheck")
                return True
            print(f"Ainda nao encontrei {WRAP_INBOX_DIR / f'{session}-chat.json'} nem {DOWNLOADS_DIR / f'{session}-chat.json'}.")
        elif choice in {"r", "restream", "api"}:
            chat_decision.update({"source": "restream_api", "accepted_by_user": True})
            save_state(state)
            return import_restream_chat(state)
        elif choice in {"c", "cancelar", "cancel"}:
            set_step(state, "chat", "blocked", "waiting for chat source")
            print("Cancelado.")
            return False
        else:
            print("Opcao invalida.")


def calibration_anchor(state: dict[str, Any]) -> str:
    decisions = state.setdefault("decisions", {})
    calibration = decisions.setdefault("calibration", {}) if isinstance(decisions, dict) else {}
    if not isinstance(calibration, dict):
        state["decisions"]["calibration"] = calibration = {}
    current = str(calibration.get("anchor") or "")
    if current:
        return current
    raw = prompt("Ancora da calibracao: p=puzzle-of-the-day, f=first-game", "p").strip().lower()
    anchor = {"f": "first-game", "p": "puzzle-of-the-day"}.get(raw, raw)
    calibration["anchor"] = anchor
    save_state(state)
    return anchor


def wrap_extra_args(state: dict[str, Any]) -> list[str]:
    decisions = state.setdefault("decisions", {})
    wrap = decisions.setdefault("wrap_session", {}) if isinstance(decisions, dict) else {}
    if not isinstance(wrap, dict):
        state["decisions"]["wrap_session"] = wrap = {}
    if "extra_args" not in wrap:
        wrap["extra_args"] = prompt("Argumentos extras", "").split()
        save_state(state)
    return [str(item) for item in wrap.get("extra_args", [])]


def wrap_command(state: dict[str, Any]) -> list[str]:
    session = str(state["session"])
    command = ["just", "wrap-session", session]
    anchor = calibration_anchor(state)
    if anchor:
        command.extend(["--calibration-anchor", anchor])
    chat = state.get("decisions", {}).get("chat", {})
    if isinstance(chat, dict) and chat.get("source") == "restream_api":
        command.append("--use-restream-api-chat-fallback")
    command.extend(wrap_extra_args(state))
    return command


def dashboard(state: dict[str, Any]) -> None:
    print(f"\nSessao {state['session']} - daily wrap\n")
    for index, key in enumerate(STEP_ORDER, start=1):
        step = state.get("steps", {}).get(key, {})
        status = step.get("status", "pending") if isinstance(step, dict) else "pending"
        detail = step.get("detail", "") if isinstance(step, dict) else ""
        suffix = f" - {detail}" if detail else ""
        print(f"{index}. {STEPS[key].label}: {status}{suffix}")
    print("")


def continue_workflow(session: str, restart: bool) -> int:
    state = reset_state(session) if restart else load_state(session)
    if not restart and state.get("status") == "completed":
        print(f"{session}: daily wrap already completed; use --restart to run it again")
        return 0
    dashboard(state)
    if not resolve_inputs(state):
        return 1
    if not resolve_chat(state):
        return 1
    if not resolve_youtube_metadata(state):
        return 1
    command = wrap_command(state)
    result = run_command(state, "wrap_session", command)
    if result != 0:
        return result

    mark_done(state, "verify", "handled by wrap-session")
    mark_done(state, "build", "handled by wrap-session")
    state["status"] = "completed"
    state["current_step"] = "done"
    state["completed_at"] = now_iso()
    save_state(state)
    return 0


def show_status(session: str) -> int:
    state = load_state(session)
    refresh_artifact_inputs(state, persist=False)
    dashboard(state)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumable daily wrap workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    continue_parser = subparsers.add_parser("continue", help="Continue a daily wrap workflow.")
    continue_parser.add_argument("session", help="Session number, e.g. 0090")
    continue_parser.add_argument("--restart", action="store_true", help="Reset saved workflow state before continuing.")

    status_parser = subparsers.add_parser("status", help="Show workflow status.")
    status_parser.add_argument("session", help="Session number, e.g. 0090")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = normalize_session_number(args.session)
    if args.command == "continue":
        return continue_workflow(session, args.restart)
    if args.command == "status":
        return show_status(session)
    fail(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
