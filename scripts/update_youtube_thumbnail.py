#!/usr/bin/env python3
"""Upload a session og_image as the YouTube video thumbnail."""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from update_youtube_chapters import ENV_PATH, access_token, env_value, load_env_file


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
STATIC_DIR = ROOT / "static"
YOUTUBE_UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024


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


def session_paths(numbers: set[str]) -> list[Path]:
    paths = []
    for number in sorted(numbers):
        path = CONTENT_DIR / f"{number.zfill(4)}.md"
        if not path.exists():
            raise RuntimeError(f"sessão não encontrada: {number}")
        paths.append(path)
    return paths


def thumbnail_for_session(path: Path) -> tuple[str, str, Path]:
    front_matter = read_front_matter(path)
    extra = front_matter.get("extra")
    if not isinstance(extra, dict):
        raise RuntimeError(f"{path}: seção [extra] não encontrada")

    video_id = str(extra.get("youtube_video_id") or "").strip()
    if not video_id or video_id == "REPLACE_WITH_YOUTUBE_VIDEO_ID":
        raise RuntimeError(f"{path}: youtube_video_id não configurado")

    og_image = str(extra.get("og_image") or "").strip()
    if not og_image:
        raise RuntimeError(f"{path}: og_image não configurado")
    if "://" in og_image:
        raise RuntimeError(f"{path}: og_image deve ser um caminho local do site, não URL absoluta")

    relative = og_image.lstrip("/")
    image_path = STATIC_DIR / relative
    if not image_path.exists():
        raise RuntimeError(f"{path}: thumbnail não encontrada em {image_path.relative_to(ROOT)}")
    if not image_path.is_file():
        raise RuntimeError(f"{path}: thumbnail não é arquivo: {image_path.relative_to(ROOT)}")
    return path.stem, video_id, image_path


def content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed in {"image/jpeg", "image/png"}:
        return guessed
    raise RuntimeError(f"{path}: YouTube aceita thumbnail JPG ou PNG; tipo detectado: {guessed or 'desconhecido'}")


def upload_thumbnail(token: str, video_id: str, image_path: Path) -> dict[str, Any]:
    data = image_path.read_bytes()
    url = f"{YOUTUBE_UPLOAD_API}/thumbnails/set?{urllib.parse.urlencode({'videoId': video_id, 'uploadType': 'media'})}"
    request = urllib.request.Request(
        url,
        method="POST",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": content_type(image_path),
            "Content-Length": str(len(data)),
            "User-Agent": "xadrez-live-youtube-thumbnail/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube thumbnail upload failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"YouTube thumbnail upload failed: {error.reason}") from error


def main() -> int:
    load_env_file(ENV_PATH)
    parser = argparse.ArgumentParser(description="Upload session og_image files as YouTube thumbnails.")
    parser.add_argument("sessions", nargs="+", help="Session numbers, e.g. 0053 0054.")
    parser.add_argument("--write", action="store_true", help="Upload to YouTube. Without this flag, only print a dry run.")
    args = parser.parse_args()

    try:
        items = [thumbnail_for_session(path) for path in session_paths(set(args.sessions))]
    except RuntimeError as error:
        parser.error(str(error))

    for session_number, video_id, image_path in items:
        size = image_path.stat().st_size
        if size > MAX_THUMBNAIL_BYTES:
            parser.error(
                f"{session_number}: thumbnail tem {size} bytes; YouTube permite no máximo {MAX_THUMBNAIL_BYTES} bytes"
            )
        print(f"{session_number}: {video_id} <- {image_path.relative_to(ROOT)} ({size} bytes)")

    if not args.write:
        print(f"dry run: {len(items)} thumbnail(s); use --write to upload")
        return 0

    client_id = env_value("YOUTUBE_CLIENT_ID")
    client_secret = env_value("YOUTUBE_CLIENT_SECRET")
    refresh_token = env_value("YOUTUBE_REFRESH_TOKEN")
    if not client_id or not client_secret:
        raise SystemExit("error: set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env")
    if not refresh_token:
        raise SystemExit("error: set YOUTUBE_REFRESH_TOKEN in .env or run `just youtube-chapters-authorize` first")

    token = access_token(client_id, client_secret, refresh_token)
    uploaded = 0
    for session_number, video_id, image_path in items:
        try:
            upload_thumbnail(token, video_id, image_path)
        except RuntimeError as error:
            print(f"{session_number}: {error}", file=sys.stderr)
            continue
        uploaded += 1
        print(f"{session_number}: uploaded thumbnail")
    print(f"summary: {uploaded} uploaded, {len(items) - uploaded} failed")
    return 0 if uploaded == len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
