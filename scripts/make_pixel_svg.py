#!/usr/bin/env python3
"""
Generate a red-themed pixel-art portrait SVG with terminal chrome.

Usage:
  python scripts/make_pixel_svg.py [--input assets/source-photo.jpg] [--output portrait-pixel.svg]

Env:
  STATIC=1 -> no animation
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

BG = "#0d1117"
PANEL = "#1a1014"
BORDER = "#6b2222"
MUTED = "#c48a8a"

OUT_W = 370
CHROME_TOP = 44
PAD = 16

# Pixel grid size (columns). Rows follow aspect ratio.
COLS = 56

# Red ramp for luminance → pixel color (dark → bright)
RAMP = [
    (12, 4, 6),
    (42, 10, 12),
    (90, 18, 22),
    (140, 32, 36),
    (190, 48, 52),
    (230, 70, 70),
    (255, 120, 120),
    (255, 180, 180),
]


def rgb_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def tone(v: int) -> tuple[int, int, int]:
    t = (v / 255.0) ** 0.85
    idx = min(len(RAMP) - 1, int(t * (len(RAMP) - 1)))
    # Blend toward next stop for smoother steps
    frac = t * (len(RAMP) - 1) - idx
    a = RAMP[idx]
    b = RAMP[min(len(RAMP) - 1, idx + 1)]
    return (
        int(a[0] + (b[0] - a[0]) * frac),
        int(a[1] + (b[1] - a[1]) * frac),
        int(a[2] + (b[2] - a[2]) * frac),
    )


def to_pixels(img: Image.Image, cols: int) -> tuple[list[list[tuple[int, int, int]]], int, int]:
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.2)

    w, h = gray.size
    rows = max(12, int(round((h / w) * cols)))
    small = gray.resize((cols, rows), Image.Resampling.BOX)
    px = small.load()

    grid: list[list[tuple[int, int, int]]] = []
    for y in range(rows):
        grid.append([tone(px[x, y]) for x in range(cols)])
    return grid, cols, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate red pixel-art portrait SVG")
    parser.add_argument("--input", default="assets/source-photo.jpg")
    parser.add_argument("--output", default="portrait-pixel.svg")
    parser.add_argument("--cols", type=int, default=COLS)
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[make_pixel_svg] input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    static = os.getenv("STATIC", "0") == "1"

    try:
        raw = Image.open(in_path).convert("RGB")
    except Exception as exc:
        print(f"[make_pixel_svg] failed to open image: {exc}", file=sys.stderr)
        sys.exit(1)

    grid, cols, rows = to_pixels(raw, args.cols)

    grid_w = OUT_W - PAD * 2
    cell = grid_w / cols
    grid_h = cell * rows
    img_x = PAD
    img_y = CHROME_TOP + 6
    height = int(img_y + grid_h + PAD + 8)

    rects: list[str] = []
    for y, row in enumerate(grid):
        for x, rgb in enumerate(row):
            # Skip near-black empty margin pixels for a cleaner silhouette feel
            if rgb[0] < 22 and rgb[1] < 12 and rgb[2] < 14:
                continue
            px_ = img_x + x * cell
            py = img_y + y * cell
            delay = (x + y) * 0.004
            fill = rgb_hex(rgb)
            if static:
                rects.append(
                    f'<rect x="{px_:.2f}" y="{py:.2f}" width="{cell:.2f}" height="{cell:.2f}" fill="{fill}"/>'
                )
            else:
                # Default opacity=1 so GitHub still shows art if SMIL is ignored
                rects.append(
                    f'<rect x="{px_:.2f}" y="{py:.2f}" width="{cell:.2f}" height="{cell:.2f}" '
                    f'fill="{fill}" opacity="1">'
                    f'<animate attributeName="opacity" from="0" to="1" begin="{delay:.3f}s" '
                    f'dur="0.18s" fill="freeze"/>'
                    f"</rect>"
                )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{OUT_W}" height="{height}" viewBox="0 0 {OUT_W} {height}" role="img" aria-label="Pixel art portrait">
  <rect width="100%" height="100%" fill="{BG}" rx="12"/>
  <rect x="8" y="8" width="{OUT_W - 16}" height="{height - 16}" rx="10" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
  <circle cx="26" cy="28" r="5" fill="#ff5f56"/>
  <circle cx="42" cy="28" r="5" fill="#ffbd2e"/>
  <circle cx="58" cy="28" r="5" fill="#27c93f"/>
  <text x="76" y="32" fill="{MUTED}" font-size="12" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">portrait · pixel</text>

  <rect x="{img_x - 2}" y="{img_y - 2}" width="{grid_w + 4}" height="{grid_h + 4}" rx="4" fill="#0a0505" stroke="{BORDER}" stroke-opacity="0.6"/>
  <g shape-rendering="crispEdges">
    {"".join(rects)}
  </g>
</svg>
"""

    Path(args.output).write_text(svg, encoding="utf-8")
    print(f"[make_pixel_svg] wrote {args.output} ({cols}x{rows}, cell={cell:.2f}px)")


if __name__ == "__main__":
    main()
