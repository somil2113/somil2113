#!/usr/bin/env python3
"""
Generate a red halftone (dot) portrait SVG with terminal chrome.

Darker image areas → larger dots. Studio-white backdrop stays empty.

Usage:
  python scripts/make_halftone_svg.py [--input assets/source-photo.jpg] [--output portrait-halftone.svg]

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
DOT = "#ff6b6b"
DOT_DIM = "#a82a2a"

OUT_W = 370
CHROME_TOP = 44
PAD = 16

# Sampling grid (more cols = finer dots / larger file)
COLS = 52
BG_LOOSE = 240  # near-white treated as empty


def prepare(img: Image.Image, cols: int) -> tuple[Image.Image, int, int]:
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.25)
    w, h = gray.size
    rows = max(14, int(round((h / w) * cols)))
    return gray.resize((cols, rows), Image.Resampling.LANCZOS), cols, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate red halftone portrait SVG")
    parser.add_argument("--input", default="assets/source-photo.jpg")
    parser.add_argument("--output", default="portrait-halftone.svg")
    parser.add_argument("--cols", type=int, default=COLS)
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[make_halftone_svg] input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    static = os.getenv("STATIC", "0") == "1"

    try:
        raw = Image.open(in_path).convert("RGB")
    except Exception as exc:
        print(f"[make_halftone_svg] failed to open image: {exc}", file=sys.stderr)
        sys.exit(1)

    small, cols, rows = prepare(raw, args.cols)
    px = small.load()

    grid_w = OUT_W - PAD * 2
    cell = grid_w / cols
    grid_h = cell * rows
    img_x = PAD
    img_y = CHROME_TOP + 6
    height = int(img_y + grid_h + PAD + 8)
    max_r = cell * 0.48

    dots: list[str] = []
    for y in range(rows):
        for x in range(cols):
            v = px[x, y]
            if v >= BG_LOOSE:
                continue  # empty backdrop

            # Invert: dark subject → large dots; light face → smaller dots
            ink = 1.0 - (v / 255.0)
            ink = max(0.0, min(1.0, ink ** 0.85))
            if ink < 0.06:
                continue

            r = max_r * (0.18 + 0.82 * ink)
            cx = img_x + (x + 0.5) * cell
            cy = img_y + (y + 0.5) * cell
            # Brighter (larger) dots use stronger red
            fill = DOT if ink > 0.45 else DOT_DIM
            delay = (x + y) * 0.0035

            if static:
                dots.append(
                    f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}"/>'
                )
            else:
                dots.append(
                    f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}" opacity="1">'
                    f'<animate attributeName="opacity" from="0" to="1" begin="{delay:.3f}s" '
                    f'dur="0.20s" fill="freeze"/>'
                    f'<animate attributeName="r" from="0" to="{r:.2f}" begin="{delay:.3f}s" '
                    f'dur="0.20s" fill="freeze"/>'
                    f"</circle>"
                )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{OUT_W}" height="{height}" viewBox="0 0 {OUT_W} {height}" role="img" aria-label="Halftone portrait">
  <rect width="100%" height="100%" fill="{BG}" rx="12"/>
  <rect x="8" y="8" width="{OUT_W - 16}" height="{height - 16}" rx="10" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
  <circle cx="26" cy="28" r="5" fill="#ff5f56"/>
  <circle cx="42" cy="28" r="5" fill="#ffbd2e"/>
  <circle cx="58" cy="28" r="5" fill="#27c93f"/>
  <text x="76" y="32" fill="{MUTED}" font-size="12" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">portrait · halftone</text>

  <rect x="{img_x - 2}" y="{img_y - 2}" width="{grid_w + 4}" height="{grid_h + 4}" rx="4" fill="#0a0505" stroke="{BORDER}" stroke-opacity="0.6"/>
  <g>
    {"".join(dots)}
  </g>
</svg>
"""

    # For GitHub: if SMIL ignored, animated circles still have final r/opacity as attributes
    Path(args.output).write_text(svg, encoding="utf-8")
    print(f"[make_halftone_svg] wrote {args.output} ({cols}x{rows}, {len(dots)} dots)")


if __name__ == "__main__":
    main()
