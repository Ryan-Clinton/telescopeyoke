#!/usr/bin/env python3
"""Compare stacks of the same target side by side, at full size.

    ./compare.py old.fits live.fits final.fits --labels "old" "live" "restack"

Finds the same patch of sky in each stack, shows it at one screen pixel per
image pixel (doubled for visibility, with no smoothing), and prints what the
stars measure in each: width, roundness, how many were found, and how far the
typical star stands above the background grain. Writes web/compare.jpg.
"""
import argparse
from pathlib import Path

import config

import numpy as np
from astropy.io import fits
from PIL import Image, ImageDraw, ImageFont

import stacking
from camera import stretch

ROOT = Path(__file__).parent


def load(path):
    rgb = np.moveaxis(fits.getdata(path), 0, 2).astype(np.float32)
    lum = rgb.sum(axis=2)
    stars = stacking.find_stars(lum)
    q = stacking.quality(lum, stars)
    # Grain measured on the sky between the stars, after removing its slope.
    q["signal"] = q["flux"] / q["noise"] if q["stars"] else 0.0
    return rgb, lum, stars, q


def same_patch(first, other, centre):
    """Where `centre` (x, y) in the first stack falls in another stack."""
    _, lum_a, stars_a, _ = first
    _, lum_b, stars_b, _ = other
    rough = stacking.offset(stacking.centre_square(lum_b), stacking.centre_square(lum_a))
    r, t, matched, _ = stacking.align(stars_a, stars_b, rough)
    return r @ np.array(centre, dtype=float) + t, matched


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stacks", nargs="+", help="stack FITS files of the same target")
    ap.add_argument("--labels", nargs="+")
    ap.add_argument("--size", type=int, default=320, help="width of the patch in image pixels")
    ap.add_argument("--output", default=str(config.DATA / "web" / "compare.jpg"))
    args = ap.parse_args()
    labels = args.labels or [Path(p).parent.name + "/" + Path(p).name for p in args.stacks]

    loaded = [load(p) for p in args.stacks]
    rows, cols = loaded[0][1].shape
    centre = (cols / 2, rows / 2)
    font = ImageFont.load_default(size=20)
    panels = []
    print(f"{'stack':<14} {'FWHM':>5} {'round':>6} {'stars':>6} {'signal':>7}")
    for label, item in zip(labels, loaded):
        rgb, _, _, q = item
        (x, y), _ = (centre, None) if item is loaded[0] else same_patch(loaded[0], item, centre)
        half = args.size // 2
        x0 = int(np.clip(round(x) - half, 0, rgb.shape[1] - args.size))
        y0 = int(np.clip(round(y) - half, 0, rgb.shape[0] - args.size))
        patch = Image.fromarray(stretch(rgb[y0:y0 + args.size, x0:x0 + args.size]))
        patch = patch.resize((args.size * 2, args.size * 2), Image.NEAREST)
        panel = Image.new("RGB", (patch.width, patch.height + 64), (11, 13, 18))
        panel.paste(patch, (0, 64))
        draw = ImageDraw.Draw(panel)
        draw.text((8, 6), label, fill=(215, 220, 230), font=font)
        draw.text((8, 34), f"FWHM {q['fwhm']:.1f}  round {q['roundness']:.2f}",
                  fill=(138, 147, 166), font=font)
        panels.append(panel)
        print(f"{label:<14} {q['fwhm']:>5.1f} {q['roundness']:>6.2f} {q['stars']:>6} {q['signal']:>7.0f}")
    sheet = Image.new("RGB", (sum(p.width for p in panels) + 8 * (len(panels) - 1), panels[0].height),
                      (11, 13, 18))
    x = 0
    for panel in panels:
        sheet.paste(panel, (x, 0))
        x += panel.width + 8
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=92)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
