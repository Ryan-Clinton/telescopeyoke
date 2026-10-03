#!/usr/bin/env python3
"""Take a picture: several short exposures lined up and averaged.

    ./shoot.py M27                     12 frames of 2 s
    ./shoot.py M27 --frames 30 --exposure 2
    ./shoot.py M27 --frames 48 --recentre 8    re-centre on M27 every 8 frames

The mount drifts off target over a few minutes, so long runs need --recentre.
That moves the mount by small amounts, so it needs serial access:
    sudo -u $USER -g dialout ./shoot.py M27 --frames 48 --recentre 8

Short exposures keep the stars round while the mount drifts; averaging them
brings out faint detail and smooths the grain. The picture on the web page
updates after every frame, and the result is saved as web/NAME.jpg and
frames/NAME-*.fits.
"""
import argparse
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image
from scipy import ndimage

from camera import Camera, colour, stretch

ROOT = Path(__file__).parent
WEB = ROOT / "web"
FRAMES = ROOT / "frames"
REGISTER = 1024  # side of the central square used to line frames up


def clean(rgb):
    """Replace hot pixels: anything far brighter than its neighbours."""
    out = rgb.copy()
    for c in range(3):
        plane = rgb[..., c]
        local = ndimage.median_filter(plane, 3)
        spread = 1.4826 * np.median(np.abs(plane - local)) + 1e-6
        hot = plane - local > 8 * spread
        out[..., c][hot] = local[hot]
    return out


def centre_square(rgb):
    """The middle of the frame reduced to its stars only. The sensor's own
    fixed pattern and dust shadows sit still from frame to frame, and would
    otherwise fool the line-up into finding no movement at all."""
    lum = rgb.sum(axis=2)
    y, x = (lum.shape[0] - REGISTER) // 2, (lum.shape[1] - REGISTER) // 2
    square = ndimage.gaussian_filter(lum[y:y + REGISTER, x:x + REGISTER], 1.5)
    square = square - ndimage.uniform_filter(square, 64)
    noise = 1.4826 * np.median(np.abs(square))
    return np.clip(square - 5 * noise, 0, None)


def offset(reference, square):
    """(rows, cols) to shift a frame by so its stars land on the reference's."""
    fa, fb = np.fft.fft2(reference), np.fft.fft2(square)
    match = np.fft.ifft2(fa * fb.conj()).real
    dy, dx = np.unravel_index(np.argmax(match), match.shape)
    return (dy - REGISTER if dy > REGISTER // 2 else dy,
            dx - REGISTER if dx > REGISTER // 2 else dx)


def publish(stack, name, count, total):
    image = Image.fromarray(stretch(stack))
    WEB.mkdir(exist_ok=True)
    image.resize((1600, round(1600 * image.height / image.width)), Image.LANCZOS) \
         .save(WEB / "latest.jpg", quality=88)
    image.save(WEB / f"{name}.jpg", quality=92)
    print(f"{datetime.now():%H:%M:%S}  {name}: {count} of {total} frames stacked", flush=True)


def add(mosaic, total, used, reference):
    """Line one raw frame up with the first and add it to the running sum."""
    rgb = clean(colour(mosaic))
    square = centre_square(rgb)
    if reference is None:
        return rgb.copy(), 1, square
    dy, dx = offset(reference, square)
    if max(abs(dy), abs(dx)) > REGISTER // 3:
        print("  frame skipped: could not line it up (cloud or a knock?)", flush=True)
        return total, used, reference
    return total + ndimage.shift(rgb, (dy, dx, 0), order=0, mode="nearest"), used + 1, reference


def recentre(target):
    """Put the target back in the middle of the frame by plate solving."""
    import config
    import mount
    scope = mount.Mount(watch=False)
    try:
        scope.goto_target(target, config.load()["site"], solve=True)
    except BaseException:
        scope.stop()
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="what it is a picture of; used for the file names")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--exposure", type=float, default=2.0, help="seconds per frame")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--recentre", type=int, metavar="N", default=0,
                    help="slew back onto the target every N frames")
    args = ap.parse_args()
    name = args.name.replace(" ", "")

    total, used, reference = None, 0, None
    batch = args.recentre or args.frames
    for start in range(0, args.frames, batch):
        if args.recentre:
            recentre(args.name)
        with Camera(gain=args.gain) as cam:
            for _ in range(min(batch, args.frames - start)):
                mosaic, _ = cam.frame(args.exposure)
                total, used, reference = add(mosaic, total, used, reference)
                if used:
                    publish(total / used, name, used, args.frames)
    if not used:
        raise SystemExit("No usable frames.")
    FRAMES.mkdir(exist_ok=True)
    path = FRAMES / f"{name}-{datetime.now():%Y%m%d-%H%M%S}.fits"
    header = fits.Header({"OBJECT": args.name, "EXPTIME": args.exposure * used,
                          "NFRAMES": used, "GAIN": args.gain})
    fits.PrimaryHDU(np.moveaxis(total / used, 2, 0).astype(np.float32), header).writeto(path)
    print(f"saved {path} and {WEB / (name + '.jpg')}")


if __name__ == "__main__":
    main()
