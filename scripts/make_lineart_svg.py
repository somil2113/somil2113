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
    Build an SVG path for the outer silhouette of the drawn figure.

    Dilates ink, keeps all meaningful stroke components (so outer jacket
    edges aren't dropped), then traces the external contour. The bottom-left
    path is further pushed out to the true leftmost ink so it doesn't cut
    inside the jacket folds.
    """
    arr = np.array(gray, dtype=np.uint8)
    h, w = arr.shape
    ink = (arr < 200).astype(np.uint8) * 255

    conn = cv2.dilate(
        ink,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
        iterations=2,
    )

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(conn)
    mask = np.zeros((h, w), dtype=np.uint8)
    min_area = max(40, int(0.0004 * w * h))
    for i in range(1, n_labels):
        x, y, bw, bh, area = stats[i]
        if area < min_area:
            continue
        # Reject only a full-frame flood component
        if area > 0.90 * w * h and bw > 0.95 * w and bh > 0.95 * h:
            continue
        mask[labels == i] = 255

    if not mask.any():
        return "", 0.0

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
        iterations=2,
    )

    # Pull silhouette out to the real outer ink on the left/bottom so the
    # path hugs the jacket rim instead of an internal fold.
    mask = _expand_to_outer_ink(mask, ink)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return "", 0.0

    contour = max(contours, key=cv2.contourArea)
    peri = float(cv2.arcLength(contour.astype(np.float32), True))
    pts = contour.reshape(-1, 2).astype(np.float64)

    bx, by, bw, bh = cv2.boundingRect(contour)
    if bw > 0.95 * w and bh > 0.95 * h and cv2.contourArea(contour) > 0.8 * w * h:
        return "", 0.0

    i0 = int(np.argmin(pts[:, 1]))
    pts = np.vstack([pts[i0:], pts[:i0]])
    pts = _resample_closed(pts, spacing=3.5)
    # Snap bottom-left samples to leftmost ink again after smoothing
    pts = _snap_bottom_left_to_ink(pts, ink)

    path_d = _catmull_closed_to_path(pts, ox, oy, scale_x, scale_y)
    svg_peri = peri * ((scale_x + scale_y) / 2.0)
    return path_d, svg_peri


def _expand_to_outer_ink(mask: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """Ensure leftmost/bottom ink strokes are inside the silhouette mask."""
    h, w = mask.shape
    out = mask.copy()
    # For each row, if ink exists left of the mask, fill out to that ink
    for y in range(h):
        ink_xs = np.where(ink[y] > 0)[0]
        mask_xs = np.where(out[y] > 0)[0]
        if len(ink_xs) == 0:
            continue
        left_ink = int(ink_xs.min())
        if len(mask_xs) == 0:
            continue
        left_mask = int(mask_xs.min())
        if left_ink < left_mask:
            # Bridge from outer ink into the figure (short horizontal fill)
            right = min(left_mask + 2, w - 1)
            out[y, left_ink : right + 1] = 255

    # Similar for bottom rows: extend mask down to lowest ink in each column
    # on the left half (jacket hem / sleeve bottom)
    for x in range(0, int(w * 0.55)):
        ink_ys = np.where(ink[:, x] > 0)[0]
        mask_ys = np.where(out[:, x] > 0)[0]
        if len(ink_ys) == 0 or len(mask_ys) == 0:
            continue
        bottom_ink = int(ink_ys.max())
        bottom_mask = int(mask_ys.max())
        if bottom_ink > bottom_mask:
            out[bottom_mask : bottom_ink + 1, x] = 255

    out = cv2.morphologyEx(
        out,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        iterations=2,
    )
    return out


def _snap_bottom_left_to_ink(pts: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """Push path points in the bottom-left region out to the outermost ink."""
    h, w = ink.shape
    pts = pts.copy()
    for i, (x, y) in enumerate(pts):
        yi = int(round(y))
        if yi < int(h * 0.62) or yi >= h:
            continue
        if x > w * 0.45:
            continue
        row = ink[yi]
        xs = np.where(row > 0)[0]
        if len(xs) == 0:
            continue
        left = float(xs.min())
        # Only snap outward (never pull inward)
        if left < x - 1:
            pts[i, 0] = left
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
