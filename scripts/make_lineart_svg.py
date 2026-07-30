#!/usr/bin/env python3
"""
Generate a red line-art portrait SVG with terminal chrome.

Expects a clean black-on-white line drawing (e.g. assets/lineart-source.png).
Recolors ink to red, punches out the white backdrop, and embeds it in the
same terminal frame styling used by the other portrait SVGs.

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

import numpy as np
from PIL import Image, ImageOps

BG = "#0d1117"
PANEL = "#1a1014"
BORDER = "#6b2222"
MUTED = "#c48a8a"
INK = (255, 107, 107)  # #ff6b6b

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
    """Black ink → red; white paper → transparent."""
    gray = ImageOps.grayscale(img)
    # Soft threshold so anti-aliased edges keep partial alpha
    arr = np.asarray(gray, dtype=np.float32)
    # ink strength: 0 on white, 1 on black
    ink = 1.0 - (arr / 255.0)
    ink = np.clip((ink - 0.04) / 0.96, 0.0, 1.0)
    # Slight contrast so mid greys become clearer strokes
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
    # Render at 2x then fit for crisp lines on HiDPI
    hi = fit_portrait(raw, img_w * 2, IMG_MAX_H * 2)
    rgba = lineart_to_red_rgba(hi)
    rgba = fit_portrait(rgba, img_w, IMG_MAX_H)
    iw, ih = rgba.size

    img_x = (OUT_W - iw) / 2
    img_y = CHROME_TOP + 8
    height = int(img_y + ih + PAD + 8)
    b64 = encode_png(rgba)

    anim = ""
    if not static:
        anim = (
            '<animate attributeName="opacity" from="0" to="1" begin="0.08s" '
            'dur="0.5s" fill="freeze"/>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{OUT_W}" height="{height}" viewBox="0 0 {OUT_W} {height}" role="img" aria-label="Line art portrait">
  <rect width="100%" height="100%" fill="{BG}" rx="12"/>
  <rect x="8" y="8" width="{OUT_W - 16}" height="{height - 16}" rx="10" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
  <circle cx="26" cy="28" r="5" fill="#ff5f56"/>
  <circle cx="42" cy="28" r="5" fill="#ffbd2e"/>
  <circle cx="58" cy="28" r="5" fill="#27c93f"/>
  <text x="76" y="32" fill="{MUTED}" font-size="12" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">portrait · line art</text>

  <defs>
    <clipPath id="photoClip">
      <rect x="{img_x}" y="{img_y}" width="{iw}" height="{ih}" rx="6"/>
    </clipPath>
  </defs>

  <rect x="{img_x - 2}" y="{img_y - 2}" width="{iw + 4}" height="{ih + 4}" rx="6" fill="#0a0505" stroke="{BORDER}" stroke-opacity="0.6"/>
  <g clip-path="url(#photoClip)" opacity="1">{anim}
    <image x="{img_x}" y="{img_y}" width="{iw}" height="{ih}"
           href="data:image/png;base64,{b64}"
           xlink:href="data:image/png;base64,{b64}"
           preserveAspectRatio="xMidYMid meet"/>
  </g>
</svg>
"""

    Path(args.output).write_text(svg, encoding="utf-8")
    print(f"[make_lineart_svg] wrote {args.output} ({iw}x{ih})")


if __name__ == "__main__":
    main()
