#!/usr/bin/env python3
import argparse
import base64
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import tomllib
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import thumbnail_prompt


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "content/fcz/_thumbnail-templates/post-live-blank-template.png"
OUTPUT_DIR = ROOT / "static/fcz/thumbnails"
OPENAI_IMAGES_EDIT_URL = "https://api.openai.com/v1/images/edits"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_SIZE = "auto"
DEFAULT_QUALITY = "high"


def fail(message):
    raise SystemExit(f"error: {message}")


def load_env_file(path):
    if not path.exists():
        return

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            fail(f"malformed env line in {path}:{line_number}")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            fail(f"missing env key in {path}:{line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def run(command):
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        fail(f"required command not found: {command[0]}")
    except subprocess.CalledProcessError as error:
        fail(f"command failed with exit code {error.returncode}: {' '.join(command)}")


def extract_front_matter(text, path):
    if not text.startswith("+++"):
        fail(f"missing TOML front matter in {path}")

    marker = "\n+++"
    end = text.find(marker, 3)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")

    return text[3:end].strip(), end + len(marker)


def load_session(session):
    path = ROOT / "content" / "fcz" / f"{session}.md"
    if not path.exists():
        fail(f"session file not found: {path}")

    text = path.read_text(encoding="utf-8")
    front_matter, body_start = extract_front_matter(text, path)
    try:
        data = tomllib.loads(front_matter)
    except tomllib.TOMLDecodeError as error:
        fail(f"malformed TOML front matter in {path}: {error}")

    return path, text, front_matter, body_start, data


def default_output(data):
    date = data.get("date")
    if date is None:
        fail("missing session date")

    return OUTPUT_DIR / f"{date:%Y-%m}" / f"{date:%Y%m%d}-post-thumb.jpg"


def relative_site_path(path):
    try:
        static_relative = path.relative_to(ROOT / "static")
    except ValueError:
        return ""
    return "/" + static_relative.as_posix()


def update_session_og_image(path, text, body_start, site_path):
    front = text[:body_start]
    rest = text[body_start:]
    lines = front.splitlines(keepends=True)

    for index, line in enumerate(lines):
        if line.startswith("og_image = "):
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f'og_image = "{site_path}"{newline}'
            path.write_text("".join(lines) + rest, encoding="utf-8")
            return

    fail(f"could not find og_image in {path}")


def multipart_body(fields, files):
    boundary = f"----xadrezlive-{uuid.uuid4().hex}"
    chunks = []

    for name, value in fields:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )

    for name, path in files:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{path.name}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )

    chunks.append(f"--{boundary}--\r\n".encode())
    return boundary, b"".join(chunks)


def decode_api_error(error):
    try:
        payload = error.read().decode("utf-8")
    except Exception:
        return str(error)

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return payload

    message = parsed.get("error", {}).get("message")
    return message or payload


def request_image(prompt, template, model, size, quality, timeout):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        fail("OPENAI_API_KEY is not set")

    fields = [
        ("model", model),
        ("prompt", prompt),
        ("size", size),
        ("quality", quality),
        ("output_format", "png"),
    ]
    boundary, body = multipart_body(fields, [("image[]", template)])
    request = urllib.request.Request(
        OPENAI_IMAGES_EDIT_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        fail(f"OpenAI image edit failed: {decode_api_error(error)}")
    except urllib.error.URLError as error:
        fail(f"OpenAI image edit failed: {error.reason}")

    try:
        image_base64 = payload["data"][0]["b64_json"]
    except (KeyError, IndexError, TypeError):
        fail(f"OpenAI image edit returned no image data: {json.dumps(payload)[:1000]}")

    return base64.b64decode(image_base64)


def normalize_image(input_path, output_path):
    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        run(
            [
                "magick",
                str(input_path),
                "-strip",
                "-resize",
                "1200x675^",
                "-gravity",
                "center",
                "-extent",
                "1200x675",
                "-quality",
                "85",
                str(output_path),
            ]
        )
        return

    if output_path.suffix.lower() == ".png":
        run(
            [
                "magick",
                str(input_path),
                "-strip",
                "-resize",
                "1200x675^",
                "-gravity",
                "center",
                "-extent",
                "1200x675",
                str(output_path),
            ]
        )
        return

    fail("output must end in .jpg, .jpeg, or .png")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a post-live thumbnail by editing the blank template with the OpenAI Image API."
    )
    parser.add_argument("session", help="session number, such as 0029")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output path; defaults to static/fcz/thumbnails/YYYY-MM/YYYYMMDD-post-thumb.jpg",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_IMAGE_MODEL", DEFAULT_MODEL),
        help=f"OpenAI image model; default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--size",
        default=os.environ.get("OPENAI_IMAGE_SIZE", DEFAULT_SIZE),
        help=f"OpenAI image size; default: {DEFAULT_SIZE}",
    )
    parser.add_argument(
        "--quality",
        default=os.environ.get("OPENAI_IMAGE_QUALITY", DEFAULT_QUALITY),
        help=f"OpenAI image quality; default: {DEFAULT_QUALITY}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("OPENAI_IMAGE_TIMEOUT", "180")),
        help="API timeout in seconds; default: 180",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the prompt and paths without calling the API",
    )
    parser.add_argument(
        "--no-update-session",
        action="store_true",
        help="do not update extra.og_image in the session front matter",
    )
    args = parser.parse_args()
    load_env_file(ROOT / ".env")

    if not TEMPLATE.exists():
        fail(f"template not found: {TEMPLATE}")

    if not args.dry_run and shutil.which("magick") is None:
        fail("ImageMagick 'magick' command not found")

    os.chdir(ROOT)
    path, text, _front_matter, body_start, data = load_session(args.session)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        fail(f"missing [extra] in {path}")

    prompt = thumbnail_prompt.prompt("post", thumbnail_prompt.post_data_block(extra))

    output = args.output or default_output(data)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    site_path = relative_site_path(output)
    if not site_path and not args.no_update_session:
        fail("output must be under static/ when updating og_image")

    if args.dry_run:
        print(f"session: {args.session}")
        print(f"template: {TEMPLATE.relative_to(ROOT)}")
        print(f"output: {output.relative_to(ROOT) if output.is_relative_to(ROOT) else output}")
        print(f"model: {args.model}")
        print(f"size: {args.size}")
        print(f"quality: {args.quality}")
        print()
        print(prompt)
        return

    image_bytes = request_image(
        prompt=prompt,
        template=TEMPLATE,
        model=args.model,
        size=args.size,
        quality=args.quality,
        timeout=args.timeout,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        generated = Path(tmp_dir) / "generated.png"
        generated.write_bytes(image_bytes)
        normalize_image(generated, output)

    if not args.no_update_session:
        update_session_og_image(path, text, body_start, site_path)

    try:
        print(output.relative_to(ROOT))
    except ValueError:
        print(output)


if __name__ == "__main__":
    main()
