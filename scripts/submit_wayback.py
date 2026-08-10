#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITEMAP = ROOT / "public" / "sitemap.xml"
WAYBACK_SAVE_URL = "https://web.archive.org/save/"
WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
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


def latest_cdx_capture(url: str, timeout: int) -> tuple[str, str]:
    query = urllib.parse.urlencode(
        {
            "url": url,
            "output": "json",
            "fl": "original,timestamp,statuscode,mimetype",
            "filter": "statuscode:200",
            "limit": "-1",
        }
    )
    request = urllib.request.Request(
        f"{WAYBACK_CDX_URL}?{query}",
        headers={
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
            "User-Agent": "xadrez-live-wayback-submit/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as error:
        if error.code == 429:
            return "rate_limited", f"CDX HTTP 429 {error.reason}"
        detail = error.read().decode("utf-8", errors="replace").strip()
        return "failed", f"CDX HTTP {error.code} {error.reason}: {detail[:240]}"
    except urllib.error.URLError as error:
        return "pending", f"CDX unavailable: {error.reason}"

    if not text or text == "[]":
        return "pending", "CDX has no 200 capture yet"

    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return "pending", f"CDX returned non-JSON response: {text[:120]}"

    if not isinstance(rows, list) or len(rows) < 2 or not isinstance(rows[-1], list):
        return "pending", "CDX has no capture rows yet"

    headers = rows[0]
    latest = rows[-1]
    if not isinstance(headers, list):
        return "pending", "CDX returned malformed header"
    row = {str(key): str(value) for key, value in zip(headers, latest)}
    timestamp = row.get("timestamp", "")
    statuscode = row.get("statuscode", "")
    mimetype = row.get("mimetype", "")
    if timestamp and statuscode == "200":
        return "captured", f"CDX {timestamp} HTTP {statuscode} {mimetype}".strip()
    return "pending", f"CDX latest row is not a 200 capture: {row}"


def verify_cdx_capture(url: str, timeout: int, wait_seconds: int, interval: float) -> tuple[str, str]:
    deadline = time.monotonic() + max(0, wait_seconds)
    messages = []
    while True:
        status, message = latest_cdx_capture(url, timeout)
        if status in {"captured", "rate_limited", "failed"}:
            return status, message
        messages.append(message)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "pending", " | ".join(unique(messages[-3:]))
        time.sleep(min(interval, remaining))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit sitemap URLs to Internet Archive Save Page Now.")
    parser.add_argument("--write", action="store_true", help="Submit URLs. Without this flag, only list what would be submitted.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N URLs.")
    parser.add_argument("--start", type=int, default=1, help="1-based index to start from, useful for resuming after a failed run.")
    parser.add_argument("--delay", type=float, default=10.0, help="Seconds to wait between submissions.")
    parser.add_argument("--retries", type=int, default=2, help="Retries for temporary HTTP/network failures.")
    parser.add_argument("--retry-delay", type=float, default=30.0, help="Base seconds to wait before retrying temporary failures.")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout per URL.")
    parser.add_argument("--no-verify", action="store_true", help="Do not verify submitted URLs in the Wayback CDX index.")
    parser.add_argument("--verify-wait", type=int, default=45, help="Seconds to wait for each submitted URL to appear in CDX.")
    parser.add_argument("--verify-interval", type=float, default=5.0, help="Seconds between CDX verification attempts.")
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

    verify_suffix = "" if args.no_verify else " and verifying CDX captures"
    print(f"Submitting {len(urls)} URL(s) to Internet Archive Save Page Now{verify_suffix}.")
    counts = {"captured": 0, "submitted": 0, "pending": 0, "rate_limited": 0, "failed": 0}
    for index, url in enumerate(urls, start=1):
        absolute_index = args.start + index - 1
        ok, message = archive_url_with_retries(url, args.timeout, args.retries, args.retry_delay)
        if not ok:
            counts["failed"] += 1
            print(f"{absolute_index} failed: {url} ({message})", flush=True)
        elif args.no_verify:
            counts["submitted"] += 1
            print(f"{absolute_index} submitted: {url} ({message})", flush=True)
        else:
            verify_status, verify_message = verify_cdx_capture(
                url,
                args.timeout,
                args.verify_wait,
                args.verify_interval,
            )
            counts[verify_status] += 1
            print(f"{absolute_index} {verify_status}: {url} ({message}; {verify_message})", flush=True)
        if index < len(urls) and args.delay > 0:
            time.sleep(args.delay)
    if args.no_verify:
        print(f"summary: {counts['submitted']} submitted, {counts['failed']} failed")
        return 0 if counts["failed"] == 0 else 1
    print(
        "summary: "
        f"{counts['captured']} captured, "
        f"{counts['pending']} pending, "
        f"{counts['rate_limited']} rate_limited, "
        f"{counts['failed']} failed"
    )
    return 0 if counts["pending"] == counts["rate_limited"] == counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
