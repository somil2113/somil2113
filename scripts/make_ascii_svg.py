#!/usr/bin/env python3
"""
Generate animated ASCII SVG portrait (monochrome purple terminal theme).

Maps dark subject pixels to dense glyphs and light/white background to spaces
so the portrait reads clearly on a dark terminal background.

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

from PIL import Image, ImageOps, ImageFilter

# Brightness ramp: space = empty bg, @ = densest subject ink
RAMP = " .:-=+*#%@"
BG = "#0d1117"
FG = "#cbb6ff"
CURSOR = "#b48cff"

# Original pixels brighter than this become empty space (white studio bg)
BG_THRESHOLD = 235
# Crush near-threshold noise into empty
INK_FLOOR = 12


def brightness_to_char(v: int) -> str:
    """Invert for dark terminals: white bg → space, dark subject → dense glyph."""
    if v >= BG_THRESHOLD:
        return " "
    # Invert so dark hair/jacket become heavy ink
    ink = 255 - v
    if ink < INK_FLOOR:
        return " "
    # Stretch remaining range for stronger subject contrast
    ink = min(255, int((ink - INK_FLOOR) * 255 / (255 - INK_FLOOR)))
    # Mild gamma so midtones (face) stay readable
    ink = int((ink / 255) ** 0.85 * 255)
    idx = int((ink / 255) * (len(RAMP) - 1))
    return RAMP[idx]


def prepare_image(img: Image.Image) -> Image.Image:
    """Grayscale, contrast boost, light blur to stabilize ASCII cells."""
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=2)
    # Soften single-pixel noise that becomes random glyphs
    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    return gray


def crop_to_content(gray: Image.Image, pad: float = 0.04) -> Image.Image:
    """Crop away large white margins so the subject fills the frame."""
    bw = gray.point(lambda p: 0 if p >= BG_THRESHOLD else 255)
    bbox = bw.getbbox()
    if not bbox:
        return gray
    w, h = gray.size
    l, t, r, b = bbox
    dx = int((r - l) * pad)
    dy = int((b - t) * pad)
    l = max(0, l - dx)
    t = max(0, t - dy)
    r = min(w, r + dx)
    b = min(h, b + dy)
    return gray.crop((l, t, r, b))


def image_to_ascii(img: Image.Image, cols: int = 90) -> tuple[list[str], int, int]:
    gray = prepare_image(img)
    gray = crop_to_content(gray)
    w, h = gray.size
    if w == 0 or h == 0:
        raise ValueError("Image has zero dimensions")

    # Glyphs are taller than wide
    char_aspect = 0.45
    rows = max(12, int((h / w) * cols * char_aspect))
    resized = gray.resize((cols, rows), Image.Resampling.LANCZOS)
    px = resized.load()

    lines: list[str] = []
    for y in range(rows):
        line = "".join(brightness_to_char(px[x, y]) for x in range(cols))
        lines.append(line.rstrip())

    # Drop fully empty leading/trailing rows
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return lines, cols, len(lines)


def make_svg(lines: list[str], cols: int, rows: int, output: str) -> None:
    static = os.getenv("STATIC", "0") == "1"
    font_size = 9
    line_h = 10.5
    pad = 16
    width = int(pad * 2 + cols * 5.6)
    height = int(pad * 2 + rows * line_h)

    defs: list[str] = []
    groups: list[str] = []
    for i, raw_line in enumerate(lines):
        y = pad + (i + 1) * line_h
        line = html.escape(raw_line if raw_line else " ")
        if static:
            groups.append(f'<text x="{pad}" y="{y}" fill="{FG}">{line}</text>')
            continue

        clip_id = f"clip{i}"
        delay = i * 0.028
        defs.append(
            f'<clipPath id="{clip_id}">'
            f'<rect x="{pad}" y="{y - line_h + 2}" width="0" height="{line_h + 1}">'
            f'<animate attributeName="width" from="0" to="{width - pad * 2}" '
            f'begin="{delay:.3f}s" dur="0.45s" fill="freeze"/>'
            f"</rect></clipPath>"
        )
        groups.append(
            f'<text x="{pad}" y="{y}" fill="{FG}" clip-path="url(#{clip_id})">{line}</text>'
        )
        groups.append(
            f'<rect x="{pad}" y="{y - line_h + 2}" width="5" height="{line_h - 1}" '
            f'fill="{CURSOR}" opacity="0.85">'
            f'<animate attributeName="x" from="{pad}" to="{width - pad - 5}" '
            f'begin="{delay:.3f}s" dur="0.45s" fill="freeze"/>'
            f'<animate attributeName="opacity" from="0.85" to="0" '
            f'begin="{delay + 0.42:.3f}s" dur="0.08s" fill="freeze"/>'
            f"</rect>"
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="ASCII portrait">
  <rect width="100%" height="100%" fill="{BG}" rx="10"/>
  <defs>
    {"".join(defs)}
  </defs>
  <g font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="{font_size}" letter-spacing="0.5">
    {"".join(groups)}
  </g>
</svg>
"""
    Path(output).write_text(svg, encoding="utf-8")
    print(f"[make_ascii_svg] wrote {output} ({cols}x{rows})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate animated ASCII SVG portrait")
    parser.add_argument("--input", default="source-prepped.png")
    parser.add_argument("--output", default="avi-ascii.svg")
    parser.add_argument("--cols", type=int, default=90)
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
