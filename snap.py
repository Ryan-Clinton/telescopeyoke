#!/usr/bin/env python3
"""Take one camera frame, keep the FITS, and publish a preview to the web page.

    ./snap.py --exposure 2 --gain 300
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image

from camera import PORT, Camera, colour, stretch

ROOT = Path(__file__).parent
FRAMES = ROOT / "frames"
PREVIEW = ROOT / "web" / "latest.jpg"
PREVIEW_WIDTH = 1600


def label(kind, detail="", folder=None, name="latest"):
    """Note beside a picture in web/ saying what it is a picture of."""
    folder = folder or PREVIEW.parent
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"kind": kind, "detail": detail}))


def publish(mosaic, path=PREVIEW, kind="single frame", detail="", quick=False):
    """Write a colour preview of a raw frame. web/latest.jpg, the default, is
    always the newest single exposure: what the telescope sees now. `quick`
    halves the size first, for callers that publish every frame."""
    rgb = colour(mosaic)
    image = Image.fromarray(stretch(rgb[::2, ::2] if quick else rgb))
    if image.width > PREVIEW_WIDTH:
        height = round(image.height * PREVIEW_WIDTH / image.width)
        image = image.resize((PREVIEW_WIDTH, height), Image.LANCZOS)
    path.parent.mkdir(exist_ok=True)
    partial = path.with_suffix(".part.jpg")
    image.save(partial, quality=88)
    partial.replace(path)   # the page never loads a half-written picture
    if path == PREVIEW:
        label(kind, detail)


def save(mosaic, header):
    FRAMES.mkdir(exist_ok=True)
    path = FRAMES / f"{datetime.now():%Y%m%d-%H%M%S}.fits"
    fits.PrimaryHDU(mosaic, header).writeto(path)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exposure", type=float, default=1.0, help="seconds")
    ap.add_argument("--gain", type=int, default=300, help="camera gain (100 = lowest)")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    started = time.monotonic()
    with Camera(args.port, args.gain) as cam:
        mosaic, header = cam.frame(args.exposure)
    took = time.monotonic() - started
    path = save(mosaic, header)
    publish(mosaic, detail=f"{args.exposure:g} s")
    print(f"{args.exposure:g}s exposure, {took:.1f}s in total")
    print(f"frame {mosaic.shape}, min {mosaic.min()}, median {np.median(mosaic):.0f}, "
          f"max {mosaic.max()} (of 4095)")
    print(f"saved {path} and {PREVIEW}")


if __name__ == "__main__":
    main()
