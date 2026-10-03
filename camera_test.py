#!/usr/bin/env python3
"""Find the camera gain that suits tonight's sky, by trying a range of them.

    ./camera_test.py --gain-sweep
    ./camera_test.py --gain-sweep --gains 300 900 1500 2500 --exposure 2

For each gain it takes a frame of the sky the telescope is pointed at and
reports the sky level and grain, how many pixels are burnt out, how many
stars it can find and how strongly they stand out. High gain lowers the
camera's own noise but burns out bright stars sooner; the best setting finds
the most stars without burning many pixels. The gain numbers are this
camera's own and do not match other makes'.
"""
import argparse

import numpy as np

import stacking
from camera import WHITE, Camera, luminance

GAINS = (300, 600, 900, 1200, 1500, 1800)


def measure(mosaic):
    lum = luminance(mosaic)
    stars = stacking.find_stars(lum)
    q = stacking.quality(lum, stars)
    q["burnt"] = float((mosaic >= WHITE - 1).mean())
    # How far the typical star stands above the sky's grain.
    q["signal"] = float(np.median(stars[:, 2]) / q["noise"]) if len(stars) else 0.0
    return q


def recommend(results):
    """The gain that finds the most stars while burning out under 0.02% of
    pixels; None if no gain found any."""
    usable = [(q["stars"], gain) for gain, q in results if q["burnt"] < 0.0002 and q["stars"]]
    return max(usable)[1] if usable else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gain-sweep", action="store_true", required=True)
    ap.add_argument("--gains", type=int, nargs="+", default=list(GAINS))
    ap.add_argument("--exposure", type=float, default=2.0)
    args = ap.parse_args()

    results = []
    print(f"{'gain':>5} {'sky':>6} {'grain':>6} {'burnt':>7} {'stars':>6} {'signal':>7} {'FWHM':>5}")
    for gain in args.gains:
        with Camera(gain=gain) as cam:
            mosaic, _ = cam.frame(args.exposure)
        q = measure(mosaic)
        results.append((gain, q))
        fwhm = "" if q["fwhm"] is None else f"{q['fwhm']:.1f}"
        print(f"{gain:>5} {q['background']:>6.0f} {q['noise']:>6.1f} {q['burnt']:>7.3%} "
              f"{q['stars']:>6} {q['signal']:>7.0f} {fwhm:>5}", flush=True)
    best = recommend(results)
    print(f"\nSuggested gain: {best}" if best else "\nNo stars found at any gain.")


if __name__ == "__main__":
    main()
