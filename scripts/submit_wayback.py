#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITEMAP = ROOT / "public" / "sitemap.xml"
WAYBACK_SAVE_URL = "https://web.archive.org/save/"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def fail(message: str) -> None:
    print(f"error: {message}")
    raise SystemExit(1)


def sitemap_urls(path: Path) -> list[str]:
    if not path.exists():
        fail(f"missing sitemap: {path}. Run `just build` first.")
    root = ET.parse(path).getroot()
    urls = []
    for loc in root.findall(".//sm:loc", SITEMAP_NS):
        url = (loc.text or "").strip()
        if url:
            urls.append(url)
    return unique(urls)


def unique(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def archive_url(url: str, timeout: int) -> tuple[bool, str, bool]:
    request = urllib.request.Request(
        WAYBACK_SAVE_URL + urllib.parse.quote(url, safe=":/?&=%#"),
        method="POST",
        headers={
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "User-Agent": "xadrez-live-wayback-submit/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            location = response.headers.get("Content-Location") or response.geturl()
            return True, f"HTTP {response.status} {location}", False
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        return False, f"HTTP {error.code} {error.reason}: {detail[:240]}", error.code in RETRYABLE_HTTP_STATUS
    except urllib.error.URLError as error:
        return False, str(error.reason), True


def archive_url_with_retries(url: str, timeout: int, retries: int, retry_delay: float) -> tuple[bool, str]:
    messages = []
    for attempt in range(retries + 1):
        ok, message, retryable = archive_url(url, timeout)
        if ok:
            return True, message
        messages.append(message)
        if not retryable or attempt >= retries:
            return False, " | ".join(messages)
        sleep_for = retry_delay * (2**attempt)
        print(f"  retrying in {sleep_for:.1f}s after {message}", flush=True)
        time.sleep(sleep_for)
    return False, "unknown retry failure"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit sitemap URLs to Internet Archive Save Page Now.")
    parser.add_argument("--write", action="store_true", help="Submit URLs. Without this flag, only list what would be submitted.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N URLs.")
    parser.add_argument("--start", type=int, default=1, help="1-based index to start from, useful for resuming after a failed run.")
    parser.add_argument("--delay", type=float, default=10.0, help="Seconds to wait between submissions.")
    parser.add_argument("--retries", type=int, default=2, help="Retries for temporary HTTP/network failures.")
    parser.add_argument("--retry-delay", type=float, default=30.0, help="Base seconds to wait before retrying temporary failures.")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout per URL.")
    parser.add_argument("--sitemap", type=Path, default=SITEMAP)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    urls = sitemap_urls(args.sitemap)
    if args.start < 1:
        fail("--start must be 1 or greater")
    if args.start > 1:
        urls = urls[args.start - 1 :]
    if args.limit > 0:
        urls = urls[: args.limit]

    if not urls:
        print("No sitemap URLs found.")
        return 0

    if not args.write:
        print(f"dry run: {len(urls)} URL(s) would be submitted to Internet Archive Save Page Now")
        for url in urls:
            print(url)
        print("\nuse --write to submit")
        return 0

    print(f"Submitting {len(urls)} URL(s) to Internet Archive Save Page Now.")
    failures = 0
    for index, url in enumerate(urls, start=1):
        absolute_index = args.start + index - 1
        ok, message = archive_url_with_retries(url, args.timeout, args.retries, args.retry_delay)
        status = "ok" if ok else "failed"
        print(f"{absolute_index} {status}: {url} ({message})", flush=True)
        if not ok:
            failures += 1
        if index < len(urls) and args.delay > 0:
            time.sleep(args.delay)
    print(f"summary: {len(urls) - failures} submitted, {failures} failed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
