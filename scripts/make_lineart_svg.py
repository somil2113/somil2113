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
    Build an SVG path for the outer silhouette of the drawing.
    Returns (path_d, approximate_perimeter).
    """
    arr = np.array(gray, dtype=np.uint8)
    # Ink mask (black lines + filled interior via flood from outside)
    ink = (arr < 220).astype(np.uint8) * 255

    # Close gaps in the outline so we get one solid subject blob
    kernel = np.ones((5, 5), np.uint8)
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel, iterations=3)
    closed = cv2.dilate(closed, np.ones((3, 3), np.uint8), iterations=1)

    # Fill interior: flood-fill background from corners, invert
    h, w = closed.shape
    flood = closed.copy()
    ff_mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, ff_mask, (0, 0), 255)
    filled = cv2.bitwise_not(flood)
    subject = cv2.bitwise_or(closed, filled)

    contours, _ = cv2.findContours(subject, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return "", 0.0

    contour = max(contours, key=cv2.contourArea)
    peri = float(cv2.arcLength(contour.astype(np.float32), True))
    # Smooth enough to look organic, not jagged
    approx = cv2.approxPolyDP(contour, max(1.5, 0.0018 * peri), True)
    pts = approx.reshape(-1, 2).astype(np.float64)
    if len(pts) < 3:
        pts = contour.reshape(-1, 2).astype(np.float64)

    # Chaikin-ish densify then downsample for smoother SVG curves via many short segments
    # Convert to cubic Bezier via Catmull-Rom
    # Start at top-most point so animation begins at the hairline
    i0 = int(np.argmin(pts[:, 1]))
    pts = np.vstack([pts[i0:], pts[:i0], pts[i0:i0 + 1]])  # closed loop starting at top

    # Resample for even spacing
    pts = _resample_closed(pts[:-1], spacing=4.0)
    path_d = _catmull_closed_to_path(pts, ox, oy, scale_x, scale_y)
    # Perimeter in SVG units
    svg_peri = peri * ((scale_x + scale_y) / 2.0)
    return path_d, svg_peri


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
        dash_a, gap_a = 10, 8
        period_a = dash_a + gap_a
        comet_len = min(36.0, sil_peri * 0.08)
        gap_b = max(1.0, sil_peri - comet_len)

        style_block = f"""
  <style>
    .sil-stream {{
      fill: none;
      stroke: {FLOW};
      stroke-width: 1.7;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-dasharray: {dash_a} {gap_a};
      animation: silFlowA 2.8s linear infinite;
    }}
    .sil-comet {{
      fill: none;
      stroke: {FLOW_BRIGHT};
      stroke-width: 2.6;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-dasharray: {comet_len:.1f} {gap_b:.1f};
      filter: url(#glow);
      animation: silFlowB 4.2s linear infinite;
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
