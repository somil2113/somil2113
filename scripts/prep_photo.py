#!/usr/bin/env python3
"""
Prepare portrait photo for ASCII conversion:
- optional background removal (rembg)
- CLAHE contrast enhancement
- composite on white
- grayscale output

Usage:
  python scripts/prep_photo.py <input_image> [--output source-prepped.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def remove_bg_if_available(img: Image.Image) -> Image.Image:
    try:
        from rembg import remove
    except Exception:
        print("[prep_photo] rembg not installed/available, skipping background removal.")
        return img
    print("[prep_photo] removing background...")
    return remove(img.convert("RGBA"))


def composite_on_white(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, rgba).convert("RGB")


def apply_clahe(gray_np: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    return clahe.apply(gray_np)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prep photo for ASCII SVG conversion")
    parser.add_argument("input_image", help="Path to input photo")
    parser.add_argument(
        "--output",
        default="source-prepped.png",
        help="Output grayscale image path (default: source-prepped.png)",
    )
    args = parser.parse_args()

    in_path = Path(args.input_image)
    if not in_path.exists():
        print(f"[prep_photo] input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    try:
        img = Image.open(in_path).convert("RGBA")
    except Exception as exc:
        print(f"[prep_photo] failed to open image: {exc}", file=sys.stderr)
        sys.exit(1)

    img = remove_bg_if_available(img)
    img = composite_on_white(img)

    gray = apply_clahe(np.array(img.convert("L")))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(gray).save(out_path)
    print(f"[prep_photo] wrote {out_path}")


if __name__ == "__main__":
    main()
