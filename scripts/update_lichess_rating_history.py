#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content" / "fcz"
OUTPUT = ROOT / "data" / "fcz" / "lichess_rating_history.toml"
DEFAULT_USERNAME = "fcz"
SERIES = {
    "Rapid": {
        "key": "rapid",
        "label": "Rapid",
        "color": "#d8a657",
        "url": "https://lichess.org/@/fcz/perf/rapid",
    },
    "Puzzles": {
        "key": "puzzles",
        "label": "Puzzles",
        "color": "#80b8ff",
        "url": "https://lichess.org/@/fcz/perf/puzzle",
    },
}
CHART_WIDTH = 720
CHART_HEIGHT = 260
PLOT_LEFT = 46
PLOT_TOP = 20
PLOT_RIGHT = 694
PLOT_BOTTOM = 212


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def format_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def int_value(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def fetch_rating_history(username: str, timeout: int) -> list[dict[str, Any]]:
    url = f"https://lichess.org/api/user/{username}/rating-history"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "xadrez.live static site stats (https://xadrez.live)",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def point_date(point: list[int]) -> str:
    year, month_zero_based, day, _rating = point
    return f"{year:04d}-{month_zero_based + 1:02d}-{day:02d}"


def point_timestamp(point: list[int]) -> float:
    year, month_zero_based, day, _rating = point
    return datetime(year, month_zero_based + 1, day, tzinfo=timezone.utc).timestamp()


def front_matter(path: Path) -> dict[str, Any]:
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


def load_session_markers(field: str) -> list[dict[str, Any]]:
    markers = []
    for path in sorted(CONTENT_DIR.glob("[0-9][0-9][0-9][0-9].md")):
        data = front_matter(path)
        if data.get("draft") is True:
            continue
        extra = data.get("extra")
        if not isinstance(extra, dict):
            continue
        rating = int_value(extra.get(field))
        if rating is None:
            continue
        status_tone = str(extra.get("status_tone") or "").strip().casefold()
        if status_tone in {"scheduled", "live"}:
            continue
        session_date = data.get("date")
        if not session_date:
            continue
        number = str(extra.get("session_number") or path.stem)
        title = str(data.get("title") or f"Sessão #{number}")
        summary_title = str(extra.get("summary_title") or "").strip()
        markers.append(
            {
                "session_number": number,
                "title": title,
                "summary_title": summary_title,
                "date": str(session_date),
                "rating": rating,
                "url": f"/fcz/{number}/",
            }
        )
    return markers


def scaled_points(points: list[list[int]]) -> dict[str, Any]:
    ratings = [int(point[3]) for point in points]
    min_rating = min(ratings)
    max_rating = max(ratings)
    spread = max(max_rating - min_rating, 1)
    padding = max(10, round(spread * 0.08))
    y_min = min_rating - padding
    y_max = max_rating + padding
    y_spread = max(y_max - y_min, 1)
    x_span = PLOT_RIGHT - PLOT_LEFT
    y_span = PLOT_BOTTOM - PLOT_TOP
    first_timestamp = point_timestamp(points[0])
    last_timestamp = point_timestamp(points[-1])
    timestamp_span = max(last_timestamp - first_timestamp, 1)

    svg_points = []
    scaled = []
    for point in points:
        rating = int(point[3])
        timestamp = point_timestamp(point)
        x = PLOT_LEFT + ((timestamp - first_timestamp) / timestamp_span) * x_span
        y = PLOT_BOTTOM - ((rating - y_min) / y_spread) * y_span
        svg_points.append(f"{x:.1f},{y:.1f}")
        scaled.append(
            {
                "date": point_date(point),
                "timestamp": timestamp,
                "rating": rating,
                "x": x,
                "y": y,
            }
        )

    latest = scaled[-1]
    first = scaled[0]
    return {
        "svg_points": " ".join(svg_points),
        "scaled": scaled,
        "first": first,
        "latest": latest,
        "min_rating": min_rating,
        "max_rating": max_rating,
        "y_min": y_min,
        "y_max": y_max,
        "x_axis_y": PLOT_BOTTOM,
        "plot_left": PLOT_LEFT,
        "plot_right": PLOT_RIGHT,
        "plot_top": PLOT_TOP,
        "plot_bottom": PLOT_BOTTOM,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
    }


def scale_session_markers(markers: list[dict[str, Any]], chart: dict[str, Any]) -> list[dict[str, Any]]:
    scaled_points_by_date = {point["date"]: point for point in chart["scaled"]}
    result = []

    for marker in markers:
        point = scaled_points_by_date.get(marker["date"])
        if not point:
            continue
        line_rating = point["rating"]
        result.append(
            {
                **marker,
                "line_rating": line_rating,
                "x": point["x"],
                "y": point["y"],
            }
        )

    return result


def render(username: str, payload: list[dict[str, Any]]) -> str:
    by_name = {
        str(item.get("name") or ""): item.get("points")
        for item in payload
        if isinstance(item, dict)
    }
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    lines = [
        "# Generated by scripts/update_lichess_rating_history.py; do not edit manually.",
        "",
        f"username = {toml_string(username)}",
        f"updated_at = {toml_string(now)}",
        f"source_url = {toml_string(f'https://lichess.org/api/user/{username}/rating-history')}",
        "",
    ]

    for lichess_name, meta in SERIES.items():
        points = by_name.get(lichess_name)
        if not isinstance(points, list) or not points:
            continue

        cleaned = [
            point
            for point in points
            if isinstance(point, list)
            and len(point) == 4
            and all(isinstance(value, int) for value in point)
        ]
        if not cleaned:
            continue

        chart = scaled_points(cleaned)
        session_markers = []
        if meta["key"] == "rapid":
            session_markers = scale_session_markers(load_session_markers("rapid"), chart)
        first_rating = chart["first"]["rating"]
        latest_rating = chart["latest"]["rating"]
        delta = latest_rating - first_rating
        lines.extend(
            [
                "[[series]]",
                f"key = {toml_string(meta['key'])}",
                f"label = {toml_string(meta['label'])}",
                f"color = {toml_string(meta['color'])}",
                f"url = {toml_string(meta['url'])}",
                f"point_count = {len(cleaned)}",
                f"first_date = {toml_string(chart['first']['date'])}",
                f"first_rating = {first_rating}",
                f"first_rating_label = {toml_string(format_int(first_rating))}",
                f"latest_date = {toml_string(chart['latest']['date'])}",
                f"latest_rating = {latest_rating}",
                f"latest_rating_label = {toml_string(format_int(latest_rating))}",
                f"delta = {delta}",
                f"delta_label = {toml_string(('+' if delta > 0 else '') + format_int(delta))}",
                f"min_rating = {chart['min_rating']}",
                f"max_rating = {chart['max_rating']}",
                f"y_min = {chart['y_min']}",
                f"y_max = {chart['y_max']}",
                f"svg_points = {toml_string(chart['svg_points'])}",
                f"latest_x = {chart['latest']['x']:.1f}",
                f"latest_y = {chart['latest']['y']:.1f}",
                f"plot_left = {chart['plot_left']}",
                f"plot_right = {chart['plot_right']}",
                f"plot_top = {chart['plot_top']}",
                f"plot_bottom = {chart['plot_bottom']}",
                f"y_max_label_y = {chart['plot_top'] + 4}",
                f"y_min_label_y = {chart['plot_bottom'] + 4}",
                f"x_label_y = {chart['height'] - 14}",
                f"chart_width = {chart['width']}",
                f"chart_height = {chart['height']}",
                "",
            ]
        )

        for point in chart["scaled"]:
            lines.extend(
                [
                    "[[series.points]]",
                    f"date = {toml_string(point['date'])}",
                    f"timestamp = {int(point['timestamp'])}",
                    f"rating = {point['rating']}",
                    f"rating_label = {toml_string(format_int(point['rating']))}",
                    "",
                ]
            )

        for marker in session_markers:
            rating_note = f"rapid Lichess {marker['line_rating']}"
            if marker["rating"] != marker["line_rating"]:
                rating_note = f"{rating_note}; sessão {marker['rating']}"
            tooltip = f"{rating_note} - {marker['title']}"
            if marker["summary_title"]:
                tooltip = f"{tooltip}: {marker['summary_title']}"
            tooltip = f"{tooltip} ({marker['date']})"
            lines.extend(
                [
                    "[[series.sessions]]",
                    f"session_number = {toml_string(marker['session_number'])}",
                    f"title = {toml_string(marker['title'])}",
                    f"summary_title = {toml_string(marker['summary_title'])}",
                    f"date = {toml_string(marker['date'])}",
                    f"rating = {marker['rating']}",
                    f"rating_label = {toml_string(format_int(marker['rating']))}",
                    f"line_rating = {marker['line_rating']}",
                    f"line_rating_label = {toml_string(format_int(marker['line_rating']))}",
                    f"url = {toml_string(marker['url'])}",
                    f"x = {marker['x']:.1f}",
                    f"y = {marker['y']:.1f}",
                    f"tooltip = {toml_string(tooltip)}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    try:
        payload = fetch_rating_history(args.username, args.timeout)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        if OUTPUT.exists():
            print(f"Keeping existing {OUTPUT.relative_to(ROOT)}; Lichess fetch failed: {error}", file=sys.stderr)
            return 0
        print(f"Lichess rating history unavailable and no cache exists: {error}", file=sys.stderr)
        return 1

    OUTPUT.write_text(render(args.username, payload), encoding="utf-8")
    print(f"Updated {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
