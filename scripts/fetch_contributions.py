#!/usr/bin/env python3
"""
Fetch GitHub contribution calendar and save parsed day data.

Prefers GraphQL (includes private contributions when authenticated as the user).
Falls back to the public HTML contributions page.

Usage:
  python scripts/fetch_contributions.py

Env:
  GITHUB_USERNAME   override default username (somil2113)
  CONTRIB_TOKEN     preferred PAT (read:user) for private contribs
  GH_TOKEN / GITHUB_TOKEN  alternate token names
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
HTML_URL = f"https://github.com/users/{USERNAME}/contributions"
GRAPHQL_URL = "https://api.github.com/graphql"

LEVEL_MAP = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

COUNT_RE = re.compile(
    r"^(?:No contributions|(\d+)\s+contributions?)\b",
    re.IGNORECASE,
)

GQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""


def auth_token() -> str | None:
    for key in ("CONTRIB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        val = os.getenv(key, "").strip()
        if val:
            return val
    return None


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


def fetch_via_graphql(token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": f"profile-svg-generator/1.0 (+https://github.com/{USERNAME})",
    }
    resp = requests.post(
        GRAPHQL_URL,
        headers=headers,
        json={"query": GQL_QUERY, "variables": {"login": USERNAME}},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])

    user = (payload.get("data") or {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {USERNAME}")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    days: list[dict] = []
    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            level_name = day.get("contributionLevel", "NONE")
            days.append(
                {
                    "date": day["date"],
                    "count": int(day.get("contributionCount", 0)),
                    "level": LEVEL_MAP.get(level_name, 0),
                }
            )
    days.sort(key=lambda x: x["date"])
    print(
        f"[fetch_contributions] GraphQL totalContributions="
        f"{calendar.get('totalContributions')}"
    )
    return days


def count_from_tooltip(text: str) -> int | None:
    if not text:
        return None
    m = COUNT_RE.match(text.strip())
    if not m:
        return None
    if m.group(1) is None:
        return 0
    return int(m.group(1))


def parse_days_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    tip_counts: dict[str, int] = {}
    for tip in soup.select("tool-tip[for]"):
        parsed = count_from_tooltip(tip.get_text(" ", strip=True))
        if parsed is not None:
            tip_counts[tip["for"]] = parsed

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
            count = level

        days.append({"date": date, "level": level, "count": count})

    days.sort(key=lambda x: x["date"])
    return days


def fetch_via_html() -> list[dict]:
    headers = {
        "User-Agent": f"profile-svg-generator/1.0 (+https://github.com/{USERNAME})",
        "Accept": "text/html",
    }
    print(f"[fetch_contributions] fetching public HTML {HTML_URL}")
    resp = requests.get(HTML_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    days = parse_days_html(resp.text)
    if not days:
        raise RuntimeError(
            "no contribution cells found — GitHub HTML may have changed."
        )
    return days


def main() -> None:
    token = auth_token()
    days: list[dict] = []
    source = "html"

    if token:
        print("[fetch_contributions] using GraphQL with auth token")
        try:
            days = fetch_via_graphql(token)
            source = "graphql"
        except Exception as exc:
            print(
                f"[fetch_contributions] GraphQL failed ({exc}); falling back to HTML",
                file=sys.stderr,
            )

    if not days:
        try:
            days = fetch_via_html()
            source = "html"
        except Exception as exc:
            print(f"[fetch_contributions] request failed: {exc}", file=sys.stderr)
            sys.exit(1)

    total = sum(d["count"] for d in days)
    current, longest = compute_streaks(days)
    best = max(days, key=lambda x: x["count"]) if days else {"date": None, "count": 0}

    payload = {
        "username": USERNAME,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
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
