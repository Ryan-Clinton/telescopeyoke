"""The Moon in a picture and in the sky: where its disc is in a frame, how
bright it is, the part of the sensor that holds it, and tonight's Moon (its
phase, age, distance and size, from sky.py). moon.py uses these.

The disc is found from the Moon itself, not from stars: the bright region,
then a circle fitted to its edge. The terminator lies inside the true
circle, so the fit is repeated on the edge points on or outside the last
circle until only the sunlit limb is left. A crescent's centre is found as
well as a full Moon's.
"""
import math

import numpy as np
from scipy import ndimage

TARGET_LEVEL = 0.72           # the bright surface this far up the scale: room below clipping
CLIPPED_SHARE = 0.001         # at most this share of the disc at the top of the scale


def _fit_circle(y, x):
    """Least-squares circle through points: (cy, cx, r)."""
    a = np.column_stack([x, y, np.ones_like(x)])
    b = x ** 2 + y ** 2
    (c0, c1, c2), *_ = np.linalg.lstsq(a, b, rcond=None)
    cx, cy = c0 / 2, c1 / 2
    return cy, cx, math.sqrt(max(c2 + cx ** 2 + cy ** 2, 0.0))


def find_disc(image, shrink=4):
    """The Moon's disc in a picture (a 2-D brightness array): a dict with its
    centre (cy, cx) and radius r in the picture's pixels, the bounding box of
    the lit part (top, left, bottom, right), the brightness of its bright
    surface, and the level only CLIPPED_SHARE of it is above. None when no
    disc is found."""
    a = np.asarray(image, dtype=np.float32)
    small = a[:a.shape[0] // shrink * shrink, :a.shape[1] // shrink * shrink].reshape(
        a.shape[0] // shrink, shrink, a.shape[1] // shrink, shrink).mean(axis=(1, 3))
    top = np.percentile(small, 99.5)
    floor = np.median(small)
    if top <= floor * 1.5 + 1e-6:
        return None
    lit = small > floor + 0.35 * (top - floor)
    labels, count = ndimage.label(lit)
    if not count:
        return None
    sizes = ndimage.sum(lit, labels, range(1, count + 1))
    disc = labels == 1 + int(np.argmax(sizes))
    if disc.sum() < 50:
        return None
    disc = ndimage.binary_fill_holes(disc)
    edge = disc & ~ndimage.binary_erosion(disc)
    # Points on the frame's border are where the frame cuts the disc, not its limb.
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = False
    ys, xs = np.nonzero(edge)
    if len(ys) < 10:
        return None
    ys, xs = ys.astype(float), xs.astype(float)
    cy, cx, r = _fit_circle(ys, xs)
    for _ in range(6):
        outside = np.hypot(ys - cy, xs - cx) >= r - 1.5
        if outside.sum() < 10:
            break
        cy, cx, r = _fit_circle(ys[outside], xs[outside])
    rows, cols = np.nonzero(disc)
    inside = np.zeros(a.shape, bool)
    big = np.repeat(np.repeat(disc, shrink, 0), shrink, 1)
    inside[:big.shape[0], :big.shape[1]] = big
    surface = a[inside]
    return {"cy": (cy + 0.5) * shrink - 0.5, "cx": (cx + 0.5) * shrink - 0.5, "r": r * shrink,
            "box": (int(rows.min() * shrink), int(cols.min() * shrink),
                    int((rows.max() + 1) * shrink), int((cols.max() + 1) * shrink)),
            "level": float(np.percentile(surface, 99)) if surface.size else 0.0,
            "peak": float(np.percentile(surface, 100 * (1 - CLIPPED_SHARE))) if surface.size else 0.0}


def offset(disc, shape):
    """How far the disc's centre is from the frame's middle, in pixels
    (down, right)."""
    return disc["cy"] - (shape[0] - 1) / 2, disc["cx"] - (shape[1] - 1) / 2


def roi(disc, shape, margin=0.08, step=16):
    """The part of the sensor that holds the whole disc with `margin` (a
    share of its diameter) around it, as (x, y, width, height) rounded to
    `step` pixels so the colour pattern and the camera's own rounding agree."""
    r = disc["r"] * (1 + 2 * margin)
    size = int(math.ceil(2 * r / step) * step)
    w, h = min(size, shape[1] // step * step), min(size, shape[0] // step * step)
    x = int(round((disc["cx"] - w / 2) / step) * step)
    y = int(round((disc["cy"] - h / 2) / step) * step)
    return (max(0, min(x, shape[1] - w)), max(0, min(y, shape[0] - h)), w, h)


def exposure_for(disc, exposure, white, gain=100, longest=0.03, most_gain=400):
    """(exposure, gain) that put the bright surface at TARGET_LEVEL of the
    scale: the shortest exposure that does, since a short one freezes the
    air. Gain rises only once the exposure would pass `longest`."""
    level = max(disc["level"], 1.0)
    if disc["peak"] >= 0.98 * white:
        level = max(level, white) * 2          # clipped: the true level is unknown, so halve
    wanted = exposure * TARGET_LEVEL * white / level
    if wanted <= longest:
        return max(wanted, 0.0002), gain
    raised = min(most_gain, gain * wanted / longest)
    return wanted * gain / raised, int(round(raised))


def calibration(moves):
    """The 2x2 matrix that turns a move on the sky (arcminutes east, north)
    into a move of the picture (pixels down, right), from two or more
    measured moves: [((east, north), (down, right)), ...]."""
    sky = np.array([m[0] for m in moves], float)
    picture = np.array([m[1] for m in moves], float)
    solved, *_ = np.linalg.lstsq(sky, picture, rcond=None)
    return solved.T          # picture = M @ sky


def correction(matrix, down, right):
    """Arcminutes (east, north) to add to the aim to bring a disc that is
    (down, right) pixels off the middle back to it."""
    east, north = np.linalg.solve(np.asarray(matrix, float), -np.array([down, right], float))
    return float(east), float(north)


def state(site, when=None):
    """Tonight's Moon at the site (sky.moon_state: per cent lit, waxing or
    waning, age, distance, size and altitude)."""
    import sky
    return sky.moon_state(site, when)
