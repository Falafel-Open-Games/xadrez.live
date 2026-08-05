#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tomllib
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
SITEMAP = ROOT / "public" / "sitemap.xml"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def read_config() -> dict[str, Any]:
    return tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))


def run_git(args: list[str], path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args, "--", str(path.relative_to(ROOT))],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def session_paths() -> list[Path]:
    return sorted((CONTENT_DIR / "fcz").glob("[0-9][0-9][0-9][0-9].md"))


def content_paths_for_url(url: str, base_url: str) -> list[Path]:
    if not url.startswith(base_url.rstrip("/") + "/"):
        return []

    relative = url.removeprefix(base_url.rstrip("/") + "/").strip("/")
    if not relative:
        return [CONTENT_DIR / "_index.md", *session_paths(), ROOT / "data" / "external_streams.toml"]

    parts = relative.split("/")
    if len(parts) == 1:
        content_path = CONTENT_DIR / f"{parts[0]}.md"
        if parts[0] in {"arquivo", "busca"}:
            return [content_path, *session_paths()]
        if parts[0] == "estatisticas":
            return [content_path, ROOT / "data" / "site_stats.toml"]
        if parts[0] == "apoiadores":
            return [content_path, ROOT / "data" / "supporters.toml"]
        return [content_path]

    if len(parts) == 2 and parts[0] == "fcz":
        return [CONTENT_DIR / "fcz" / f"{parts[1]}.md"]

    return []


def front_matter_date(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        return ""

    end = text.find("\n+++", 4)
    if end == -1:
        return ""

    try:
        data = tomllib.loads(text[4:end])
    except tomllib.TOMLDecodeError:
        return ""

    value = data.get("updated") or data.get("date") or ""
    return str(value)


def is_dirty(path: Path) -> bool:
    proc = run_git(["diff", "--quiet"], path)
    return proc.returncode == 1


def git_lastmod(path: Path) -> str:
    if is_dirty(path):
        return date.today().isoformat()

    proc = run_git(["log", "-1", "--format=%cs"], path)
    return proc.stdout.strip()


def lastmod_for_path(path: Path) -> str:
    if not path.exists():
        return ""
    return git_lastmod(path) or front_matter_date(path)


def lastmod_for_paths(paths: list[Path]) -> str:
    return max((lastmod for path in paths if (lastmod := lastmod_for_path(path))), default="")


def update_sitemap() -> int:
    if not SITEMAP.exists():
        raise SystemExit(f"missing sitemap: {SITEMAP}")

    base_url = str(read_config().get("base_url") or "").rstrip("/")
    if not base_url:
        raise SystemExit("config.toml must define base_url")

    ET.register_namespace("", NS)
    tree = ET.parse(SITEMAP)
    root = tree.getroot()
    changed = 0

    for url_element in root.findall(f"{{{NS}}}url"):
        loc = url_element.find(f"{{{NS}}}loc")
        if loc is None or not loc.text:
            continue

        paths = content_paths_for_url(loc.text, base_url)
        if not paths:
            continue

        lastmod = lastmod_for_paths(paths)
        if not lastmod:
            continue

        lastmod_element = url_element.find(f"{{{NS}}}lastmod")
        if lastmod_element is None:
            loc_index = list(url_element).index(loc)
            lastmod_element = ET.Element(f"{{{NS}}}lastmod")
            url_element.insert(loc_index + 1, lastmod_element)

        if lastmod_element.text != lastmod:
            lastmod_element.text = lastmod
            changed += 1

    ET.indent(tree, space="    ")
    tree.write(SITEMAP, encoding="utf-8", xml_declaration=True)
    print(f"Updated sitemap lastmod for {changed} URL(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(update_sitemap())
