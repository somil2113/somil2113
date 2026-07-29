#!/usr/bin/env python3
"""
Generate animated ASCII SVG portrait (monochrome purple terminal theme).

Uses edge-connected flood-fill so only the true studio backdrop becomes
empty space — light face/skin stays as dense glyphs on the dark terminal.

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

import numpy as np
from PIL import Image, ImageFilter, ImageOps

RAMP = " .:-=+*#%@"
BG = "#0d1117"
FG = "#d4c4ff"
CURSOR = "#b48cff"

# Pixels this bright *and* connected to the image border count as backdrop
BG_LOOSE = 236


def prepare_image(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = gray.filter(ImageFilter.MedianFilter(size=3))
    return gray


def background_mask(gray: Image.Image) -> np.ndarray:
    """True where studio backdrop is (near-white, flood-filled from borders)."""
    arr = np.array(gray, dtype=np.uint8)
    h, w = arr.shape
    bg = np.zeros((h, w), dtype=bool)
    seen = np.zeros((h, w), dtype=bool)

    seeds: list[tuple[int, int]] = []
    for x in range(w):
        if arr[0, x] >= BG_LOOSE:
            seeds.append((0, x))
        if arr[h - 1, x] >= BG_LOOSE:
            seeds.append((h - 1, x))
    for y in range(h):
        if arr[y, 0] >= BG_LOOSE:
            seeds.append((y, 0))
        if arr[y, w - 1] >= BG_LOOSE:
            seeds.append((y, w - 1))

    stack = list(seeds)
    for y, x in stack:
        seen[y, x] = True
    while stack:
        y, x = stack.pop()
        if arr[y, x] < BG_LOOSE:
            continue
        bg[y, x] = True
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and arr[ny, nx] >= BG_LOOSE:
                seen[ny, nx] = True
                stack.append((ny, nx))
    return bg


def crop_to_subject(gray: Image.Image, bg: np.ndarray, pad: float = 0.05) -> tuple[Image.Image, np.ndarray]:
    ys, xs = np.where(~bg)
    if len(xs) == 0:
        return gray, bg
    h, w = bg.shape
    l, r = int(xs.min()), int(xs.max()) + 1
    t, b = int(ys.min()), int(ys.max()) + 1
    dx = int((r - l) * pad)
    dy = int((b - t) * pad)
    l, t = max(0, l - dx), max(0, t - dy)
    r, b = min(w, r + dx), min(h, b + dy)
    return gray.crop((l, t, r, b)), bg[t:b, l:r]


def subject_to_char(v: int, is_bg: bool, vmin: int, vmax: int) -> str:
    if is_bg:
        return " "
    span = max(1, vmax - vmin)
    t = (v - vmin) / span
    t = max(0.0, min(1.0, t))
    # Lighter face → denser glyphs (readable on dark SVG)
    t = 0.18 + 0.82 * (t ** 0.7)
    idx = int(t * (len(RAMP) - 1))
    return RAMP[idx]


def image_to_ascii(img: Image.Image, cols: int = 70) -> tuple[list[str], int, int]:
    gray = prepare_image(img)
    bg = background_mask(gray)
    gray, bg = crop_to_subject(gray, bg)

    w, h = gray.size
    char_aspect = 0.48
    rows = max(14, int((h / w) * cols * char_aspect))
    resized = gray.resize((cols, rows), Image.Resampling.LANCZOS)
    bg_img = Image.fromarray((bg.astype(np.uint8) * 255))
    bg_r = np.array(bg_img.resize((cols, rows), Image.Resampling.NEAREST)) > 127
    px = resized.load()

    subject_vals = [
        px[x, y]
        for y in range(rows)
        for x in range(cols)
        if not bg_r[y, x]
    ]
    if not subject_vals:
        raise ValueError("No subject pixels found — check source photo contrast")
    subject_vals.sort()
    vmin = subject_vals[int(len(subject_vals) * 0.05)]
    vmax = subject_vals[int(len(subject_vals) * 0.95)]
    if vmax <= vmin:
        vmin, vmax = min(subject_vals), max(subject_vals)

    lines: list[str] = []
    for y in range(rows):
        line = "".join(
            subject_to_char(px[x, y], bool(bg_r[y, x]), vmin, vmax)
            for x in range(cols)
        )
        lines.append(line.rstrip())

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines, cols, len(lines)


def make_svg(lines: list[str], cols: int, rows: int, output: str) -> None:
    static = os.getenv("STATIC", "0") == "1"
    font_size = 10
    line_h = 11.2
    pad = 18
    width = int(pad * 2 + cols * 6.4)
    height = int(pad * 2 + rows * line_h)
    reveal_w = width - pad * 2

    defs: list[str] = []
    groups: list[str] = []
    for i, raw_line in enumerate(lines):
        y = pad + (i + 1) * line_h
        line = html.escape(raw_line if raw_line else " ")
        if static:
            groups.append(f'<text x="{pad}" y="{y}" fill="{FG}">{line}</text>')
            continue

        # Default clip = full width so GitHub (often no SMIL) still shows the art
        clip_id = f"clip{i}"
        delay = i * 0.025
        defs.append(
            f'<clipPath id="{clip_id}">'
            f'<rect x="{pad}" y="{y - line_h + 2}" width="{reveal_w}" height="{line_h + 1}">'
            f'<animate attributeName="width" from="0" to="{reveal_w}" '
            f'begin="{delay:.3f}s" dur="0.40s" fill="freeze"/>'
            f"</rect></clipPath>"
        )
        groups.append(
            f'<text x="{pad}" y="{y}" fill="{FG}" clip-path="url(#{clip_id})">{line}</text>'
        )
        groups.append(
            f'<rect x="{pad}" y="{y - line_h + 2}" width="5" height="{line_h - 1}" '
            f'fill="{CURSOR}" opacity="0">'
            f'<animate attributeName="opacity" values="0;0.9;0.9;0" '
            f'keyTimes="0;0.05;0.85;1" begin="{delay:.3f}s" dur="0.40s" fill="freeze"/>'
            f'<animate attributeName="x" from="{pad}" to="{pad + reveal_w - 5}" '
            f'begin="{delay:.3f}s" dur="0.40s" fill="freeze"/>'
            f"</rect>"
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="ASCII portrait">
  <rect width="100%" height="100%" fill="{BG}" rx="12"/>
  <defs>
    {"".join(defs)}
  </defs>
  <g font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="{font_size}" xml:space="preserve">
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
    parser.add_argument("--cols", type=int, default=70)
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
