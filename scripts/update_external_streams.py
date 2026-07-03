#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data/external_stream_sources.toml"
OUTPUT = ROOT / "data/external_streams.toml"
DISPLAY_TZ = ZoneInfo("America/Sao_Paulo")
UPCOMING_WINDOW_SECONDS = 7 * 24 * 60 * 60
RICHNESS_KEYS = ("published_at", "scheduled_at", "live_status", "was_live")
ACTIVE_LIVE_STATUSES = {"is_live", "is_upcoming"}
FINISHED_LIVE_STATUSES = {"post_live", "was_live"}


def log(message: str) -> None:
    print(message, file=sys.stderr)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def letter_counts(value: str) -> tuple[int, int]:
    letters = [char for char in value if char.isalpha()]
    uppercase = [char for char in letters if char.isupper()]
    return len(letters), len(uppercase)


def looks_shouty(value: str) -> bool:
    letters, uppercase = letter_counts(value)
    return letters >= 12 and uppercase / letters >= 0.6


def normalize_hype_punctuation(value: str) -> str:
    value = re.sub(r"!{2,}", "!", value)
    value = re.sub(r"\?{2,}", "?", value)
    return value


def sentence_case(value: str) -> str:
    value = value.lower()
    chars = list(value)
    capitalize_next = True
    for index, char in enumerate(chars):
        if capitalize_next and char.isalpha():
            chars[index] = char.upper()
            capitalize_next = False
            continue
        if char in ".!?":
            capitalize_next = True
    return "".join(chars)


def restore_known_terms(value: str) -> str:
    replacements = (
        (r"\bchess\.com\b", "Chess.com"),
        (r"\bsesc\b", "SESC"),
        (r"\bfexpar\b", "FEXPAR"),
        (r"\birl\b", "IRL"),
        (r"\bgm\b", "GM"),
        (r"\belo\b", "Elo"),
        (r"\botb\b", "OTB"),
        (r"\btaí à toa tuesday\b", "Taí à Toa Tuesday"),
        (r"\bcopablunder\b", "CopaBlunder"),
        (r"\baliderança\b", "a liderança"),
        (r"\banti-sicilianas\b", "Anti-Sicilianas"),
        (r"\bnorway chess\b", "Norway Chess"),
    )
    for pattern, new in replacements:
        value = re.sub(pattern, new, value, flags=re.IGNORECASE)
    if value.startswith("ao vivo"):
        value = "Ao vivo" + value[len("ao vivo"):]
    return value


def normalize_shouty_words(value: str) -> str:
    def normalize_match(match):
        word = match.group(0)
        preserved = {"gm", "irl", "sesc", "fexpar", "otb"}
        if word.lower() in preserved:
            return word

        letters, uppercase = letter_counts(word)
        if letters < 2 or uppercase / letters < 0.8:
            return word
        return word.lower()

    return re.sub(r"\b[\wÀ-ÿ.-]+\b", normalize_match, value)


def capitalize_first_alpha(value: str) -> str:
    chars = list(value)
    for index, char in enumerate(chars):
        if char.isalpha():
            chars[index] = char.upper()
            break
    return "".join(chars)


def display_title(value: str) -> str:
    value = normalize_hype_punctuation(value)
    if looks_shouty(value):
        value = sentence_case(value)
    else:
        value = capitalize_first_alpha(normalize_shouty_words(value))
    return restore_known_terms(value)


def load_sources() -> tuple[int, list[dict[str, object]]]:
    with SOURCES.open("rb") as fh:
        data = tomllib.load(fh)

    limit = int(data.get("limit_per_source", 3))
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise SystemExit("data/external_stream_sources.toml must define [[sources]]")
    return limit, sources


def source_strings(source: dict[str, object], key: str) -> list[str]:
    value = source.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise SystemExit(f"source {source.get('name', source.get('url', ''))}: {key} must be a list")

    strings = []
    for entry in value:
        if not isinstance(entry, str):
            raise SystemExit(f"source {source.get('name', source.get('url', ''))}: {key} entries must be strings")
        entry = entry.strip().lower()
        if entry:
            strings.append(entry)
    return strings


