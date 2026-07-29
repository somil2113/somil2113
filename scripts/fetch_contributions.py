#!/usr/bin/env python3
"""
Fetch public GitHub contribution calendar and save parsed day data.

Usage:
  python scripts/fetch_contributions.py

Env:
  GITHUB_USERNAME  override default username (somil2113)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

USERNAME = os.getenv("GITHUB_USERNAME", "somil2113")
URL = f"https://github.com/users/{USERNAME}/contributions"

COUNT_RE = re.compile(
    r"^(?:No contributions|(\d+)\s+contributions?)\b",
    re.IGNORECASE,
)


def compute_streaks(days: list[dict]) -> tuple[int, int]:
    """Return (current_streak, longest_streak) from chronological day list."""
    longest = 0
    run = 0
    for d in days:
        if d["count"] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    current = 0
    for i, d in enumerate(reversed(days)):
        if d["count"] > 0:
            current += 1
        else:
            # Allow today (last day) to be empty without breaking an ongoing streak
            if current == 0 and i == 0:
                continue
            break
    return current, longest


def count_from_tooltip(text: str) -> int | None:
    if not text:
        return None
    m = COUNT_RE.match(text.strip())
    if not m:
        return None
    if m.group(1) is None:
        return 0
    return int(m.group(1))


def parse_days(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    # Map day element id -> contribution count from <tool-tip for="...">
    tip_counts: dict[str, int] = {}
    for tip in soup.select("tool-tip[for]"):
        parsed = count_from_tooltip(tip.get_text(" ", strip=True))
        if parsed is not None:
            tip_counts[tip["for"]] = parsed

    # GitHub has used both <rect> (SVG calendar) and <td> (table calendar)
    cells = soup.select("td[data-date], rect[data-date]")
    days: list[dict] = []
    seen: set[str] = set()

    for cell in cells:
        date = cell.get("data-date")
        if not date or date in seen:
            continue
        seen.add(date)

        try:
            level = int(cell.get("data-level", "0") or 0)
        except ValueError:
            level = 0

        count: int | None = None
        raw_count = cell.get("data-count")
        if raw_count is not None and str(raw_count).strip() != "":
            try:
                count = int(raw_count)
            except ValueError:
                count = None

        if count is None:
            cell_id = cell.get("id")
            if cell_id and cell_id in tip_counts:
                count = tip_counts[cell_id]

        if count is None:
            # Last resort: approximate from intensity level (0..4 typically)
            count = level

        days.append({"date": date, "level": level, "count": count})

    days.sort(key=lambda x: x["date"])
    return days


def main() -> None:
    headers = {
        "User-Agent": f"profile-svg-generator/1.0 (+https://github.com/{USERNAME})",
        "Accept": "text/html",
    }
    print(f"[fetch_contributions] fetching {URL}")
    try:
        resp = requests.get(URL, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[fetch_contributions] request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    days = parse_days(resp.text)
    if not days:
        print(
            "[fetch_contributions] no contribution cells found — "
            "GitHub HTML may have changed.",
            file=sys.stderr,
        )
        sys.exit(1)

    total = sum(d["count"] for d in days)
    current, longest = compute_streaks(days)
    best = max(days, key=lambda x: x["count"])

    payload = {
        "username": USERNAME,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": days,
        "stats": {
            "total": total,
            "current_streak": current,
            "longest_streak": longest,
            "best_day": {"date": best["date"], "count": best["count"]},
        },
    }

    out = Path("data/contributions.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[fetch_contributions] wrote {out} ({len(days)} days, {total} total)")


if __name__ == "__main__":
    main()
