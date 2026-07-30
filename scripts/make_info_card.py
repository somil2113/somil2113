#!/usr/bin/env python3
"""
Generate neofetch-style info card SVG (red terminal theme).

Usage:
  python scripts/make_info_card.py

Env:
  STATIC=1 -> no animation
"""

from __future__ import annotations

import os
from pathlib import Path

# --- editable profile constants ---
NAME = "somil2113"
ROLE = "Software Developer"
NOW = "Building cool things with Python + Web"
PREV = "Learning systems, backend, automation"
STACK = "Python · JS/TS · GitHub Actions · Docker"
HIGHLIGHTS = "ASCII SVG profile · automation · clean UI"
# ----------------------------------

BG = "#0d1117"
PANEL = "#1a1014"
BORDER = "#6b2222"
KEY = "#ff6b6b"
VAL = "#ffd6d6"
MUTED = "#c48a8a"


def text_line(content: str, y: float, fill: str, delay: float, static: bool) -> str:
    escaped = (
        content.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    if static:
        return f'<text x="22" y="{y}" fill="{fill}">{escaped}</text>'
    return (
        f'<text x="22" y="{y}" fill="{fill}" opacity="0" transform="translate(0,6)">{escaped}'
        f'<animate attributeName="opacity" from="0" to="1" begin="{delay:.2f}s" dur="0.28s" fill="freeze" />'
        f'<animateTransform attributeName="transform" type="translate" from="0 6" to="0 0" '
        f'begin="{delay:.2f}s" dur="0.28s" fill="freeze" />'
        f"</text>"
    )


def main() -> None:
    static = os.getenv("STATIC", "0") == "1"
    width, height = 490, 330

    rows = [
        (f"{NAME}@github", KEY),
        (f"├─ role      : {ROLE}", VAL),
        (f"├─ now       : {NOW}", VAL),
        (f"├─ prev      : {PREV}", VAL),
        (f"├─ stack     : {STACK}", VAL),
        (f"└─ highlights: {HIGHLIGHTS}", VAL),
    ]

    y0 = 72
    dy = 36
    parts = [
        text_line(text, y0 + i * dy, color, i * 0.18, static)
        for i, (text, color) in enumerate(rows)
    ]

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Info card">
  <rect width="100%" height="100%" fill="{BG}" rx="12"/>
  <rect x="12" y="12" width="{width - 24}" height="{height - 24}" rx="10" fill="{PANEL}" stroke="{BORDER}"/>
  <circle cx="30" cy="32" r="5" fill="#ff5f56"/>
  <circle cx="46" cy="32" r="5" fill="#ffbd2e"/>
  <circle cx="62" cy="32" r="5" fill="#27c93f"/>
  <text x="80" y="36" fill="{MUTED}" font-size="13" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">neofetch</text>

  <g font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="14">
    {"".join(parts)}
  </g>
</svg>
"""

    Path("info-card.svg").write_text(svg, encoding="utf-8")
    print("[make_info_card] wrote info-card.svg")


if __name__ == "__main__":
    main()