def metadata_search_text(item: dict, fallback_title: str) -> str:
    values = [
        str(item.get("title") or fallback_title),
        str(item.get("description") or ""),
    ]
    for key in ("tags", "categories"):
        entries = item.get(key)
        if isinstance(entries, list):
            values.extend(str(entry) for entry in entries)

    return "\n".join(values).lower()


def matches_source_filters(source: dict[str, object], item: dict, fallback_title: str) -> bool:
    include_keywords = source_strings(source, "include_keywords")
    if not include_keywords:
        return True

    search_text = metadata_search_text(item, fallback_title)
    return any(keyword in search_text for keyword in include_keywords)


def load_existing_streams() -> dict[str, dict[str, str]]:
    if not OUTPUT.exists():
        return {}

    with OUTPUT.open("rb") as fh:
        data = tomllib.load(fh)

    existing: dict[str, dict[str, str]] = {}
    for table in ("upcoming_streams", "streams"):
        entries = data.get(table, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url") or "").strip()
            if url:
                existing[url] = {key: str(value) for key, value in entry.items()}
    return existing


def run_json_lines(cmd: list[str]) -> list[dict]:
    proc = subprocess.run(
        cmd,
        check=False,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd)}")

    items = []
    for line in proc.stdout.splitlines():
        if line.strip():
            items.append(json.loads(line))
    return items


def timestamp_from_upload_date(upload_date: str) -> int:
    if len(upload_date) != 8 or not upload_date.isdigit():
        return 0
    date = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    return int(date.timestamp())


def publication_timestamp(item: dict) -> int:
    for key in ("timestamp", "release_timestamp"):
        value = item.get(key)
        if isinstance(value, int) and value > 0:
            return value
    upload_date = str(item.get("upload_date") or "")
    return timestamp_from_upload_date(upload_date)


def scheduled_timestamp(item: dict) -> int:
    value = item.get("release_timestamp")
    if isinstance(value, int) and value > 0:
        return value
    return publication_timestamp(item)


def publication_fields(item: dict) -> dict[str, str | int]:
    timestamp = publication_timestamp(item)
    if not timestamp:
        return {
            "sort_timestamp": 0,
            "published_at": "",
            "published_date": "",
            "published_label": "",
        }

    published = datetime.fromtimestamp(timestamp, timezone.utc)
    display = published.astimezone(DISPLAY_TZ)
    return {
        "sort_timestamp": timestamp,
        "published_at": published.isoformat(timespec="seconds"),
        "published_date": display.date().isoformat(),
        "published_label": display.strftime("%d/%m/%Y"),
    }


def scheduled_fields(item: dict) -> dict[str, str | int]:
    timestamp = scheduled_timestamp(item)
    if not timestamp:
        return {
            "sort_timestamp": 0,
            "scheduled_at": "",
            "scheduled_date": "",
            "scheduled_label": "",
            "scheduled_time": "",
        }

    scheduled = datetime.fromtimestamp(timestamp, timezone.utc)
    display = scheduled.astimezone(DISPLAY_TZ)
    return {
        "sort_timestamp": timestamp,
        "scheduled_at": scheduled.isoformat(timespec="seconds"),
        "scheduled_date": display.date().isoformat(),
        "scheduled_label": display.strftime("%d/%m/%Y"),
        "scheduled_time": display.strftime("%H:%M"),
    }


def live_fields(item: dict) -> dict[str, str | int]:
    now = datetime.now(timezone.utc)
    display = now.astimezone(DISPLAY_TZ)
    return {
        "sort_timestamp": int(now.timestamp()),
        "scheduled_at": now.isoformat(timespec="seconds"),
        "scheduled_date": display.date().isoformat(),
        "scheduled_label": "ao vivo agora",
        "scheduled_time": "",
    }


