#!/usr/bin/env python3
"""
Generate animated ASCII SVG portrait (monochrome purple terminal theme).

Usage:
  python scripts/make_ascii_svg.py [--input source-prepped.png] [--output avi-ascii.svg]

Env:
  STATIC=1  -> disable animation (final frame only)
"""

from __future__ import annotations

import argparse
import html
import os
import sys
from pathlib import Path

from PIL import Image

# Brightness ramp (leading space = darkest)
RAMP = " .`:-=+*cs#%@"
BG = "#0d1117"
FG = "#cbb6ff"  # light purple / gray-lilac
CURSOR = "#b48cff"


def brightness_to_char(v: int) -> str:
    idx = int((v / 255) * (len(RAMP) - 1))
    return RAMP[idx]


def image_to_ascii(img: Image.Image, cols: int = 100) -> tuple[list[str], int, int]:
    gray = img.convert("L")
    w, h = gray.size
    if w == 0 or h == 0:
        raise ValueError("Image has zero dimensions")

    # Terminal glyphs are taller than wide
    char_aspect = 0.50
    rows = max(10, int((h / w) * cols * char_aspect))
    resized = gray.resize((cols, rows))
    px = resized.load()

    lines: list[str] = []
    for y in range(rows):
        line = "".join(brightness_to_char(px[x, y]) for x in range(cols))
        lines.append(line.rstrip())
    return lines, cols, rows


def make_svg(lines: list[str], cols: int, rows: int, output: str) -> None:
    static = os.getenv("STATIC", "0") == "1"
    font_size = 10
    line_h = 11.5
    pad = 14
    width = int(pad * 2 + cols * 6.2)
    height = int(pad * 2 + rows * line_h)

    defs: list[str] = []
    groups: list[str] = []
    for i, raw_line in enumerate(lines):
        y = pad + (i + 1) * line_h
        line = html.escape(raw_line if raw_line else " ")
        if static:
            groups.append(f'<text x="{pad}" y="{y}" fill="{FG}">{line}</text>')
            continue

        # Left-to-right reveal via expanding clip + optional cursor block
        clip_id = f"clip{i}"
        delay = i * 0.035
        defs.append(
            f'<clipPath id="{clip_id}">'
            f'<rect x="{pad}" y="{y - line_h + 2}" width="0" height="{line_h + 1}">'
            f'<animate attributeName="width" from="0" to="{width - pad * 2}" '
            f'begin="{delay:.3f}s" dur="0.55s" fill="freeze"/>'
            f"</rect></clipPath>"
        )
        groups.append(
            f'<text x="{pad}" y="{y}" fill="{FG}" clip-path="url(#{clip_id})">{line}</text>'
        )
        groups.append(
            f'<rect x="{pad}" y="{y - line_h + 2}" width="6" height="{line_h}" '
            f'fill="{CURSOR}" opacity="0.85">'
            f'<animate attributeName="x" from="{pad}" to="{width - pad - 6}" '
            f'begin="{delay:.3f}s" dur="0.55s" fill="freeze"/>'
            f'<animate attributeName="opacity" from="0.85" to="0" '
            f'begin="{delay + 0.52:.3f}s" dur="0.08s" fill="freeze"/>'
            f"</rect>"
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="ASCII portrait">
  <rect width="100%" height="100%" fill="{BG}" rx="10"/>
  <defs>
    {"".join(defs)}
  </defs>
  <g font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="{font_size}">
    {"".join(groups)}
  </g>
</svg>
"""
    Path(output).write_text(svg, encoding="utf-8")
    print(f"[make_ascii_svg] wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate animated ASCII SVG portrait")
    parser.add_argument("--input", default="source-prepped.png")
    parser.add_argument("--output", default="avi-ascii.svg")
    parser.add_argument("--cols", type=int, default=100)
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(
            f"[make_ascii_svg] input not found: {in_path}. Run prep_photo.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        img = Image.open(in_path)
        lines, cols, rows = image_to_ascii(img, cols=args.cols)
        make_svg(lines, cols, rows, args.output)
    except Exception as exc:
        print(f"[make_ascii_svg] failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
