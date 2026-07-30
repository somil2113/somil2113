#!/usr/bin/env python3
"""
Render 53×7 contribution heatmap SVG from data/contributions.json (red palette).

GitHub-like layout: month labels, Mon/Wed/Fri day labels, Less→More legend.

Usage:
  python scripts/render_heatmap_svg.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

# Red scale matching GitHub intensity steps (0..4 + boosted top)
PALETTE = [
    "#161b22",  # level 0 empty
    "#3d1515",
    "#6b1e1e",
    "#a82a2a",
    "#e63946",
    "#ff8a80",  # level 5 (rare / boosted)
]

BG = "#0d1117"
TEXT = "#ffd6d6"
MUTED = "#c48a8a"

CELL = 11
GAP = 3
COLS = 53
ROWS = 7
LEFT = 36  # room for day labels
TOP = 44  # room for title + month labels
BOTTOM = 48
RIGHT = 16

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# GitHub week starts Sunday; show Mon/Wed/Fri (rows 1, 3, 5)
DAY_LABELS = {1: "Mon", 3: "Wed", 5: "Fri"}


def sunday_before(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def load() -> dict:
    path = Path("data/contributions.json")
    if not path.exists():
        raise FileNotFoundError(
            "data/contributions.json missing. Run fetch_contributions.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def build_grid(days_map: dict) -> tuple[list[dict], date]:
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
    return out, start


def month_labels(start: date) -> list[str]:
    """Place month abbreviations above the first week of each month."""
    labels: list[str] = []
    prev_month = None
    for col in range(COLS):
        week_start = start + timedelta(weeks=col)
        # Prefer a day mid-week for month detection stability
        mid = week_start + timedelta(days=3)
        m = mid.month
        if m != prev_month:
            labels.append(
                f'<text x="{LEFT + col * (CELL + GAP)}" y="{TOP - 8}" '
                f'font-size="11" fill="{MUTED}">{MONTHS[m - 1]}</text>'
            )
            prev_month = m
    return labels


def main() -> None:
    try:
        data = load()
    except Exception as exc:
        print(f"[render_heatmap_svg] {exc}", file=sys.stderr)
        sys.exit(1)

    stats = data.get("stats", {})
    days_map = {d["date"]: d for d in data.get("days", [])}
    cells, start = build_grid(days_map)

    grid_w = COLS * (CELL + GAP) - GAP
    grid_h = ROWS * (CELL + GAP) - GAP
    width = LEFT + grid_w + RIGHT
    height = TOP + grid_h + BOTTOM

    # Day labels (Mon / Wed / Fri)
    day_texts = []
    for row, label in DAY_LABELS.items():
        y = TOP + row * (CELL + GAP) + CELL - 1
        day_texts.append(
            f'<text x="2" y="{y}" font-size="10" fill="{MUTED}">{label}</text>'
        )

    rects: list[str] = []
    for i, day in enumerate(cells):
        col = i // ROWS
        row = i % ROWS
        x = LEFT + col * (CELL + GAP)
        y = TOP + row * (CELL + GAP)
        level = max(0, min(5, int(day.get("level", 0))))
        # GraphQL levels are 0..4 — stretch top quartile into brighter red
        if level == 4:
            level = 5
        fill = PALETTE[level]
        delay = (col + row) * 0.014
        count = day.get("count", 0)
        rects.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" '
            f'fill="{fill}" opacity="0">'
            f'<title>{day["date"]}: {count} contributions</title>'
            f'<animate attributeName="opacity" from="0" to="1" '
            f'begin="{delay:.3f}s" dur="0.20s" fill="freeze" />'
            f'<animate attributeName="y" from="{y - 4}" to="{y}" '
            f'begin="{delay:.3f}s" dur="0.20s" fill="freeze" />'
            f"</rect>"
        )

    # Legend: empty + 4 intensity steps (GitHub-style Less→More)
    legend_levels = [0, 1, 2, 3, 5]
    legend_w = len(legend_levels) * 14
    legend_x = width - RIGHT - legend_w - 40
    legend_y = TOP + grid_h + 18
    legend = [
        f'<rect x="{legend_x + i * 14}" y="{legend_y - 10}" width="11" height="11" '
        f'rx="2" fill="{PALETTE[lv]}" />'
        for i, lv in enumerate(legend_levels)
    ]

    total = stats.get("total", 0)
    current = stats.get("current_streak", 0)
    longest = stats.get("longest_streak", 0)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Contribution heatmap">
  <rect width="100%" height="100%" fill="{BG}" rx="10"/>
  <g font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">
    <text x="{LEFT}" y="18" font-size="13" fill="{TEXT}">{total:,} contributions in the last year</text>
    {"".join(month_labels(start))}
    {"".join(day_texts)}
    {"".join(rects)}
    <text x="{legend_x - 32}" y="{legend_y}" font-size="10" fill="{MUTED}">Less</text>
    {"".join(legend)}
    <text x="{legend_x + legend_w + 4}" y="{legend_y}" font-size="10" fill="{MUTED}">More</text>
    <text x="{LEFT}" y="{height - 8}" font-size="11" fill="{MUTED}">Current streak: {current} days · Longest streak: {longest} days</text>
  </g>
</svg>
"""

    Path("contrib-heatmap.svg").write_text(svg, encoding="utf-8")
    print("[render_heatmap_svg] wrote contrib-heatmap.svg")


if __name__ == "__main__":
    main()