def fetch_video_metadata(url: str) -> dict:
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--skip-download",
        "--ignore-no-formats",
        url,
    ]
    return run_json_lines(cmd)[0]


def stream_base(
    item: dict,
    source: dict[str, object],
    source_url: str,
    stream_url: str,
    title: str,
    duration: str,
) -> dict[str, str | int]:
    return {
        "title": str(item.get("title") or title).strip(),
        "display_title": display_title(str(item.get("title") or title).strip()),
        "creator": str(source.get("name") or item.get("channel") or "").strip(),
        "video_platform": str(source.get("video_platform") or "YouTube").strip(),
        "language": str(source.get("language") or "pt-BR").strip(),
        "url": str(item.get("webpage_url") or stream_url).strip(),
        "channel_url": source_url,
        "duration": duration,
        "live_status": str(item.get("live_status") or "").strip(),
        "was_live": "true" if item.get("was_live") else "false",
        "source_kind": "streams",
    }


def is_richer(existing: dict[str, str], candidate: dict[str, str | int]) -> bool:
    existing_status = str(existing.get("live_status", "")).strip()
    candidate_status = str(candidate.get("live_status", "")).strip()

    if candidate_status in ACTIVE_LIVE_STATUSES:
        return False
    if existing_status in ACTIVE_LIVE_STATUSES and candidate_status in FINISHED_LIVE_STATUSES:
        return False

    for key in RICHNESS_KEYS:
        existing_value = str(existing.get(key, "")).strip()
        candidate_value = str(candidate.get(key, "")).strip()
        if existing_value and not candidate_value:
            return True
        if key == "was_live" and existing_value == "true" and candidate_value != "true":
            return True
    return False


def preserve_existing_if_richer(
    stream: dict[str, str | int],
    existing_by_url: dict[str, dict[str, str]],
) -> dict[str, str | int]:
    existing = existing_by_url.get(str(stream.get("url") or ""))
    if not existing or not is_richer(existing, stream):
        return stream

    preserved = {**stream}
    for key, value in existing.items():
        if key != "sort_timestamp":
            preserved[key] = value

    timestamp_key = "scheduled_at" if preserved.get("scheduled_at") else "published_at"
    timestamp_value = str(preserved.get(timestamp_key) or "")
    if timestamp_value:
        try:
            preserved["sort_timestamp"] = int(datetime.fromisoformat(timestamp_value).timestamp())
        except ValueError:
            pass

    return preserved


