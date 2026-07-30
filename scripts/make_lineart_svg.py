#!/usr/bin/env python3
"""
Generate a red line-art portrait SVG with terminal chrome.

Builds a clean silhouette from the subject mask, then adds smoothed
internal Canny strokes (no jagged approxPolyDP shards).

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
STROKE_SOFT = "#c44545"

OUT_W = 370
CHROME_TOP = 44
PAD = 16
PROCESS_W = 560


def load_bgr(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def resample_open(pts: np.ndarray, spacing: float = 2.5) -> np.ndarray:
    """Resample an open polyline to roughly uniform spacing."""
    pts = pts.astype(np.float64).reshape(-1, 2)
    if len(pts) < 2:
        return pts
    diffs = np.diff(pts, axis=0)
    seglen = np.linalg.norm(diffs, axis=1)
    total = float(seglen.sum())
    if total < spacing:
        return pts
    n = max(2, int(round(total / spacing)))
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    samples = np.linspace(0.0, total, n)
    out = []
    j = 0
    for s in samples:
        while j < len(seglen) - 1 and cum[j + 1] < s:
            j += 1
        t = 0.0 if seglen[j] == 0 else (s - cum[j]) / seglen[j]
        out.append(pts[j] * (1 - t) + pts[j + 1] * t)
    return np.asarray(out, dtype=np.float64)


def chaikin(pts: np.ndarray, iterations: int = 2) -> np.ndarray:
    """Chaikin corner-cutting for smoother open polylines."""
    pts = pts.astype(np.float64).reshape(-1, 2)
    for _ in range(iterations):
        if len(pts) < 3:
            break
        new = [pts[0]]
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            new.append(0.75 * p + 0.25 * q)
            new.append(0.25 * p + 0.75 * q)
        new.append(pts[-1])
        pts = np.asarray(new, dtype=np.float64)
    return pts


def catmull_rom_to_bezier_path(
    pts: np.ndarray, sx: float, sy: float, ox: float, oy: float
) -> str:
    """Convert open polyline to smooth cubic SVG path via Catmull-Rom."""
    pts = pts.reshape(-1, 2)
    if len(pts) == 0:
        return ""
    if len(pts) == 1:
        x, y = pts[0]
        return f"M {ox + x * sx:.2f} {oy + y * sy:.2f}"
    if len(pts) == 2:
        (x0, y0), (x1, y1) = pts
        return (
            f"M {ox + x0 * sx:.2f} {oy + y0 * sy:.2f} "
            f"L {ox + x1 * sx:.2f} {oy + y1 * sy:.2f}"
        )

    # Pad endpoints for Catmull-Rom
    ext = np.vstack([pts[0], pts, pts[-1]])
    x0, y0 = pts[0]
    parts = [f"M {ox + x0 * sx:.2f} {oy + y0 * sy:.2f}"]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        c1 = p1 + (p2 - p0) / 6.0
        c2 = p2 - (p3 - p1) / 6.0
        parts.append(
            f"C {ox + c1[0] * sx:.2f} {oy + c1[1] * sy:.2f} "
            f"{ox + c2[0] * sx:.2f} {oy + c2[1] * sy:.2f} "
            f"{ox + p2[0] * sx:.2f} {oy + p2[1] * sy:.2f}"
        )
    return " ".join(parts)


def largest_external_contour(mask: np.ndarray) -> np.ndarray | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 500:
        return None
    return c.reshape(-1, 2)


def split_closed_to_open(pts: np.ndarray, pieces: int = 1) -> list[np.ndarray]:
    """Keep silhouette as one open-ish loop starting at topmost point."""
    pts = pts.reshape(-1, 2)
    if len(pts) < 8:
        return [pts]
    # Start at top-most point for a natural hairline begin
    i0 = int(np.argmin(pts[:, 1]))
    ordered = np.vstack([pts[i0:], pts[: i0 + 1]])  # close back to start
    return [ordered]


def extract_strokes(bgr: np.ndarray) -> tuple[list[tuple[np.ndarray, str]], int, int]:
    h0, w0 = bgr.shape[:2]
    w = PROCESS_W
    h = max(1, int(round(h0 * (w / max(w0, 1)))))
    resized = cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 60, 60)

    # Subject mask from near-white studio backdrop
    _, mask = cv2.threshold(gray, 242, 255, cv2.THRESH_BINARY_INV)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

    strokes: list[tuple[np.ndarray, str]] = []

    # --- Primary silhouette (clean outer contour) ---
    outer = largest_external_contour(mask)
    if outer is not None:
        for loop in split_closed_to_open(outer):
            smooth = chaikin(resample_open(loop, spacing=3.0), iterations=3)
            strokes.append((smooth, "main"))

    # --- Internal feature edges (masked, no border double-draw) ---
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    g2 = clahe.apply(gray)
    edges = cv2.Canny(g2, 55, 140)

    # Keep edges only well inside the subject (avoid duplicating silhouette)
    inner = cv2.erode(mask, np.ones((11, 11), np.uint8), iterations=1)
    edges = cv2.bitwise_and(edges, edges, mask=inner)

    # Connect small gaps, then thin-ish with erode after dilate
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)

    # Optional thinning for single-pixel ridges
    try:
        edges = cv2.ximgproc.thinning(edges)
    except Exception:
        # Fallback: light erode to reduce double ridges
        edges = cv2.erode(edges, np.ones((2, 2), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    min_len = w * 0.055
    internal: list[np.ndarray] = []
    for c in contours:
        peri = cv2.arcLength(c, False)
        if peri < min_len:
            continue
        pts = c.reshape(-1, 2).astype(np.float64)
        # Drop nearly-horizontal scribble bands (jacket texture noise)
        if len(pts) >= 4:
            dx = np.abs(np.diff(pts[:, 0])).mean()
            dy = np.abs(np.diff(pts[:, 1])).mean()
            if dx > 1e-3 and dy / dx < 0.22 and peri < w * 0.35:
                continue
        internal.append(pts)

    # Keep longest internal strokes only (face/hair structure)
    def peri(p: np.ndarray) -> float:
        return float(cv2.arcLength(p.reshape(-1, 1, 2).astype(np.float32), False))

    internal.sort(key=peri, reverse=True)
    for pts in internal[:80]:
        smooth = chaikin(resample_open(pts, spacing=2.2), iterations=2)
        if len(smooth) >= 2:
            strokes.append((smooth, "detail"))

    return strokes, w, h


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

    strokes, src_w, src_h = extract_strokes(bgr)
    if not strokes:
        print("[make_lineart_svg] no strokes found", file=sys.stderr)
        sys.exit(1)

    grid_w = OUT_W - PAD * 2
    scale = grid_w / src_w
    grid_h = src_h * scale
    img_x = PAD
    img_y = CHROME_TOP + 6
    height = int(img_y + grid_h + PAD + 8)

    paths: list[str] = []
    for i, (pts, kind) in enumerate(strokes):
        d = catmull_rom_to_bezier_path(pts, scale, scale, img_x, img_y)
        if not d:
            continue
        if kind == "main":
            stroke, width = STROKE, 1.55
        else:
            stroke, width = STROKE_SOFT, 1.05
        delay = 0.05 + i * 0.012
        length = max(
            50,
            int(cv2.arcLength(pts.reshape(-1, 1, 2).astype(np.float32), False) * scale),
        )

        if static:
            paths.append(
                f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )
        else:
            paths.append(
                f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}" '
                f'stroke-linecap="round" stroke-linejoin="round" '
                f'stroke-dasharray="{length}" stroke-dashoffset="0" opacity="1">'
                f'<animate attributeName="stroke-dashoffset" from="{length}" to="0" '
                f'begin="{delay:.3f}s" dur="0.7s" fill="freeze"/>'
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
