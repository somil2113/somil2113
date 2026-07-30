#!/usr/bin/env python3
"""
Generate a red line-art portrait SVG with terminal chrome.

Expects a clean black-on-white line drawing (e.g. assets/lineart-source.png).
Recolors ink to red and embeds it in the terminal frame.

A flowing dashed stroke travels along the *subject silhouette* (the drawing's
own outline), not the rectangular photo frame.

Usage:
  python scripts/make_lineart_svg.py [--input assets/lineart-source.png] [--output portrait-lineart.svg]

Env:
  STATIC=1 -> no animation
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

BG = "#0d1117"
PANEL = "#1a1014"
BORDER = "#6b2222"
MUTED = "#c48a8a"
FLOW = "#ff6b6b"
FLOW_BRIGHT = "#ffd0d0"
INK = (255, 107, 107)

OUT_W = 370
CHROME_TOP = 44
PAD = 16
IMG_MAX_H = 420


def fit_portrait(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    w, h = img.size
    scale = min(max_w / w, max_h / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def lineart_to_red_rgba(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
    arr = np.asarray(gray, dtype=np.float32)
    ink = 1.0 - (arr / 255.0)
    ink = np.clip((ink - 0.04) / 0.96, 0.0, 1.0)
    ink = np.power(ink, 0.85)

    rgba = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    rgba[..., 0] = INK[0]
    rgba[..., 1] = INK[1]
    rgba[..., 2] = INK[2]
    rgba[..., 3] = (ink * 255.0).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


def encode_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def silhouette_path(gray: Image.Image, ox: float, oy: float, scale_x: float, scale_y: float) -> tuple[str, float]:
    """
    Build an SVG path from the true outer ink envelope of the drawing.

    Left side = leftmost ink each row (outer jacket/sleeve).
    Bottom = bottommost ink each column (jacket hem).
    Right/top = rightmost / topmost ink (face + hair).
    This avoids cutting through inner jacket folds.
    """
    arr = np.array(gray, dtype=np.uint8)
    h, w = arr.shape
    # Slight dilate so tiny gaps in the outer stroke don't punch holes in the envelope
    ink = (arr < 200).astype(np.uint8) * 255
    ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)

    pts = _ink_outer_envelope(ink, step=2)
    if len(pts) < 8:
        return "", 0.0

    # Start at top-most point
    i0 = int(np.argmin(pts[:, 1]))
    pts = np.vstack([pts[i0:], pts[:i0]])
    pts = _resample_closed(pts, spacing=3.0)
    # Light smooth without pulling away from outer rim
    pts = _chaikin_open_loop(pts, iterations=1)
    pts = _resample_closed(pts, spacing=3.2)

    peri = float(
        np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1).sum()
    )
    path_d = _catmull_closed_to_path(pts, ox, oy, scale_x, scale_y)
    svg_peri = peri * ((scale_x + scale_y) / 2.0)
    return path_d, svg_peri


def _ink_outer_envelope(ink: np.ndarray, step: int = 2) -> np.ndarray:
    """Closed polygon from leftmost/rightmost/topmost/bottommost ink extremes."""
    h, w = ink.shape
    ys, xs = np.where(ink > 0)
    if len(xs) == 0:
        return np.zeros((0, 2), dtype=np.float64)

    ymin, ymax = int(ys.min()), int(ys.max())
    xmin, xmax = int(xs.min()), int(xs.max())

    left: dict[int, int] = {}
    right: dict[int, int] = {}
    for y in range(ymin, ymax + 1):
        cols = np.where(ink[y] > 0)[0]
        if len(cols):
            left[y] = int(cols.min())
            right[y] = int(cols.max())

    top: dict[int, int] = {}
    bottom: dict[int, int] = {}
    for x in range(xmin, xmax + 1):
        rows = np.where(ink[:, x] > 0)[0]
        if len(rows):
            top[x] = int(rows.min())
            bottom[x] = int(rows.max())

    pts: list[tuple[float, float]] = []

    # 1) Down the outer left rim (jacket / sleeve)
    for y in range(ymin, ymax + 1, step):
        if y in left:
            pts.append((left[y], y))
    if ymax in left and (not pts or pts[-1][1] != ymax):
        pts.append((left[ymax], ymax))

    # 2) Across the bottom hem (left → right), always on bottommost ink
    x_bl = int(pts[-1][0]) if pts else xmin
    for x in range(x_bl, xmax + 1, step):
        if x in bottom:
            pts.append((x, bottom[x]))
    if xmax in bottom:
        pts.append((xmax, bottom[xmax]))

    # 3) Up the right profile (face / beard)
    for y in range(ymax, ymin - 1, -step):
        if y in right:
            pts.append((right[y], y))
    if ymin in right:
        pts.append((right[ymin], ymin))

    # 4) Across the top hairline (right → left)
    x_tr = int(pts[-1][0]) if pts else xmax
    for x in range(x_tr, xmin - 1, -step):
        if x in top:
            pts.append((x, top[x]))
    if xmin in top:
        pts.append((xmin, top[xmin]))

    return np.asarray(pts, dtype=np.float64)


def _chaikin_open_loop(pts: np.ndarray, iterations: int = 1) -> np.ndarray:
    """Chaikin on a closed ring (treat last→first as connected)."""
    pts = pts.reshape(-1, 2).astype(np.float64)
    for _ in range(iterations):
        n = len(pts)
        if n < 3:
            break
        new = []
        for i in range(n):
            p = pts[i]
            q = pts[(i + 1) % n]
            new.append(0.75 * p + 0.25 * q)
            new.append(0.25 * p + 0.75 * q)
        pts = np.asarray(new, dtype=np.float64)
    return pts


def _resample_closed(pts: np.ndarray, spacing: float) -> np.ndarray:
    pts = pts.reshape(-1, 2)
    closed = np.vstack([pts, pts[0]])
    diffs = np.diff(closed, axis=0)
    seglen = np.linalg.norm(diffs, axis=1)
    total = float(seglen.sum())
    if total < spacing:
        return pts
    n = max(16, int(round(total / spacing)))
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    samples = np.linspace(0.0, total, n, endpoint=False)
    out = []
    j = 0
    for s in samples:
        while j < len(seglen) - 1 and cum[j + 1] < s:
            j += 1
        t = 0.0 if seglen[j] == 0 else (s - cum[j]) / seglen[j]
        out.append(closed[j] * (1 - t) + closed[j + 1] * t)
    return np.asarray(out, dtype=np.float64)


def _catmull_closed_to_path(
    pts: np.ndarray, ox: float, oy: float, sx: float, sy: float
) -> str:
    n = len(pts)
    if n < 3:
        return ""

    def P(i: int) -> np.ndarray:
        return pts[i % n]

    x0, y0 = P(0)
    parts = [f"M {ox + x0 * sx:.2f} {oy + y0 * sy:.2f}"]
    for i in range(n):
        p0, p1, p2, p3 = P(i - 1), P(i), P(i + 1), P(i + 2)
        c1 = p1 + (p2 - p0) / 6.0
        c2 = p2 - (p3 - p1) / 6.0
        parts.append(
            f"C {ox + c1[0] * sx:.2f} {oy + c1[1] * sy:.2f} "
            f"{ox + c2[0] * sx:.2f} {oy + c2[1] * sy:.2f} "
            f"{ox + p2[0] * sx:.2f} {oy + p2[1] * sy:.2f}"
        )
    parts.append("Z")
    return " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate red line-art portrait SVG")
    parser.add_argument("--input", default="assets/lineart-source.png")
    parser.add_argument("--output", default="portrait-lineart.svg")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[make_lineart_svg] input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    static = os.getenv("STATIC", "0") == "1"

    try:
        raw = Image.open(in_path).convert("RGB")
    except Exception as exc:
        print(f"[make_lineart_svg] failed to open image: {exc}", file=sys.stderr)
        sys.exit(1)

    img_w = OUT_W - PAD * 2
    # Work from the fitted bitmap so silhouette coords match the embedded image
    fitted = fit_portrait(raw, img_w, IMG_MAX_H)
    rgba = lineart_to_red_rgba(fitted)
    iw, ih = rgba.size

    img_x = (OUT_W - iw) / 2
    img_y = CHROME_TOP + 8
    height = int(img_y + ih + PAD + 8)
    b64 = encode_png(rgba)

    gray = ImageOps.grayscale(fitted)
    # Image pixels map 1:1 into SVG at (img_x, img_y)
    sil_d, sil_peri = silhouette_path(gray, img_x, img_y, 1.0, 1.0)

    fade = ""
    flow_layer = ""
    style_block = ""

    if not static and sil_d and sil_peri > 0:
        fade = (
            '<animate attributeName="opacity" from="0" to="1" begin="0.08s" '
            'dur="0.5s" fill="freeze"/>'
        )
        # Stream of dashes + bright comet traveling the silhouette
        dash_a, gap_a = 12, 7
        period_a = dash_a + gap_a
        comet_len = min(48.0, sil_peri * 0.10)
        gap_b = max(1.0, sil_peri - comet_len)

        style_block = f"""
  <style>
    .sil-stream {{
      fill: none;
      stroke: {FLOW};
      stroke-width: 2.2;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-dasharray: {dash_a} {gap_a};
      animation: silFlowA 2.4s linear infinite;
    }}
    .sil-comet {{
      fill: none;
      stroke: {FLOW_BRIGHT};
      stroke-width: 3.2;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-dasharray: {comet_len:.1f} {gap_b:.1f};
      filter: url(#glow);
      animation: silFlowB 3.8s linear infinite;
    }}
    @keyframes silFlowA {{
      to {{ stroke-dashoffset: -{period_a}; }}
    }}
    @keyframes silFlowB {{
      to {{ stroke-dashoffset: -{sil_peri:.1f}; }}
    }}
  </style>"""

        flow_layer = f"""
  <path class="sil-stream" d="{sil_d}" opacity="0.8">
    <animate attributeName="stroke-dashoffset" from="0" to="-{period_a}"
             dur="2.8s" repeatCount="indefinite"/>
  </path>
  <path class="sil-comet" d="{sil_d}" opacity="0.95"
        stroke-dasharray="{comet_len:.1f} {gap_b:.1f}">
    <animate attributeName="stroke-dashoffset" from="0" to="-{sil_peri:.1f}"
             dur="4.2s" repeatCount="indefinite"/>
  </path>"""
    elif sil_d:
        flow_layer = f"""
  <path d="{sil_d}" fill="none" stroke="{FLOW}" stroke-width="1.5"
        stroke-linecap="round" stroke-linejoin="round" opacity="0.7"/>"""

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{OUT_W}" height="{height}" viewBox="0 0 {OUT_W} {height}" role="img" aria-label="Line art portrait">
{style_block}
  <defs>
    <clipPath id="photoClip">
      <rect x="{img_x}" y="{img_y}" width="{iw}" height="{ih}" rx="6"/>
    </clipPath>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="1.8" result="b"/>
      <feMerge>
        <feMergeNode in="b"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
  </defs>

  <rect width="100%" height="100%" fill="{BG}" rx="12"/>
  <rect x="8" y="8" width="{OUT_W - 16}" height="{height - 16}" rx="10" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
  <circle cx="26" cy="28" r="5" fill="#ff5f56"/>
  <circle cx="42" cy="28" r="5" fill="#ffbd2e"/>
  <circle cx="58" cy="28" r="5" fill="#27c93f"/>
  <text x="76" y="32" fill="{MUTED}" font-size="12" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">portrait · line art</text>

  <rect x="{img_x - 2}" y="{img_y - 2}" width="{iw + 4}" height="{ih + 4}" rx="6" fill="#0a0505" stroke="{BORDER}" stroke-opacity="0.45"/>
  <g clip-path="url(#photoClip)" opacity="1">{fade}
    <image x="{img_x}" y="{img_y}" width="{iw}" height="{ih}"
           href="data:image/png;base64,{b64}"
           xlink:href="data:image/png;base64,{b64}"
           preserveAspectRatio="xMidYMid meet"/>
  </g>
{flow_layer}
</svg>
"""

    Path(args.output).write_text(svg, encoding="utf-8")
    print(
        f"[make_lineart_svg] wrote {args.output} ({iw}x{ih}, "
        f"silhouette={'yes' if sil_d else 'no'}, peri={sil_peri:.0f})"
    )


if __name__ == "__main__":
    main()