def fetch_source(
    source: dict[str, object], limit: int, existing_by_url: dict[str, dict[str, str]]
) -> tuple[list[dict[str, str | int]], list[dict[str, str | int]]]:
    source_url = str(source["url"])
    source_name = str(source.get("name") or source_url)
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-end",
        str(limit),
        "--dump-json",
        source_url,
    ]
    log(f"source start: name={source_name!r} url={source_url!r} limit={limit}")
    items = run_json_lines(cmd)
    log(f"source playlist: name={source_name!r} items={len(items)}")

    upcoming_streams = []
    streams = []
    for index, item in enumerate(items, start=1):
        flat_item = item
        video_id = str(flat_item.get("id") or "").strip()
        stream_url = str(flat_item.get("url") or flat_item.get("webpage_url") or "").strip()
        if video_id and not stream_url.startswith("http"):
            stream_url = f"https://www.youtube.com/watch?v={video_id}"

        title = str(flat_item.get("title") or "").strip()
        log(
            "video flat: "
            f"source={source_name!r} index={index} id={video_id!r} "
            f"status={str(flat_item.get('live_status') or '').strip()!r} "
            f"duration={str(flat_item.get('duration_string') or '').strip()!r} "
            f"url={stream_url!r} title={title!r}"
        )
        if not title or not stream_url:
            log(f"video skip: source={source_name!r} index={index} reason='missing title or url'")
            continue

        used_fallback_metadata = False
        try:
            item = fetch_video_metadata(stream_url)
        except SystemExit:
            used_fallback_metadata = True
            item = flat_item
            log(f"video metadata: source={source_name!r} id={video_id!r} result='fallback-flat'")
        else:
            log(
                "video metadata: "
                f"source={source_name!r} id={video_id!r} result='fetched' "
                f"status={str(item.get('live_status') or '').strip()!r} "
                f"was_live={bool(item.get('was_live'))!r} "
                f"is_live={bool(item.get('is_live'))!r} "
                f"duration={str(item.get('duration_string') or '').strip()!r} "
                f"timestamp={item.get('timestamp')!r} release_timestamp={item.get('release_timestamp')!r}"
            )
        if not matches_source_filters(source, item, title):
            log(f"video skip: source={source_name!r} id={video_id!r} reason='source filter'")
            continue

        base = stream_base(
            item,
            source,
            source_url,
            stream_url,
            title,
            str(item.get("duration_string") or flat_item.get("duration_string") or "").strip(),
        )
        live_status = str(item.get("live_status") or "").strip()
        log(
            "video classify: "
            f"source={source_name!r} id={video_id!r} status={live_status!r} "
            f"was_live={base['was_live']!r} duration={base['duration']!r} "
            f"fallback={used_fallback_metadata!r}"
        )
        if live_status in ("is_upcoming", "is_live"):
            scheduled = scheduled_fields(item) if live_status == "is_upcoming" else live_fields(item)
            if not scheduled["sort_timestamp"]:
                log(f"video skip: source={source_name!r} id={video_id!r} reason='unscheduled upcoming/live'")
                continue
            candidate = {
                **base,
                "scheduled_at": str(scheduled["scheduled_at"]),
                "scheduled_date": str(scheduled["scheduled_date"]),
                "scheduled_label": str(scheduled["scheduled_label"]),
                "scheduled_time": str(scheduled["scheduled_time"]),
                "sort_timestamp": int(scheduled["sort_timestamp"]),
            }
            stream = preserve_existing_if_richer(candidate, existing_by_url)
            log(
                "video bucket: "
                f"source={source_name!r} id={video_id!r} bucket='upcoming' "
                f"status={str(stream.get('live_status') or '').strip()!r} "
                f"label={str(stream.get('scheduled_label') or '').strip()!r} "
                f"preserved_existing={stream != candidate!r}"
            )
            upcoming_streams.append(stream)
            continue

        published = publication_fields(item)
        if not published["sort_timestamp"]:
            log(f"video skip: source={source_name!r} id={video_id!r} reason='undated stream'")
            continue

        candidate = {
            **base,
            "published_at": str(published["published_at"]),
            "published_date": str(published["published_date"]),
            "published_label": str(published["published_label"]),
            "sort_timestamp": int(published["sort_timestamp"]),
        }
        stream = preserve_existing_if_richer(candidate, existing_by_url)
        log(
            "video bucket: "
            f"source={source_name!r} id={video_id!r} bucket='recent' "
            f"status={str(stream.get('live_status') or '').strip()!r} "
            f"label={str(stream.get('published_label') or '').strip()!r} "
            f"preserved_existing={stream != candidate!r}"
        )
        streams.append(stream)
    return upcoming_streams, streams


def write_streams_table(
    lines: list[str],
    table_name: str,
    streams: list[dict[str, str | int]],
    keys: tuple[str, ...],
) -> None:
    for stream in streams:
        lines.append(f"[[{table_name}]]")
        for key in keys:
            lines.append(f"{key} = {toml_string(str(stream.get(key, '')))}")
        lines.append("")


