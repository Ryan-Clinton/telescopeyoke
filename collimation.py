#!/usr/bin/env python3
"""Is the telescope still collimated? Measured from a defocused star.

    ./ty collimation                 three frames of what the camera sees now
    ./ty collimation --file F.fits   a frame already taken
    ./ty collimation --history       every check so far

Defocused, a star in a Newtonian is a doughnut: a bright ring with the
secondary mirror's shadow in the middle. When the mirrors are lined up the
shadow sits in the middle of the ring; when they are not it sits to one
side. This finds the ring's outer edge and the shadow in the star nearest
the middle of the frame (stars towards the edge are bent by coma at f/5),
measures how far the shadow's centre is from the ring's as a share of the
ring's radius, and says what that means:

    under 5 %    fine
    5 to 10 %    slightly off: fine for deep sky, worth a look before a Barlow night
    over 10 %    off: time to have it collimated

It moves nothing and needs the stars out of focus, as they are when the
drawtube has been set a touch out by hand for the walk-in; the walk-in runs
this check by itself on its first doughnuts. Every check is kept in
cache/collimation.jsonl, so drift shows over the weeks.

24 October 2026: Gary collimates the telescope with a laser; this says
when it needs him, between visits, without one.
"""
import argparse
import json
import sys
import time

import numpy as np
from scipy import ndimage

import config

HISTORY = config.DATA / "cache" / "collimation.jsonl"
FINE, SLIGHT = 0.05, 0.10
SMALLEST = 20           # pixels across: a smaller doughnut is too near focus to show its shadow


def _fit_circle(y, x):
    a = np.column_stack([x, y, np.ones_like(x)])
    (c0, c1, c2), *_ = np.linalg.lstsq(a, x ** 2 + y ** 2, rcond=None)
    cx, cy = c0 / 2, c1 / 2
    return cy, cx, float(np.sqrt(max(c2 + cx ** 2 + cy ** 2, 0.0)))


def doughnut(crop):
    """The ring's outer centre and radius and the shadow's centre in a crop
    round one defocused star: a dict, or None with no clear ring and shadow."""
    a = ndimage.gaussian_filter(np.asarray(crop, dtype=np.float32), 1.5)
    edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    sky, top = float(np.median(edge)), float(np.percentile(a, 99.5))
    if top - sky <= 0:
        return None
    lit = a > sky + 0.3 * (top - sky)
    labels, count = ndimage.label(lit)
    if not count:
        return None
    ring = labels == 1 + int(np.argmax(ndimage.sum(lit, labels, range(1, count + 1))))
    whole = ndimage.binary_fill_holes(ring)
    shadow = whole & ~ring
    if shadow.sum() < 4:
        return None
    border = whole & ~ndimage.binary_erosion(whole)
    ys, xs = np.nonzero(border)
    if len(ys) < 12:
        return None
    cy, cx, r = _fit_circle(ys.astype(float), xs.astype(float))
    if 2 * r < SMALLEST:
        return None
    labels, count = ndimage.label(shadow)
    biggest = labels == 1 + int(np.argmax(ndimage.sum(shadow, labels, range(1, count + 1))))
    sy, sx = ndimage.center_of_mass(biggest)
    return {"cy": cy, "cx": cx, "r": r, "sy": float(sy), "sx": float(sx)}


def stars(lum, most=12):
    """Centres (y, x) of the brightest blobs in a frame, the defocused stars."""
    small = ndimage.gaussian_filter(np.asarray(lum, dtype=np.float32), 3)
    sky = np.median(small)
    noise = 1.4826 * np.median(np.abs(small - sky))
    lit = small > sky + 8 * max(noise, 1e-6)
    labels, count = ndimage.label(lit)
    if not count:
        return []
    sizes = ndimage.sum(lit, labels, range(1, count + 1))
    order = np.argsort(sizes)[::-1][:most]
    return [ndimage.center_of_mass(lit, labels, i + 1) + (float(sizes[i]),) for i in order]


def check(lum):
    """The collimation from one frame of defocused stars: the star nearest
    the middle with a measurable doughnut, its shadow's offset as a share of
    the ring's radius and the way it points in the frame. None when no
    star shows a ring with a shadow (in focus, or no stars)."""
    h, w = lum.shape
    found = []
    for y, x, area in stars(lum):
        reach = int(np.sqrt(area / np.pi) * 1.6) + 6
        y0, x0 = max(int(y) - reach, 0), max(int(x) - reach, 0)
        crop = lum[y0:int(y) + reach, x0:int(x) + reach]
        d = doughnut(crop)
        if d:
            found.append((np.hypot(y - h / 2, x - w / 2), d))
    if not found:
        return None
    _, d = min(found, key=lambda f: f[0])
    dy, dx = d["sy"] - d["cy"], d["sx"] - d["cx"]
    share = float(np.hypot(dy, dx) / d["r"])
    way = ("up" if dy < 0 else "down") if abs(dy) >= abs(dx) else ("left" if dx < 0 else "right")
    return {"offset": round(share, 3), "towards": way, "ring_px": round(2 * d["r"]),
            "verdict": verdict(share)}


def verdict(share):
    if share < FINE:
        return "fine"
    if share < SLIGHT:
        return "slightly off: fine for deep sky, worth a look before a Barlow night"
    return "off: time to have it collimated"


def combine(results):
    """Several frames' checks as one: the median offset (seeing moves the
    shadow about from frame to frame)."""
    good = [r for r in results if r]
    if not good:
        return None
    share = float(np.median([r["offset"] for r in good]))
    ways = [r["towards"] for r in good]
    return {"offset": round(share, 3), "towards": max(set(ways), key=ways.count),
            "ring_px": int(np.median([r["ring_px"] for r in good])), "frames": len(good), "verdict": verdict(share)}


def keep(result, source):
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.time(), "source": source, **result}) + "\n")


def words(result):
    if result is None:
        return ("No doughnut with a shadow in it: the stars are in focus or too faint. Set the drawtube a touch "
                "out by hand, as for the walk-in, with a bright star in view.")
    return (f"Collimation {result['verdict']}: the shadow is {100 * result['offset']:.0f}% of the ring's radius "
            f"off centre, towards the {result['towards']} of the frame (doughnuts {result['ring_px']} px).")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", nargs="+", help="frames already taken (FITS) instead of the camera")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--gain", type=int, default=300)
    ap.add_argument("--history", action="store_true", help="every check so far")
    args = ap.parse_args(argv)
    if args.history:
        if HISTORY.exists():
            for line in HISTORY.read_text(encoding="utf-8").splitlines():
                e = json.loads(line)
                print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(e['at']))}  {100 * e['offset']:4.0f}%  "
                      f"{e['towards']:5}  {e['verdict']}")
        return 0
    from focus import luminance
    results = []
    if args.file:
        from astropy.io import fits
        for path in args.file:
            with fits.open(path) as hdul:
                data = next(h.data for h in hdul if h.data is not None)
            results.append(check(luminance(data)))
        source = "file"
    else:
        from camera import Camera
        with Camera(gain=args.gain) as cam:
            for _ in range(args.frames):
                mosaic, _ = cam.frame(args.exposure)
                results.append(check(luminance(mosaic)))
        source = "camera"
    result = combine(results)
    print(words(result))
    if result:
        keep(result, source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
