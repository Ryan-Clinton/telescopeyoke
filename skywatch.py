#!/usr/bin/env python3
"""Watch for stars: photograph the sky through the telescope every minute and
stop as soon as stars show, or at a set time.

    ./skywatch.py --until 22:00

Each frame goes to the web page. Exits with a message saying whether the sky
cleared, so whatever started it knows when to carry on.
"""
import argparse
import time
from datetime import datetime

import numpy as np
from scipy import ndimage

from camera import Camera, luminance
from snap import publish, save

ENOUGH_STARS = 8  # in two frames running; a plate solve needs about this many


def count_stars(lum):
    """Number of star-like spots standing clear of the sky background."""
    lum = ndimage.median_filter(lum, 3)  # drop hot pixels
    flat = lum - ndimage.uniform_filter(lum, 64)  # drop the sky gradient
    noise = 1.4826 * float(np.median(np.abs(flat - np.median(flat))))
    spots, count = ndimage.label(flat > 6 * max(noise, 1.0))
    if not count:
        return 0
    sizes = ndimage.sum(np.ones_like(spots), spots, range(1, count + 1))
    # Stars cover a few pixels; anything huge is cloud edge or glare.
    return int(np.sum((sizes >= 3) & (sizes < 5000)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--until", default="22:00", help="give up at this time (HH:MM)")
    ap.add_argument("--every", type=float, default=60, help="seconds between frames")
    ap.add_argument("--exposure", type=float, default=2.0)
    args = ap.parse_args()

    hour, minute = (int(x) for x in args.until.split(":"))
    end = datetime.now().replace(hour=hour, minute=minute, second=0)
    streak = 0
    with Camera() as cam:
        while datetime.now() < end:
            started = time.monotonic()
            mosaic, header = cam.frame(args.exposure)
            stars = count_stars(luminance(mosaic))
            publish(mosaic)
            print(f"{datetime.now():%H:%M:%S}  {stars} stars, sky level "
                  f"{np.median(mosaic):.0f}", flush=True)
            streak = streak + 1 if stars >= ENOUGH_STARS else 0
            if streak >= 2:
                print(f"STARS VISIBLE: frame saved as {save(mosaic, header)}", flush=True)
                return
            time.sleep(max(0, args.every - (time.monotonic() - started)))
    print("No clear sky before the deadline.", flush=True)


if __name__ == "__main__":
    main()
