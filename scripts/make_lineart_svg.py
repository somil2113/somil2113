#!/usr/bin/env python3
"""
Generate a red line-art portrait SVG with terminal chrome.

Uses OpenCV Canny edges → simplified polylines for a clean profile sketch.

Usage:
  python scripts/make_lineart_svg.py [--input assets/source-photo.jpg] [--output portrait-lineart.svg]

Env:
  STATIC=1 -> no animation
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BG = "#0d1117"
PANEL = "#1a1014"
BORDER = "#6b2222"
MUTED = "#c48a8a"
STROKE = "#ff6b6b"
STROKE_SOFT = "#a82a2a"

OUT_W = 370
CHROME_TOP = 44
PAD = 16
PROCESS_W = 420  # working resolution for edge detect


def load_bgr(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    arr = np.array(img)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def extract_contours(bgr: np.ndarray) -> tuple[list[np.ndarray], int, int]:
    h0, w0 = bgr.shape[:2]
    scale = PROCESS_W / max(w0, 1)
    w = PROCESS_W
    h = max(1, int(round(h0 * scale)))
    resized = cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    # Slight bilateral keep edges while smoothing skin noise
    gray = cv2.bilateralFilter(gray, 7, 50, 50)

    edges = cv2.Canny(gray, 60, 150)
    # Dilate lightly so contours connect better
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

    kept: list[np.ndarray] = []
    min_area = (w * h) * 0.00015
    for c in contours:
        if cv2.contourArea(c) < min_area and cv2.arcLength(c, False) < w * 0.08:
            continue
        # Simplify
        eps = 0.0025 * cv2.arcLength(c, False)
        approx = cv2.approxPolyDP(c, max(eps, 1.2), False)
        if len(approx) < 2:
            continue
        kept.append(approx.reshape(-1, 2))

    # Prefer longer strokes first (drawn underneath soft, then strong top)
    kept.sort(key=lambda pts: len(pts), reverse=True)
    return kept[:450], w, h  # cap for file size


def points_to_path(pts: np.ndarray, sx: float, sy: float, ox: float, oy: float) -> str:
    if len(pts) == 0:
        return ""
    x0, y0 = pts[0]
    parts = [f"M {ox + x0 * sx:.2f} {oy + y0 * sy:.2f}"]
    for x, y in pts[1:]:
        parts.append(f"L {ox + x * sx:.2f} {oy + y * sy:.2f}")
    return " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate red line-art portrait SVG")
    parser.add_argument("--input", default="assets/source-photo.jpg")
    parser.add_argument("--output", default="portrait-lineart.svg")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[make_lineart_svg] input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    static = os.getenv("STATIC", "0") == "1"

    try:
        bgr = load_bgr(in_path)
    except Exception as exc:
        print(f"[make_lineart_svg] failed to open image: {exc}", file=sys.stderr)
        sys.exit(1)

    contours, src_w, src_h = extract_contours(bgr)
    if not contours:
        print("[make_lineart_svg] no edges found", file=sys.stderr)
        sys.exit(1)

    grid_w = OUT_W - PAD * 2
    scale = grid_w / src_w
    grid_h = src_h * scale
    img_x = PAD
    img_y = CHROME_TOP + 6
    height = int(img_y + grid_h + PAD + 8)

    paths: list[str] = []
    n = len(contours)
    for i, pts in enumerate(contours):
        d = points_to_path(pts, scale, scale, img_x, img_y)
        if not d:
            continue
        # Longer contours (drawn first) get slightly softer stroke
        soft = i < n * 0.35
        stroke = STROKE_SOFT if soft else STROKE
        width = 1.05 if soft else 1.35
        delay = i * 0.008
        if static:
            paths.append(
                f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )
        else:
            # Approximate path length for dash reveal; GitHub-safe: visible by default
            length = max(40, int(cv2.arcLength(pts.reshape(-1, 1, 2), False) * scale))
            paths.append(
                f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}" '
                f'stroke-linecap="round" stroke-linejoin="round" '
                f'stroke-dasharray="{length}" stroke-dashoffset="0" opacity="1">'
                f'<animate attributeName="stroke-dashoffset" from="{length}" to="0" '
                f'begin="{delay:.3f}s" dur="0.55s" fill="freeze"/>'
                f'<animate attributeName="opacity" from="0" to="1" '
                f'begin="{delay:.3f}s" dur="0.25s" fill="freeze"/>'
                f"</path>"
            )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{OUT_W}" height="{height}" viewBox="0 0 {OUT_W} {height}" role="img" aria-label="Line art portrait">
  <rect width="100%" height="100%" fill="{BG}" rx="12"/>
  <rect x="8" y="8" width="{OUT_W - 16}" height="{height - 16}" rx="10" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
  <circle cx="26" cy="28" r="5" fill="#ff5f56"/>
  <circle cx="42" cy="28" r="5" fill="#ffbd2e"/>
  <circle cx="58" cy="28" r="5" fill="#27c93f"/>
  <text x="76" y="32" fill="{MUTED}" font-size="12" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">portrait · line art</text>

  <rect x="{img_x - 2}" y="{img_y - 2}" width="{grid_w + 4}" height="{grid_h + 4}" rx="4" fill="#0a0505" stroke="{BORDER}" stroke-opacity="0.6"/>
  <g>
    {"".join(paths)}
  </g>
</svg>
"""

    Path(args.output).write_text(svg, encoding="utf-8")
    print(f"[make_lineart_svg] wrote {args.output} ({len(paths)} strokes)")


if __name__ == "__main__":
    main()
