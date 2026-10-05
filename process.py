#!/usr/bin/env python3
"""Turn a stacked picture into a cleaner image for viewing.

    ./process.py M27                 newest frames/M27-*.fits -> web/M27-processed.jpg
    ./process.py M27 --crop 600      also a close-up of the middle, 600 pixels wide

shoot.py's own preview is stretched hard so faint things show while the stack
builds, which also shows every bit of grain. This evens out the background,
smooths the colour noise (the eye forgives soft colour far more than soft
detail), and uses a gentler stretch with a properly dark sky.
"""
import argparse
from pathlib import Path

import config

import numpy as np
from astropy.io import fits
from PIL import Image
from scipy import ndimage

import stacking

ROOT = Path(__file__).parent


def process(rgb, detail=0.8, colour=5.0, stretch=None, background=2, saturation=1.25):
    """rgb: float array (rows, cols, 3) from a stack. Returns 8-bit RGB."""
    rgb = rgb.astype(np.float32)
    # Level each channel: take out the sky glow and its gradient, then match
    # the channels' scales on the stars so the sky is neutral grey.
    # Take out the sky glow with a smooth surface fitted to the sky alone:
    # a tilt, or a gentle bowl at order 2. Anything finer would remove the
    # nebula along with the sky.
    rows, cols = rgb.shape[:2]
    yy, xx = np.mgrid[0:rows:64, 0:cols:64]
    terms = lambda y, x: [np.ones_like(y), y, x] + ([y * y, x * x, y * x] if background == 2 else [])
    ys, xs = yy.ravel() / rows, xx.ravel() / cols
    design = np.column_stack(terms(ys, xs))
    full_y, full_x = np.mgrid[0:rows, 0:cols]
    full = [t.astype(np.float32) for t in terms(full_y / rows, full_x / cols)]
    for c in range(3):
        samples = ndimage.median_filter(rgb[::64, ::64, c], 3).ravel()
        # Sky only: leave out stars, nebula and the empty edges of a stack.
        keep = (samples < np.percentile(samples, 60)) & (samples != 0)
        fit, *_ = np.linalg.lstsq(design[keep], samples[keep], rcond=None)
        rgb[..., c] -= sum(k * t for k, t in zip(fit, full))
    # Colour balance: the average star is white. Stars are the pixels far
    # above the sky in every channel.
    grey = rgb.mean(axis=2)
    spread = 1.4826 * np.median(np.abs(grey))
    stars = (grey > 15 * spread) & (grey < 0.5 * grey.max())
    if stars.sum() > 200:
        balance = rgb[stars].mean(axis=0)
        rgb *= balance.mean() / balance
    rgb /= 1.4826 * np.median(np.abs(rgb.mean(axis=2)))   # in units of the sky noise

    # Smooth brightness a little and colour a lot.
    brightness = rgb.mean(axis=2)
    tint = rgb - brightness[..., None]
    brightness = ndimage.gaussian_filter(brightness, detail)
    tint = ndimage.gaussian_filter(tint, (colour, colour, 0))
    rgb = brightness[..., None] + tint

    # Sky just above black; stretch so faint glow shows without lifting grain.
    softness = 1.0 / np.sqrt(1 + detail ** 2 * 12)   # noise left after smoothing
    black, white = -2.0 * softness, np.percentile(brightness, 99.995)
    scaled = np.clip((rgb - black) / (white - black), 0, 1)
    if stretch is None:
        stretch = auto_stretch((FAINT - black) / (white - black))
    out = np.arcsinh(stretch * scaled) / np.arcsinh(stretch)
    # A little more colour, pushed out from each pixel's own grey level.
    grey = out.mean(axis=2, keepdims=True)
    out = grey + saturation * (out - grey)
    return (255 * np.clip(out, 0, 1)).astype(np.uint8)


FAINT = 6.0          # a glow this many times the sky's grain above the sky...
FAINT_SHOWN = 0.22   # ...is shown at this share of full brightness


def auto_stretch(faint, shown=FAINT_SHOWN, lowest=10.0, highest=3000.0):
    """How hard to stretch so that a faint glow comes out clearly visible,
    whatever the brightest thing in the frame is. `faint` is the glow's level
    as a share of the white point. Found by halving the range."""
    curve = lambda k: np.arcsinh(k * faint) / np.arcsinh(k)
    if curve(lowest) >= shown:
        return lowest
    if curve(highest) <= shown:
        return highest
    for _ in range(40):
        middle = (lowest * highest) ** 0.5
        lowest, highest = (middle, highest) if curve(middle) < shown else (lowest, middle)
    return lowest


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="object name, as given to shoot.py")
    ap.add_argument("--crop", type=int, metavar="WIDTH",
                    help="also save a close-up this many pixels wide")
    ap.add_argument("--detail", type=float, default=0.8,
                    help="brightness smoothing in pixels; more is smoother and softer")
    ap.add_argument("--saturation", type=float, default=1.25, help="colour strength; 1 is as shot")
    ap.add_argument("--stretch", type=float,
                    help="how hard faint parts are brightened (default: chosen from the "
                         "picture so faint glow shows); about 25 is gentle, 500 is hard")
    args = ap.parse_args()

    name = stacking.folder_name(args.name)
    # Newest stack for this object: a restacked session's final.fits if there
    # is one, else shoot.py's own running stack.
    stacks = sorted(list((config.DATA / "frames").glob(f"{name}-*.fits"))
                    + list((config.DATA / "frames" / name).glob("*/final.fits"))
                    + list((config.DATA / "frames" / name).glob("*/live.fits")),
                    key=lambda p: p.stat().st_mtime)
    if not stacks:
        raise SystemExit(f"No stack for {name} in frames/. Run ./shoot.py {name} first.")
    data = fits.getdata(stacks[-1])
    image = Image.fromarray(process(np.moveaxis(data, 0, 2), args.detail,
                                    colour=6 * args.detail + 1, stretch=args.stretch,
                                    saturation=args.saturation))
    out = config.DATA / "web" / f"{name}-processed.jpg"
    image.save(out, quality=93)
    print(f"{stacks[-1].relative_to(ROOT)} -> {out}")
    if args.crop:
        # shoot.py lines every frame up on the first, which was taken just
        # after centring, so the object is in the middle.
        x, y = image.width // 2, image.height // 2
        w, h = args.crop, args.crop * 2 // 3
        close = image.crop((x - w // 2, y - h // 2, x + w // 2, y + h // 2))
        close = close.resize((1350, 900), Image.LANCZOS)
        close.save(config.DATA / "web" / f"{name}-processed-closeup.jpg", quality=93)
        print(f"close-up -> web/{name}-processed-closeup.jpg")


if __name__ == "__main__":
    main()