def write_output(
    upcoming_streams: list[dict[str, str | int]],
    streams: list[dict[str, str | int]],
) -> None:
    lines = [
        "# Generated by scripts/update_external_streams.py.",
        "# Edit data/external_stream_sources.toml to change tracked channels.",
        f"updated_at = {toml_string(datetime.now(timezone.utc).isoformat(timespec='seconds'))}",
        "",
    ]

    common_keys = (
        "title",
        "display_title",
        "creator",
        "video_platform",
        "language",
        "url",
        "channel_url",
    )
    write_streams_table(
        lines,
        "upcoming_streams",
        upcoming_streams,
        (
            *common_keys,
            "scheduled_at",
            "scheduled_date",
            "scheduled_label",
            "scheduled_time",
            "live_status",
            "was_live",
            "source_kind",
        ),
    )
    write_streams_table(
        lines,
        "streams",
        streams,
        (
            *common_keys,
            "published_at",
            "published_date",
            "published_label",
            "duration",
            "live_status",
            "was_live",
            "source_kind",
        ),
    )

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def filter_upcoming_streams(
    upcoming_streams: list[dict[str, str | int]],
    now_timestamp: int,
) -> list[dict[str, str | int]]:
    by_creator: dict[str, dict[str, str | int]] = {}
    latest_allowed = now_timestamp + UPCOMING_WINDOW_SECONDS

    for stream in upcoming_streams:
        scheduled = int(stream.get("sort_timestamp", 0))
        live_status = str(stream.get("live_status") or "")
        if live_status != "is_live" and scheduled < now_timestamp:
            continue
        if scheduled > latest_allowed:
            continue

        creator = str(stream.get("creator", ""))
        current = by_creator.get(creator)
        if current is None or scheduled < int(current.get("sort_timestamp", 0)):
            by_creator[creator] = stream

    return sorted(by_creator.values(), key=lambda stream: int(stream.get("sort_timestamp", 0)))


def promote_live_streams(
    streams: list[dict[str, str | int]],
) -> tuple[list[dict[str, str | int]], list[dict[str, str | int]]]:
    live_streams = []
    recent_streams = []

    for stream in streams:
        if str(stream.get("live_status") or "") != "is_live":
            recent_streams.append(stream)
            continue

        scheduled = live_fields({})
        live_streams.append(
            {
                **stream,
                "scheduled_at": str(scheduled["scheduled_at"]),
                "scheduled_date": str(scheduled["scheduled_date"]),
                "scheduled_label": str(scheduled["scheduled_label"]),
                "scheduled_time": str(scheduled["scheduled_time"]),
                "sort_timestamp": int(scheduled["sort_timestamp"]),
            }
        )

    return live_streams, recent_streams


def filter_latest_stream_per_creator(
    streams: list[dict[str, str | int]],
) -> list[dict[str, str | int]]:
    by_creator: dict[str, dict[str, str | int]] = {}

    for stream in streams:
        creator = str(stream.get("creator", ""))
        current = by_creator.get(creator)
        if current is None or int(stream.get("sort_timestamp", 0)) > int(current.get("sort_timestamp", 0)):
            by_creator[creator] = stream

    return sorted(by_creator.values(), key=lambda stream: int(stream.get("sort_timestamp", 0)), reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update curated external stream links from configured YouTube /streams pages."
    )
    parser.parse_args()

    limit, sources = load_sources()
    existing_by_url = load_existing_streams()
    upcoming_streams: list[dict[str, str | int]] = []
    streams: list[dict[str, str | int]] = []
    for source in sources:
        source_upcoming, source_streams = fetch_source(source, limit, existing_by_url)
        upcoming_streams.extend(source_upcoming)
        streams.extend(source_streams)
    live_streams, streams = promote_live_streams(streams)
    upcoming_streams.extend(live_streams)
    upcoming_streams = filter_upcoming_streams(
        upcoming_streams,
        int(datetime.now(timezone.utc).timestamp()),
    )
    streams = filter_latest_stream_per_creator(streams)
    write_output(upcoming_streams, streams)
    print(
        f"Wrote {len(upcoming_streams)} upcoming streams and {len(streams)} recent streams "
        f"to {OUTPUT.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
