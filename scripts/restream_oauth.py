#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/restream/oauth/callback"
TOKEN_URL = "https://api.restream.io/oauth/token"
DEFAULT_AUTHORIZE_URL = "https://api.restream.io/oauth/authorize"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
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
        value = os.environ.get(name)
        if value:
            return value
    return ""


def token_request(client_id: str, client_secret: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        method="POST",
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "xadrez-live-restream-oauth/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Restream token request failed with HTTP {error.code}: {body}") from error


def token_updates(data: dict[str, Any]) -> dict[str, str]:
    access_token = str(data.get("access_token") or data.get("accessToken") or "")
    refresh_token = str(data.get("refresh_token") or data.get("refreshToken") or "")
    expires = str(data.get("expires") or data.get("accessTokenExpiresEpoch") or "")
    if not access_token or not refresh_token:
        raise RuntimeError("Restream token response did not include access and refresh tokens")

    updates = {
        "RESTREAM_ACCESS_TOKEN": access_token,
        "RESTREAM_REFRESH_TOKEN": refresh_token,
    }
    if expires:
        updates["RESTREAM_ACCESS_TOKEN_EXPIRES"] = expires
    return updates


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    server: "OAuthServer"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        code = query.get("code", [""])[0]
        state = query.get("state", [""])[0]
        error = query.get("error", [""])[0]

        if parsed.path != self.server.callback_path:
            self.send_response(404)
            self.end_headers()
            return

        if error:
            self.server.error = error
            self.respond("Restream authorization failed", error)
            return

        if not code:
            scope = query.get("scope", [""])[0]
            raw_query = parsed.query or "empty"
            self.server.error = (
                "Restream did not return an authorization code. "
                "Check that the app authorization was accepted and that the app has stream.read and chat.read scopes. "
                f"Returned scope: {scope or 'none'}. Raw callback query: {raw_query}."
            )
            self.respond("Restream authorization failed", self.server.error)
            return

        if state != self.server.expected_state:
            self.server.error = "State mismatch; refusing to exchange authorization code."
            self.respond("Restream authorization failed", self.server.error)
            return

        self.server.code = code
        self.respond("Restream authorization complete", "You can return to the terminal.")

    def log_message(self, format: str, *args: object) -> None:
        return

    def respond(self, title: str, message: str) -> None:
        body = (
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title>"
            f"<h1>{html.escape(title)}</h1>"
            f"<p>{html.escape(message)}</p>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class OAuthServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[OAuthCallbackHandler], callback_path: str, expected_state: str):
        super().__init__(server_address, handler_class)
        self.callback_path = callback_path
        self.expected_state = expected_state
        self.code = ""
        self.error = ""


def authorize(
    client_id: str,
    client_secret: str,
    authorize_url: str,
    redirect_uri: str,
    scope: str,
    write_env: bool,
) -> dict[str, str]:
    parsed_redirect = urllib.parse.urlparse(redirect_uri)
    if parsed_redirect.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("this helper only starts local callback servers")

    state = secrets.token_urlsafe(24)
    query_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scope:
        query_params["scope"] = scope
    query = urllib.parse.urlencode(query_params)
    auth_url = f"{authorize_url}?{query}"

    server = OAuthServer(
        (parsed_redirect.hostname or "127.0.0.1", parsed_redirect.port or 8765),
        OAuthCallbackHandler,
        parsed_redirect.path or "/",
        state,
    )

    print("Register this exact Redirect URI in the Restream application:", flush=True)
    print(redirect_uri, flush=True)
    print(flush=True)
    print("Open this URL, authorize the app, and wait for the local callback:", flush=True)
    print(auth_url, flush=True)
    print(flush=True)

    while not server.code and not server.error:
        server.handle_request()

    if server.error:
        raise RuntimeError(server.error)

    data = token_request(
        client_id,
        client_secret,
        {
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": server.code,
        },
    )
    updates = token_updates(data)
    if write_env:
        update_env_file(ENV_PATH, updates)
    return updates


def refresh(client_id: str, client_secret: str, refresh_token: str, write_env: bool) -> dict[str, str]:
    data = token_request(
        client_id,
        client_secret,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    updates = token_updates(data)
    if write_env:
        update_env_file(ENV_PATH, updates)
    return updates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Authorize or refresh Restream OAuth tokens for local imports.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("authorize")
    auth_parser.add_argument("--authorize-url", default=os.environ.get("RESTREAM_AUTHORIZE_URL", DEFAULT_AUTHORIZE_URL))
    auth_parser.add_argument("--redirect-uri", default=os.environ.get("RESTREAM_REDIRECT_URI", DEFAULT_REDIRECT_URI))
    auth_parser.add_argument("--scope", default=os.environ.get("RESTREAM_SCOPES", "profile.read channels.read stream.read events.read chat.read"))
    auth_parser.add_argument("--write-env", action="store_true", help="Write RESTREAM_ACCESS_TOKEN and RESTREAM_REFRESH_TOKEN to .env.")

    refresh_parser = subparsers.add_parser("refresh")
    refresh_parser.add_argument("--write-env", action="store_true", help="Write refreshed tokens to .env.")

    return parser.parse_args()


def main() -> int:
    load_env_file(ENV_PATH)
    args = parse_args()
    client_id = env_value("RESTREAM_CLIENT_ID", "RESTREAM_API_CLIENT_ID")
    client_secret = env_value("RESTREAM_CLIENT_SECRET", "RESTREAM_API_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit("error: set RESTREAM_CLIENT_ID and RESTREAM_CLIENT_SECRET in .env")

    if args.command == "authorize":
        updates = authorize(client_id, client_secret, args.authorize_url, args.redirect_uri, args.scope, args.write_env)
    else:
        refresh_token = env_value("RESTREAM_REFRESH_TOKEN")
        if not refresh_token:
            raise SystemExit("error: set RESTREAM_REFRESH_TOKEN in .env or run authorize first")
        updates = refresh(client_id, client_secret, refresh_token, args.write_env)

    print("Restream OAuth tokens received.", flush=True)
    if args.write_env:
        print(f"Updated {ENV_PATH}", flush=True)
    else:
        print("Run again with --write-env to store them in .env.", flush=True)
        for key, value in updates.items():
            print(f"{key}={value}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
