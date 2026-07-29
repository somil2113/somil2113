#!/usr/bin/env python3
"""
Render 53×7 contribution heatmap SVG from data/contributions.json (purple palette).

Usage:
  python scripts/render_heatmap_svg.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

PALETTE = [
    "#1b1426",  # level 0
    "#2a1b3f",
    "#4b2b75",
    "#6d3fb0",
    "#8b5cf6",
    "#b794ff",  # level 5
]

BG = "#0d1117"
TEXT = "#d8ccff"
MUTED = "#9f8bc8"

CELL = 12
GAP = 4
COLS = 53
ROWS = 7
LEFT = 34
TOP = 30


def sunday_before(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def load() -> dict:
    path = Path("data/contributions.json")
    if not path.exists():
        raise FileNotFoundError(
            "data/contributions.json missing. Run fetch_contributions.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def build_grid(days_map: dict) -> list[dict]:
    """Build 53 weeks × 7 days (Sun→Sat) ending near today."""
    end = date.today()
    start = sunday_before(end) - timedelta(weeks=52)
    out: list[dict] = []
    d = start
    for _ in range(COLS * ROWS):
        iso = d.isoformat()
        item = days_map.get(iso, {"date": iso, "count": 0, "level": 0})
        out.append(item)
        d += timedelta(days=1)
    return out


def main() -> None:
    try:
        data = load()
    except Exception as exc:
        print(f"[render_heatmap_svg] {exc}", file=sys.stderr)
        sys.exit(1)

    stats = data.get("stats", {})
    days_map = {d["date"]: d for d in data.get("days", [])}
    cells = build_grid(days_map)

    width = LEFT + COLS * (CELL + GAP) + 20
    height = TOP + ROWS * (CELL + GAP) + 62

    rects: list[str] = []
    for i, day in enumerate(cells):
        col = i // ROWS
        row = i % ROWS
        x = LEFT + col * (CELL + GAP)
        y = TOP + row * (CELL + GAP)
        level = max(0, min(5, int(day.get("level", 0))))
        fill = PALETTE[level]
        delay = (col + row) * 0.014  # diagonal-ish stagger
        count = day.get("count", 0)
        rects.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3" '
            f'fill="{fill}" opacity="0">'
            f'<title>{day["date"]}: {count} contributions</title>'
            f'<animate attributeName="opacity" from="0" to="1" '
            f'begin="{delay:.3f}s" dur="0.20s" fill="freeze" />'
            f'<animate attributeName="y" from="{y - 5}" to="{y}" '
            f'begin="{delay:.3f}s" dur="0.20s" fill="freeze" />'
            f"</rect>"
        )

    legend_x = width - 145
    legend = [
        f'<rect x="{legend_x + i * 18}" y="10" width="12" height="12" rx="3" fill="{c}" />'
        for i, c in enumerate(PALETTE)
    ]

    total = stats.get("total", 0)
    current = stats.get("current_streak", 0)
    longest = stats.get("longest_streak", 0)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Contribution heatmap">
  <rect width="100%" height="100%" fill="{BG}" rx="10"/>
  <g font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="11" fill="{MUTED}">
    <text x="{legend_x - 34}" y="20">Less</text>
    {"".join(legend)}
    <text x="{legend_x + 6 * 18 + 4}" y="20">More</text>
  </g>
  {"".join(rects)}
  <g font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" fill="{TEXT}">
    <text x="{LEFT}" y="{height - 22}" font-size="12">{total:,} contributions in the last year</text>
    <text x="{LEFT}" y="{height - 7}" font-size="11">Current streak: {current} days · Longest streak: {longest} days</text>
  </g>
</svg>
"""

    Path("contrib-heatmap.svg").write_text(svg, encoding="utf-8")
    print("[render_heatmap_svg] wrote contrib-heatmap.svg")


if __name__ == "__main__":
    main()
