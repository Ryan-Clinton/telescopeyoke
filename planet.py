#!/usr/bin/env python3
"""Photograph a planet: many very short frames, the sharpest kept and stacked.

    ./planet.py Saturn                  capture 300 frames and stack the best quarter
    ./planet.py Jupiter --frames 600 --keep 0.15
    ./planet.py Saturn --exposure 20    20 milliseconds a frame instead of finding the exposure
    ./planet.py --restack frames/Saturn/planet-20261014-001500   stack the saved frames again
    ./planet.py Saturn --dry-run        say what it would do; the camera is not touched

Point the telescope first: ./mount.py goto Saturn --solve. This moves
nothing; it only uses the camera.

A planet is small and bright, and the air blurs it differently from one
hundredth of a second to the next. So it takes frames short enough to freeze
the air, keeps only a square round the planet from each, and stacks the
sharpest of them after lining each up on the best. Then it sharpens the
result and gives the planet its usual colour on average (TINTS, roughly
as the eye sees it): the camera's own colour balance at these exposures is
not to be trusted.

The camera reads out the whole sensor for every frame, so a frame takes far
longer than its exposure. A region of interest on the sensor would be much
faster and is not used yet.
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import config
import interface
import records

HALF = 128          # half the side of the square kept round the planet, in sensor pixels
FULL = 4095         # the 183C's brightest reading (12 bits)
AIM = 0.6           # the planet's brightest part is put at this share of FULL
START_MS = 20.0     # first exposure tried when finding one
GAIN = 300
# Each planet's average colour, red : green : blue, roughly as it looks.
# Neutral grey for anything not listed.
TINTS = {"saturn": (1.0, 0.92, 0.72), "jupiter": (1.0, 0.94, 0.84), "mars": (1.0, 0.72, 0.52),
         "venus": (1.0, 0.97, 0.88), "uranus": (0.80, 0.95, 1.0), "neptune": (0.62, 0.78, 1.0)}
SHOWN = 96          # side of the finished picture's square round the planet, before enlarging


def find_planet(mosaic):
    """Where the planet is in a frame, (row, col) on the colour grid (both
    even), and how bright its brightest part is."""
    smooth = ndimage.uniform_filter(mosaic.astype(np.float32), 15)
    y, x = np.unravel_index(np.argmax(smooth), smooth.shape)
    y, x = int(y) // 2 * 2, int(x) // 2 * 2
    patch = mosaic[max(y - 40, 0):y + 40, max(x - 40, 0):x + 40]
    return y, x, float(np.percentile(patch, 99.5))


def crop(mosaic, y, x, half=HALF):
    """The square round (y, x), or None if it runs off the sensor."""
    if y < half or x < half:
        return None
    square = mosaic[y - half:y + half, x - half:x + half]
    return square.astype(np.float32) if square.shape == (2 * half, 2 * half) else None


def capture(cam, frames, exposure_ms=None, say=print):
    """Find the planet, set the exposure if not given, and take `frames`
    frames. Returns (squares, exposure in ms)."""
    ms = exposure_ms or START_MS
    mosaic, _ = cam.frame(ms / 1000)
    y, x, peak = find_planet(mosaic)
    if exposure_ms is None:
        for _ in range(5):
            if 0.75 * AIM * FULL <= peak <= 1.25 * AIM * FULL:
                break
            ms = float(np.clip(ms * AIM * FULL / max(peak - 48, 1), 1.0, 200.0))
            mosaic, _ = cam.frame(ms / 1000)
            y, x, peak = find_planet(mosaic)
    say(f"exposure {ms:.1f} ms; brightest part {peak:.0f} of {FULL}; planet at x {x}, y {y}")
    squares, began = [], time.time()
    for i in range(frames):
        mosaic, _ = cam.frame(ms / 1000)
        square = crop(mosaic, y, x)
        if square is not None:
            squares.append(square)
        if (i + 1) % 50 == 0:
            say(f"  {i + 1} frames, {time.time() - began:.0f} s")
    return np.array(squares), ms


def colour(square):
    """Half-size RGB from an RGGB square."""
    green = (square[0::2, 1::2] + square[1::2, 0::2]) / 2
    return np.dstack([square[0::2, 0::2], green, square[1::2, 1::2]])


def sharpness(lum):
    """How sharp a frame is: the spread of its fine detail, after the noise
    has been smoothed a little. Larger is sharper."""
    return float(ndimage.laplace(ndimage.gaussian_filter(lum, 1.0)).var())


def shift_to(reference, lum):
    """The (rows, cols) to move `lum` by to sit on `reference`, to a fraction
    of a pixel, from where their cross-correlation peaks."""
    a = reference - reference.mean()
    b = lum - lum.mean()
    product = np.fft.fft2(a) * np.conj(np.fft.fft2(b))
    corr = np.fft.ifft2(product / (np.abs(product) + 1e-9)).real
    row, col = np.unravel_index(np.argmax(corr), corr.shape)

    def fine(before, here, after):
        bend = before - 2 * here + after
        return 0.5 * (before - after) / bend if bend < 0 else 0.0

    rows, cols = corr.shape
    dy = row + fine(corr[(row - 1) % rows, col], corr[row, col], corr[(row + 1) % rows, col])
    dx = col + fine(corr[row, (col - 1) % cols], corr[row, col], corr[row, (col + 1) % cols])
    return (dy - rows if dy > rows / 2 else dy, dx - cols if dx > cols / 2 else dx)


def stack(squares, keep=0.25):
    """The sharpest `keep` share of the squares, lined up on the sharpest
    and averaged: (RGB image, how many were stacked)."""
    images = [colour(s) for s in squares]
    background = float(np.median([np.percentile(i, 5) for i in images]))
    lums = [i.sum(axis=2) for i in images]
    order = np.argsort([-sharpness(l) for l in lums])
    chosen = order[:max(1, int(round(keep * len(images))))]
    reference = lums[chosen[0]]
    total = np.zeros_like(images[0])
    for i in chosen:
        dy, dx = shift_to(reference, lums[i])
        total += ndimage.shift(images[i] - background, (dy, dx, 0), order=3, mode="nearest")
    return total / len(chosen), len(chosen)


def finish(rgb, name="", sharpen=1.5, enlarge=4):
    """Sharpen, colour the planet as it usually looks, cut a square round it
    and stretch to 8 bits, enlarged."""
    lum = rgb.sum(axis=2)
    disc = lum > 0.25 * np.percentile(lum, 99.5)
    if disc.any():
        means = np.array([rgb[..., c][disc].mean() for c in range(3)])
        tint = np.array(TINTS.get(name.lower(), (1.0, 1.0, 1.0)))
        rgb = rgb * (tint / tint.mean()) * (means.mean() / np.maximum(means, 1e-6))
        cy, cx = (int(round(v)) for v in ndimage.center_of_mass(disc))
        half = min(SHOWN // 2, cy, cx, rgb.shape[0] - cy, rgb.shape[1] - cx)
        rgb = rgb[cy - half:cy + half, cx - half:cx + half]
    blurred = ndimage.gaussian_filter(rgb, (1.5, 1.5, 0))
    rgb = rgb + sharpen * (rgb - blurred)
    top = np.percentile(rgb, 99.9)
    image = np.clip(rgb / max(top, 1e-6), 0, 1) ** 0.8
    picture = Image.fromarray((255 * image).astype(np.uint8))
    return picture.resize((picture.width * enlarge, picture.height * enlarge), Image.LANCZOS)


def save(folder, name, squares, exposure_ms, gain):
    folder.mkdir(parents=True, exist_ok=True)
    np.save(folder / "squares.npy", squares.astype(np.uint16))
    records.write(folder / "planet.json",
                  {"name": name, "frames": len(squares), "exposure_ms": round(exposure_ms, 2), "gain": gain},
                  indent=None)


def process(folder, keep, say=print):
    about = json.loads((folder / "planet.json").read_text(encoding="utf-8"))
    squares = np.load(folder / "squares.npy").astype(np.float32)
    rgb, used = stack(squares, keep)
    picture = finish(rgb, about["name"])
    picture.save(folder / "final.jpg", quality=93)
    web = config.DATA / "web"
    web.mkdir(exist_ok=True)
    picture.save(web / f"{about['name']}-final.jpg", quality=93)
    say(f"{used} of {len(squares)} frames stacked, the sharpest {keep:.0%}; "
        f"saved {folder / 'final.jpg'} and web/{about['name']}-final.jpg")
    return {"name": about["name"], "frames": len(squares), "stacked": used,
            "exposure_ms": about["exposure_ms"], "picture": str(folder / "final.jpg")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", nargs="?", help="the planet, as it should be filed (Saturn, Jupiter, Mars)")
    ap.add_argument("--frames", type=int, default=300, help="frames to take (default 300)")
    ap.add_argument("--keep", type=float, default=0.25, help="share of the sharpest frames to stack (default 0.25)")
    ap.add_argument("--exposure", type=float, metavar="MS", help="milliseconds a frame; found if left out")
    ap.add_argument("--gain", type=int, default=GAIN)
    ap.add_argument("--restack", metavar="FOLDER", help="stack a saved capture again")
    ap.add_argument("--dry-run", action="store_true", help="say what it would do; the camera is not touched")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()

    def work():
        if not 0 < args.keep <= 1:
            raise interface.Refusal("INVALID_REQUEST", "--keep is a share, more than 0 and at most 1.")
        if args.restack:
            return process(Path(args.restack), args.keep)
        if not args.name:
            raise interface.Refusal("INVALID_REQUEST", "Name the planet, or give --restack FOLDER.")
        folder = config.DATA / "frames" / args.name / f"planet-{datetime.now():%Y%m%d-%H%M%S}"
        if args.dry_run:
            how = f"{args.exposure:g} ms" if args.exposure else "an exposure found from the planet's brightness"
            print(f"Would take {args.frames} frames of {args.name} at {how}, gain {args.gain}, keep a "
                  f"{2 * HALF}-pixel square round it from each, and stack the sharpest {args.keep:.0%} into "
                  f"{folder}. Nothing moves.")
            return {"would_capture": args.frames, "folder": str(folder)}
        from camera import Camera
        with Camera(gain=args.gain) as cam:
            squares, ms = capture(cam, args.frames, args.exposure)
        if not len(squares):
            raise interface.Refusal("NO_STARS", "The planet was too near the edge of the frame: centre it.")
        save(folder, args.name, squares, ms, args.gain)
        return process(folder, args.keep)

    interface.main("planet", work, args.json)


if __name__ == "__main__":
    main()
