#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
SESSION_DIR = CONTENT_DIR / "fcz"
STATIC_DIR = ROOT / "static"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
KEY_FILE = STATIC_DIR / "f404fb61ed9739fe47f43ce69afbe879.txt"


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def read_config() -> dict[str, Any]:
    return tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))


def extract_front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++"):
        return {}
    end = text.find("\n+++", 3)
    if end == -1:
        return {}
    return tomllib.loads(text[3:end].strip())


def page_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.strip('/')}/" if path else base_url.rstrip("/") + "/"


def static_pages(base_url: str) -> list[str]:
    urls = [page_url(base_url, "")]
    for path in sorted(CONTENT_DIR.glob("*.md")):
        if path.name == "_index.md":
            continue
        data = extract_front_matter(path)
        if bool(data.get("draft")):
            continue
        urls.append(page_url(base_url, path.stem))
    return urls


def recent_session_pages(base_url: str, limit: int) -> list[str]:
    sessions = []
    for path in sorted(SESSION_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        data = extract_front_matter(path)
        if bool(data.get("draft")):
            continue
        sessions.append(path.stem)
    return [page_url(base_url, f"fcz/{session}") for session in sessions[-limit:]]


def unique(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def build_payload(base_url: str, key: str, urls: list[str]) -> dict[str, Any]:
    host = base_url.removeprefix("https://").removeprefix("http://").strip("/")
    key_location = f"{base_url.rstrip('/')}/{KEY_FILE.name}"
    return {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }


def submit(payload: dict[str, Any], endpoint: str) -> int:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            print(f"IndexNow accepted {len(payload['urlList'])} URL(s): HTTP {response.status}")
            return 0
    except urllib.error.HTTPError as error:
        print(f"IndexNow rejected request: HTTP {error.code} {error.reason}")
        print(error.read().decode("utf-8", errors="replace"))
        return 1
    except urllib.error.URLError as error:
        print(f"IndexNow request failed: {error.reason}")
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit recently changed xadrez.live URLs to IndexNow.")
    parser.add_argument("--recent-sessions", type=int, default=10, help="Number of latest session pages to include.")
    parser.add_argument("--endpoint", default=INDEXNOW_ENDPOINT)
    parser.add_argument("--dry-run", action="store_true", help="Print the payload without submitting.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = read_config()
    base_url = str(config.get("base_url") or "").strip()
    if not base_url:
        fail("config.toml must define base_url")
    if not KEY_FILE.exists():
        fail(f"missing IndexNow key file: {KEY_FILE}")

    key = KEY_FILE.read_text(encoding="utf-8").strip()
    urls = unique(static_pages(base_url) + recent_session_pages(base_url, max(0, args.recent_sessions)))
    payload = build_payload(base_url, key, urls)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    return submit(payload, args.endpoint)


if __name__ == "__main__":
    raise SystemExit(main())
