#!/usr/bin/env python3
import argparse
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

from wrap_session import read_session, write_session


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "content/fcz/_thumbnail-templates/pre-live-offline-template.jpg"
OUTPUT_DIR = ROOT / "static/fcz/thumbnails"
FONT = "Adwaita-Sans-Bold"
NAVY = "#0a2f66"


def fail(message):
    raise SystemExit(f"error: {message}")


def run(command):
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        fail("ImageMagick 'magick' command not found")
    except subprocess.CalledProcessError as error:
        fail(f"command failed with exit code {error.returncode}: {' '.join(command)}")


def extract_front_matter(text, path):
    if not text.startswith("+++"):
        fail(f"missing TOML front matter in {path}")

    marker = "\n+++"
    end = text.find(marker, 3)
    if end == -1:
        fail(f"malformed front matter in {path}: missing closing +++")

    return text[3:end].strip()


def load_session(session):
    path = ROOT / "content" / "fcz" / f"{session}.md"
    if not path.exists():
        fail(f"session file not found: {path}")

    try:
        return tomllib.loads(extract_front_matter(path.read_text(encoding="utf-8"), path))
    except tomllib.TOMLDecodeError as error:
        fail(f"malformed TOML front matter in {path}: {error}")


def update_session_og_image(session, output):
    try:
        relative = output.relative_to(ROOT / "static")
    except ValueError:
        fail(f"output must be under static/ to be used as og_image: {output}")

    path, data, body = read_session(session)
    extra = data.setdefault("extra", {})
    if not isinstance(extra, dict):
        fail(f"missing [extra] in content/fcz/{session}.md")
    extra["og_image"] = "/" + relative.as_posix()
    write_session(path, data, body)


def normalized_time(raw):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", raw)
    if not match:
        fail(f"time must look like HH:MM, got {raw!r}")

    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        fail(f"time out of range: {raw!r}")

    return f"{hour:02d}:{minute:02d}"


def make_label(text, output, size, pointsize, interline_spacing=0):
    run(
        [
            "magick",
            "-size",
            size,
            "xc:none",
            "-fill",
            NAVY,
            "-font",
            FONT,
            "-pointsize",
            str(pointsize),
            "-interline-spacing",
            str(interline_spacing),
            "-gravity",
            "center",
            "-annotate",
            "0",
            text,
            str(output),
        ]
    )


def make_stacked_label(lines, output, size, top_size, bottom_size, top_y, bottom_y):
    run(
        [
            "magick",
            "-size",
            size,
            "xc:none",
            "-fill",
            NAVY,
            "-font",
            FONT,
            "-pointsize",
            str(top_size),
            "-gravity",
            "north",
            "-annotate",
            f"+0+{top_y}",
            lines[0],
            "-pointsize",
            str(bottom_size),
            "-gravity",
            "south",
            "-annotate",
            f"+0+{bottom_y}",
            lines[1],
            str(output),
        ]
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate a pre-live thumbnail from the offline template."
    )
    parser.add_argument("session", help="session number, such as 0016")
    parser.add_argument(
        "time",
        nargs="?",
        help="live start time as HH:MM; defaults to content/fcz/SESSION.md extra.time",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output image path; defaults to static/fcz/thumbnails/YYYYMMDD-pre-thumb.jpg",
    )
    args = parser.parse_args()

    if not TEMPLATE.exists():
        fail(f"template not found: {TEMPLATE}")

    data = load_session(args.session)
    extra = data.get("extra")
    if not isinstance(extra, dict):
        fail(f"missing [extra] in content/fcz/{args.session}.md")

    session_number = str(extra.get("session_number") or args.session).strip()
    time = normalized_time(args.time or str(extra.get("time", "")).strip())

    date = data.get("date")
    if date is None:
        fail(f"missing date in content/fcz/{args.session}.md")

    output = args.output
    if output is None:
        output = OUTPUT_DIR / f"{date:%Y-%m}" / f"{date:%Y%m%d}-pre-thumb.jpg"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        session_label = tmp / "session.png"
        time_label = tmp / "time.png"
        composed = tmp / "composed.png"

        make_stacked_label(["sessão #", session_number], session_label, "320x150", 34, 54, 14, 12)
        make_stacked_label(["horário", f"{time} BRT"], time_label, "320x150", 32, 42, 15, 22)

        run(
            [
                "magick",
                str(TEMPLATE),
                str(session_label),
                "-geometry",
                "+190+612",
                "-composite",
                str(time_label),
                "-geometry",
                "+530+612",
                "-composite",
                str(composed),
            ]
        )
        run(
            [
                "magick",
                str(composed),
                "-strip",
                "-resize",
                "1200x675",
                "-quality",
                "85",
                str(output),
            ]
        )

    try:
        print(output.relative_to(ROOT))
    except ValueError:
        print(output)
    update_session_og_image(args.session, output)


if __name__ == "__main__":
    main()
