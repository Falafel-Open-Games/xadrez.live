#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from wrap_session import read_session, write_session


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
TEMPLATE = CONTENT_DIR / "_session-template.md"


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


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
    return input(f"{label}{suffix}: ").strip() or default


def extract_youtube_video_id(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{6,}", text):
        return text
    parsed = urlparse(text)
    host = parsed.netloc.casefold()
    if "youtu.be" in host:
        candidate = parsed.path.strip("/").split("/", 1)[0]
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,}", candidate) else ""
    if "youtube.com" in host:
        if parsed.path.startswith("/live/"):
            candidate = parsed.path.removeprefix("/live/").split("/", 1)[0]
            return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,}", candidate) else ""
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        return query_id if re.fullmatch(r"[A-Za-z0-9_-]{6,}", query_id) else ""
    return ""


def next_session_number() -> str:
    numbers = []
    for path in CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md"):
        try:
            numbers.append(int(path.stem))
        except ValueError:
            continue
    return f"{(max(numbers) if numbers else 0) + 1:04d}"


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        fail(f"data inválida: {value}; use YYYY-MM-DD")


def validate_time(value: str) -> str:
    if not re.fullmatch(r"\d{1,2}:\d{2}", value.strip()):
        fail(f"horário inválido: {value}; use HH:MM")
    hour, minute = [int(part) for part in value.split(":", 1)]
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        fail(f"horário inválido: {value}; use HH:MM")
    return f"{hour:02d}:{minute:02d}"


def init_from_template(session: str) -> Path:
    path = CONTENT_DIR / f"{session}.md"
    if path.exists():
        return path
    if not TEMPLATE.exists():
        fail(f"template não encontrado: {TEMPLATE}")
    path.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def update_session(path: Path, session: str, session_date: date, session_time: str, youtube_video_id: str) -> None:
    _, data, body = read_session(session)
    data["title"] = f"Sessão #{session}"
    data["date"] = session_date
    data["draft"] = False
    extra = data.setdefault("extra", {})
    if not isinstance(extra, dict):
        fail(f"{path}: [extra] inválido")
    extra["session_number"] = session
    extra["youtube_video_id"] = youtube_video_id
    extra["time"] = session_time
    extra["status"] = f"marcada para {session_time}"
    extra["status_tone"] = "scheduled"
    write_session(path, data, body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update the next scheduled xadrez.live session.")
    parser.add_argument("session", nargs="?", help="Session number, e.g. 0056. Defaults to the next number.")
    parser.add_argument("--date", dest="session_date", help="Scheduled date in YYYY-MM-DD. Defaults to tomorrow.")
    parser.add_argument("--time", dest="session_time", help="Scheduled local time in HH:MM.")
    parser.add_argument("--youtube", dest="youtube", help="YouTube video id or URL.")
    parser.add_argument("--no-prompt", action="store_true", help="Fail instead of prompting for missing values.")
    args = parser.parse_args()

    session = args.session or next_session_number()
    if not re.fullmatch(r"\d{4}", session):
        fail(f"sessão inválida: {session}; use NNNN")

    default_date = (date.today() + timedelta(days=1)).isoformat()
    raw_date = args.session_date or ("" if args.no_prompt else prompt("Data da próxima live YYYY-MM-DD", default_date))
    raw_time = args.session_time or ("" if args.no_prompt else prompt("Horário BRT HH:MM", "08:30"))
    raw_youtube = args.youtube or ("" if args.no_prompt else prompt("YouTube URL ou ID"))
    if not raw_date or not raw_time or not raw_youtube:
        fail("data, horário e YouTube ID/URL são obrigatórios")

    session_date = parse_date(raw_date)
    session_time = validate_time(raw_time)
    youtube_video_id = extract_youtube_video_id(raw_youtube)
    if not youtube_video_id:
        fail(f"não consegui extrair o YouTube video id de: {raw_youtube}")

    path = init_from_template(session)
    update_session(path, session, session_date, session_time, youtube_video_id)
    print(f"{session}: scheduled {session_date.isoformat()} {session_time} BRT with YouTube id {youtube_video_id}")
    print(f"Updated {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
