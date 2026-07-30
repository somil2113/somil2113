#!/usr/bin/env python3
"""
Generate a red-duotone portrait SVG with terminal chrome.

Usage:
  python scripts/make_duotone_svg.py [--input assets/source-photo.jpg] [--output portrait-duotone.svg]

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

from PIL import Image, ImageEnhance, ImageOps

BG = "#0d1117"
PANEL = "#1a1014"
BORDER = "#6b2222"
MUTED = "#c48a8a"
SHADOW = "#0a0505"
HIGHLIGHT = "#ffb4b4"

# Duotone map: dark → deep crimson, light → soft rose
TONE_DARK = (18, 4, 6)
TONE_LIGHT = (255, 180, 180)

OUT_W = 370
CHROME_TOP = 44
PAD = 14
IMG_MAX_H = 420


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def apply_duotone(img: Image.Image) -> Image.Image:
    """Map grayscale luminance onto a red duotone ramp."""
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.15)

    def channel_lut(c0: int, c1: int) -> list[int]:
        return [int(lerp(c0, c1, (i / 255.0) ** 0.9)) for i in range(256)]

    r = gray.point(channel_lut(TONE_DARK[0], TONE_LIGHT[0]))
    g = gray.point(channel_lut(TONE_DARK[1], TONE_LIGHT[1]))
    b = gray.point(channel_lut(TONE_DARK[2], TONE_LIGHT[2]))
    return Image.merge("RGB", (r, g, b))


def encode_jpeg(img: Image.Image, quality: int = 88) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def fit_portrait(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Resize to fit inside max box, keeping aspect ratio."""
    w, h = img.size
    scale = min(max_w / w, max_h / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def scanlines(x: float, y: float, w: float, h: float, step: int = 3) -> str:
    lines = []
    yy = y
    while yy < y + h:
        lines.append(
            f'<line x1="{x}" y1="{yy:.1f}" x2="{x + w}" y2="{yy:.1f}" '
            f'stroke="#000000" stroke-opacity="0.18" stroke-width="1"/>'
        )
        yy += step
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate red duotone portrait SVG")
    parser.add_argument("--input", default="assets/source-photo.jpg")
    parser.add_argument("--output", default="portrait-duotone.svg")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[make_duotone_svg] input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    static = os.getenv("STATIC", "0") == "1"

    try:
        raw = Image.open(in_path).convert("RGB")
    except Exception as exc:
        print(f"[make_duotone_svg] failed to open image: {exc}", file=sys.stderr)
        sys.exit(1)

    img_w = OUT_W - PAD * 2
    fitted = fit_portrait(raw, img_w * 2, IMG_MAX_H * 2)  # 2x for sharper embed
    duo = apply_duotone(fitted)
    duo = fit_portrait(duo, img_w, IMG_MAX_H)
    iw, ih = duo.size

    # Center image horizontally inside panel
    img_x = (OUT_W - iw) / 2
    img_y = CHROME_TOP + 8
    panel_h = img_y + ih + PAD
    height = int(panel_h + 8)
    b64 = encode_jpeg(duo)

    anim = ""
    if not static:
        # Default opacity=1 so GitHub (often no SMIL) still shows the portrait
        anim = (
            '<animate attributeName="opacity" from="0" to="1" begin="0.1s" '
            'dur="0.55s" fill="freeze"/>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{OUT_W}" height="{height}" viewBox="0 0 {OUT_W} {height}" role="img" aria-label="Red duotone portrait">
  <rect width="100%" height="100%" fill="{BG}" rx="12"/>
  <rect x="8" y="8" width="{OUT_W - 16}" height="{height - 16}" rx="10" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
  <circle cx="26" cy="28" r="5" fill="#ff5f56"/>
  <circle cx="42" cy="28" r="5" fill="#ffbd2e"/>
  <circle cx="58" cy="28" r="5" fill="#27c93f"/>
  <text x="76" y="32" fill="{MUTED}" font-size="12" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace">portrait · duotone</text>

  <defs>
    <clipPath id="photoClip">
      <rect x="{img_x}" y="{img_y}" width="{iw}" height="{ih}" rx="6"/>
    </clipPath>
    <linearGradient id="vignette" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{SHADOW}" stop-opacity="0.15"/>
      <stop offset="70%" stop-color="{SHADOW}" stop-opacity="0"/>
      <stop offset="100%" stop-color="{SHADOW}" stop-opacity="0.35"/>
    </linearGradient>
  </defs>

  <g clip-path="url(#photoClip)" opacity="1">{anim}
    <image x="{img_x}" y="{img_y}" width="{iw}" height="{ih}"
           href="data:image/jpeg;base64,{b64}"
           xlink:href="data:image/jpeg;base64,{b64}"
           preserveAspectRatio="xMidYMid slice"/>
    {scanlines(img_x, img_y, iw, ih)}
    <rect x="{img_x}" y="{img_y}" width="{iw}" height="{ih}" fill="url(#vignette)"/>
  </g>

  <rect x="{img_x}" y="{img_y}" width="{iw}" height="{ih}" rx="6" fill="none" stroke="{BORDER}" stroke-opacity="0.7"/>
</svg>
"""

    Path(args.output).write_text(svg, encoding="utf-8")
    print(f"[make_duotone_svg] wrote {args.output} ({iw}x{ih})")


if __name__ == "__main__":
    main()
