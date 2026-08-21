#!/usr/bin/env python3
"""Generate and optionally publish YouTube descriptions from session data."""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
TIMELINE_DIR = ROOT / "data" / "fcz" / "lichess_blunders"
EDITORIAL_CHOICES_PATH = ROOT / "data" / "fcz" / "youtube_editorial_choices.json"
ENV_PATH = ROOT / ".env"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/youtube/oauth/callback"
DEFAULT_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
CHAPTERS_START = "[xadrez.live chapters:start]"
CHAPTERS_END = "[xadrez.live chapters:end]"
SESSION_START = "[xadrez.live session:start]"
SESSION_END = "[xadrez.live session:end]"
CHANNEL_INTRO = (
    "Eu sou o Fabricio, jogador amador praticando xadrez depois dos 40. "
    "No xadrez.live eu registro puzzles, partidas rapid, capivaradas, conversas do chat "
    "e o progresso real de cada sessão."
)
MAX_DESCRIPTION_BYTES = 5000


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    if output and output[-1].strip():
        output.append("")
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def env_value(*names: str) -> str:
    for name in names:
        if os.environ.get(name):
            return str(os.environ[name])
    return ""


def read_front_matter(path: Path) -> dict[str, Any]:
    import tomllib

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


def selected_description_hook(session_number: str) -> str:
    if not EDITORIAL_CHOICES_PATH.exists():
        return ""
    try:
        data = json.loads(EDITORIAL_CHOICES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    session = data.get("sessions", {}).get(session_number, {})
    hooks = session.get("description_hooks", {}) if isinstance(session, dict) else {}
    return str(hooks.get("selected") or "") if isinstance(hooks, dict) else ""


def session_paths(numbers: set[str] | None) -> list[Path]:
    paths = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        data = read_front_matter(path)
        extra = data.get("extra")
        if not isinstance(extra, dict) or data.get("draft") is True:
            continue
        video_id = str(extra.get("youtube_video_id") or "").strip()
        if not video_id or video_id == "REPLACE_WITH_YOUTUBE_VIDEO_ID":
            continue
        if numbers is None or path.stem in numbers:
            paths.append(path)
    return paths


def expand_session_args(values: list[str]) -> set[str] | None:
    if not values:
        return None
    expanded: set[str] = set()
    for value in values:
        value = value.strip()
        if not value:
            continue
        if "-" in value:
            start_raw, end_raw = value.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
            step = 1 if start <= end else -1
            for number in range(start, end + step, step):
                expanded.add(f"{number:04d}")
        else:
            expanded.add(value.zfill(4))
    return expanded


def format_timestamp(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def chapter_label(event: dict[str, Any]) -> str:
    label = str(event.get("label") or "Evento").strip()
    if event.get("kind") == "blunder":
        color = {"white": "brancas", "black": "pretas"}.get(str(event.get("color") or ""), "")
        clock = str(event.get("clock") or "").strip()
        clock_text = ""
        if clock:
            parts = clock.split(":")
            if len(parts) == 2:
                clock_text = f"relógio {parts[0]} min {parts[1]} s"
            else:
                clock_text = f"relógio {clock}"
        details = ", ".join(value for value in (color, clock_text) if value)
        if details:
            return f"{label} ({details})"
    return label


def site_url_for_session(session_number: str) -> str:
    return f"https://xadrez.live/fcz/{session_number}/"


def session_neighbor_urls(session_number: str) -> tuple[str, str]:
    try:
        current = int(session_number)
    except ValueError:
        return "", ""
    previous_path = CONTENT_DIR / f"{current - 1:04d}.md"
    next_path = CONTENT_DIR / f"{current + 1:04d}.md"
    previous_url = site_url_for_session(f"{current - 1:04d}") if previous_path.exists() else ""
    next_url = site_url_for_session(f"{current + 1:04d}") if next_path.exists() else ""
    return previous_url, next_url


def timeline_for_session(path: Path) -> tuple[Path, str, str, list[dict[str, Any]]]:
    data = read_front_matter(path)
    extra = data.get("extra")
    assert isinstance(extra, dict)
    session_number = path.stem
    video_id = str(extra.get("youtube_video_id") or "").strip()
    timeline_path = TIMELINE_DIR / f"{session_number}.json"
    if not timeline_path.exists():
        return path, session_number, video_id, []
    try:
        timeline_data = json.loads(timeline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return path, session_number, video_id, []
    events = timeline_data.get("timeline")
    if not isinstance(events, list):
        return path, session_number, video_id, []
    chapters: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        seconds = event.get("seconds")
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            continue
        label = chapter_label(event)
        if seconds < 0 or not label:
            continue
        if chapters and seconds - chapters[-1]["seconds"] < 10:
            continue
        chapters.append({"seconds": seconds, "label": label})
    if not chapters or chapters[0]["seconds"] != 0:
        chapters.insert(0, {"seconds": 0, "label": "Início"})
    return path, session_number, video_id, chapters


def chapter_block(chapters: list[dict[str, Any]]) -> str:
    lines = [CHAPTERS_START]
    lines.extend(f"{format_timestamp(item['seconds'])} {item['label']}" for item in chapters)
    lines.append(CHAPTERS_END)
    return "\n".join(lines)


def replace_block(description: str, start_marker: str, end_marker: str, block: str) -> str:
    start = description.find(start_marker)
    end = description.find(end_marker)
    if start != -1 and end >= start:
        end += len(end_marker)
        return description[:start].rstrip() + "\n\n" + block + description[end:].lstrip()
    return description.rstrip() + "\n\n" + block + "\n"


def session_block(path: Path) -> str:
    data = read_front_matter(path)
    extra = data.get("extra") if isinstance(data, dict) else {}
    if not isinstance(extra, dict):
        extra = {}
    session_number = str(extra.get("session_number") or path.stem)
    lines = [SESSION_START]
    description = selected_description_hook(session_number) or youtube_description_summary(str(extra.get("description") or ""))
    if description:
        lines.extend([description, ""])
    lines.extend([CHANNEL_INTRO, ""])
    lines.append(f"Página da sessão: {site_url_for_session(session_number)}")

    puzzle_url = str(extra.get("puzzle_of_the_day_url") or "").strip()
    if puzzle_url:
        lines.append(f"Puzzle do dia: {puzzle_url}")

    games = extra.get("games")
    if isinstance(games, list):
        for index, game in enumerate(games, start=1):
            if not isinstance(game, dict):
                continue
            game_url = str(game.get("game_url") or game.get("lichess_game_url") or "").strip()
            opening = str(game.get("opening") or "").strip()
            if game_url:
                label = f"Partida {index}"
                if opening:
                    label += f" ({opening})"
                lines.append(f"{label}: {game_url}")

    practice_sets = extra.get("practice_sets")
    if isinstance(practice_sets, list):
        for practice_set in practice_sets:
            if not isinstance(practice_set, dict):
                continue
            title = str(practice_set.get("title") or "Treino").strip()
            url = str(practice_set.get("url") or "").strip()
            if url:
                lines.append(f"Treino: {title} - {url}")

    previous_url, next_url = session_neighbor_urls(session_number)
    if previous_url:
        lines.append(f"Sessão anterior: {previous_url}")
    if next_url:
        lines.append(f"Próxima sessão: {next_url}")

    lines.append(SESSION_END)
    return "\n".join(lines)


def youtube_description_summary(description: str) -> str:
    summary = " ".join(description.split()).strip()
    replacements = [
        (r"^Sessão de \d+h\d{1,2}\s+com\s+", ""),
        (r"^Sessão de \d+h\s+com\s+", ""),
        (r"^Sessão de \d+min\s+com\s+", ""),
        (r"^Sessão com\s+", ""),
    ]
    for pattern, replacement in replacements:
        summary = re.sub(pattern, replacement, summary, flags=re.I)
    if summary:
        summary = summary[0].upper() + summary[1:]
    return summary


def update_description(description: str, path: Path, chapters: list[dict[str, Any]], include_session_block: bool) -> str:
    if include_session_block:
        managed_description = replace_block("", SESSION_START, SESSION_END, session_block(path))
        return replace_block(managed_description, CHAPTERS_START, CHAPTERS_END, chapter_block(chapters))
    return replace_block(description, CHAPTERS_START, CHAPTERS_END, chapter_block(chapters))


def has_chapter_block(description: str) -> bool:
    start = description.find(CHAPTERS_START)
    end = description.find(CHAPTERS_END)
    return start != -1 and end > start


def validate_description(description: str) -> None:
    size = len(description.encode("utf-8"))
    if size > MAX_DESCRIPTION_BYTES:
        raise RuntimeError(f"generated description is {size} bytes; YouTube allows at most {MAX_DESCRIPTION_BYTES} bytes")


def normalized_description(description: str) -> str:
    return description.replace("\r\n", "\n").replace("\r", "\n").strip()


def api_request(path: str, token: str, *, method: str = "GET", query: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{YOUTUBE_API}/{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "xadrez-live-youtube-chapters/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube API request failed with HTTP {error.code}: {detail}") from error


def token_request(client_id: str, client_secret: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        method="POST",
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    )
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    request.add_header("Authorization", f"Basic {credentials}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            detail = error.read().decode("utf-8", errors="replace")
        finally:
            error.close()
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = {}
        if payload.get("error") == "invalid_grant":
            detail += (
                "\n\nYOUTUBE_REFRESH_TOKEN expired or was revoked. "
                "Run `just youtube-chapters-authorize`, then rerun the wrapup step."
            )
        raise RuntimeError(f"Google token request failed with HTTP {error.code}: {detail}") from error


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    server: "OAuthServer"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path != self.server.callback_path:
            self.send_response(404)
            self.end_headers()
            return
        error = query.get("error", [""])[0]
        if error:
            self.server.error = error
            self.respond("YouTube authorization failed", error)
            return
        if query.get("state", [""])[0] != self.server.expected_state:
            self.server.error = "OAuth state mismatch"
            self.respond("YouTube authorization failed", self.server.error)
            return
        self.server.code = query.get("code", [""])[0]
        if not self.server.code:
            self.server.error = "Google did not return an authorization code"
            self.respond("YouTube authorization failed", self.server.error)
            return
        self.respond("YouTube authorization complete", "You can return to the terminal.")

    def log_message(self, format: str, *args: object) -> None:
        return

    def respond(self, title: str, message: str) -> None:
        body = f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class OAuthServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], callback_path: str, state: str):
        super().__init__(address, OAuthCallbackHandler)
        self.callback_path = callback_path
        self.expected_state = state
        self.code = ""
        self.error = ""


def authorize(client_id: str, client_secret: str, redirect_uri: str, write_env: bool) -> None:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("YouTube OAuth requires a local redirect URI")
    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DEFAULT_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    server = OAuthServer((parsed.hostname or "127.0.0.1", parsed.port or 8765), parsed.path or "/", state)
    print("Register this exact redirect URI in Google Cloud:", redirect_uri, "\n", sep="\n")
    print(f"Open this URL and authorize the app:\n{GOOGLE_AUTHORIZE_URL}?{query}\n", flush=True)
    while not server.code and not server.error:
        server.handle_request()
    server.server_close()
    if server.error:
        raise RuntimeError(server.error)
    data = token_request(client_id, client_secret, {"code": server.code, "grant_type": "authorization_code", "redirect_uri": redirect_uri})
    refresh_token = str(data.get("refresh_token") or "")
    if not refresh_token:
        raise RuntimeError("Google did not return a refresh token; authorize again with prompt=consent")
    if write_env:
        update_env_file(ENV_PATH, {"YOUTUBE_REFRESH_TOKEN": refresh_token})
    print("YouTube OAuth authorization complete.")


def access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    data = token_request(client_id, client_secret, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    token = str(data.get("access_token") or "")
    if not token:
        raise RuntimeError("Google did not return an access token")
    return token


def fetch_video_snippets(token: str, video_ids: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(video_ids), 50):
        payload = api_request("videos", token, query={"part": "snippet", "id": ",".join(video_ids[offset : offset + 50])})
        for item in payload.get("items", []):
            if isinstance(item, dict) and item.get("id") and isinstance(item.get("snippet"), dict):
                result[str(item["id"])] = item["snippet"]
    return result


def updated_snippet(snippet: dict[str, Any], description: str) -> dict[str, Any]:
    output = {"title": str(snippet.get("title") or ""), "description": description, "categoryId": str(snippet.get("categoryId") or "22")}
    for key in ("tags", "defaultLanguage", "defaultAudioLanguage"):
        if key in snippet:
            output[key] = snippet[key]
    return output


def has_gum() -> bool:
    return shutil.which("gum") is not None


def confirm(message: str) -> bool:
    if has_gum():
        return subprocess.run(["gum", "confirm", message], check=False).returncode == 0
    return input(f"{message} Type YES to continue: ").strip() == "YES"


def confirm_description(session_number: str, video_id: str, description: str) -> bool:
    print()
    print(f"{session_number} ({video_id}) description preview")
    print("-" * 72)
    print(description.strip())
    print("-" * 72)
    return confirm("Publicar esta descrição no YouTube?")


def main() -> int:
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Generate and publish YouTube descriptions from xadrez.live session data.")
    parser.add_argument("sessions", nargs="*", help="Session numbers, e.g. 0052. Omit for all sessions.")
    parser.add_argument("--write", action="store_true", help="Update YouTube descriptions. Without this flag, only print a dry run.")
    parser.add_argument("--confirm", action="store_true", help="Preview each generated description and require confirmation before publishing.")
    parser.add_argument("--chapters-only", action="store_true", help="Only manage the chapter block, preserving the rest of the description.")
    parser.add_argument("--missing-only", action="store_true", help="Only include videos without the xadrez.live chapter block on YouTube.")
    parser.add_argument("--authorize", action="store_true", help="Run the local Google OAuth authorization flow.")
    parser.add_argument("--write-env", action="store_true", help="Store the OAuth refresh token in .env during --authorize.")
    parser.add_argument("--redirect-uri", default=os.environ.get("YOUTUBE_REDIRECT_URI", DEFAULT_REDIRECT_URI))
    args = parser.parse_args()

    client_id = env_value("YOUTUBE_CLIENT_ID")
    client_secret = env_value("YOUTUBE_CLIENT_SECRET")
    if args.authorize:
        if not client_id or not client_secret:
            raise SystemExit("error: set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first")
        authorize(client_id, client_secret, args.redirect_uri, args.write_env)
        return 0

    paths = session_paths(expand_session_args(args.sessions))
    generated = [timeline_for_session(path) for path in paths]
    generated = [item for item in generated if item[2] and item[3] and len(item[3]) >= 3]
    if not generated:
        print("No sessions have at least three valid timeline chapters.")
        return 0

    snippets: dict[str, dict[str, Any]] = {}
    if args.write or args.missing_only:
        if not client_id or not client_secret:
            raise SystemExit("error: set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env")
        refresh_token = env_value("YOUTUBE_REFRESH_TOKEN")
        if not refresh_token:
            raise SystemExit("error: set YOUTUBE_REFRESH_TOKEN in .env or run --authorize --write-env first")
        token = access_token(client_id, client_secret, refresh_token)
        snippets = fetch_video_snippets(token, [video_id for _, _, video_id, _ in generated])
    else:
        token = ""

    if args.missing_only:
        missing = []
        for path, session_number, video_id, chapters in generated:
            snippet = snippets.get(video_id)
            if not snippet:
                print(f"{session_number}: video {video_id} was not returned by YouTube")
                continue
            description = str(snippet.get("description") or "")
            if not has_chapter_block(description):
                missing.append((path, session_number, video_id, chapters))
        generated = missing
        if not generated:
            print("No sessions are missing the xadrez.live chapter block on YouTube.")
            return 0

    if not args.write:
        for path, session_number, video_id, chapters in generated:
            print(f"\n{session_number} ({video_id})")
            print(update_description("", path, chapters, not args.chapters_only).strip())
        qualifier = " missing" if args.missing_only else ""
        print(f"\ndry run: {len(generated)}{qualifier} session(s); use --write to update YouTube descriptions")
        return 0

    updated = 0
    for path, session_number, video_id, chapters in generated:
        snippet = snippets.get(video_id)
        if not snippet:
            print(f"{session_number}: video {video_id} was not returned by YouTube")
            continue
        description = str(snippet.get("description") or "")
        next_description = normalized_description(update_description(description, path, chapters, not args.chapters_only))
        validate_description(next_description)
        if normalized_description(next_description) == normalized_description(description):
            print(f"{session_number}: unchanged")
            continue
        if args.confirm and not confirm_description(session_number, video_id, next_description):
            print(f"{session_number}: skipped")
            continue
        api_request("videos", token, method="PUT", query={"part": "snippet"}, body={"id": video_id, "snippet": updated_snippet(snippet, next_description)})
        updated += 1
        print(f"{session_number}: updated {len(chapters)} chapters")
    print(f"summary: {updated} updated, {len(generated) - updated} unchanged")
    return 0


def cli_main() -> int:
    try:
        return main()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli_main())
