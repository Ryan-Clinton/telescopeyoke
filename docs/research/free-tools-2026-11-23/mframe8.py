"""CANDIDATE 8 (development data only): candidate 7, with one change: a spared pixel must also look like a star,
not a star with a hit on it. A sharp core is at most about 1.6 times its brightest neighbour (corelook.py: 1.2 to 1.6);
a cosmic ray on a star makes it far more. So within a confirmed star, a pixel over twice its brightest neighbour
above the sky is not spared. The rest is candidate 7.

CANDIDATE 7 (development data only): the shipped cleaning, with the pixels at stars that are in this frame AND
in the session's reference left alone. A pixel the shipped rule would replace is kept when a reference star, moved
into this frame by the frame's own line-up, falls within 1.5 px of a star found in this frame: a star seen in two
frames is not a cosmic ray. Nothing else changes: a hit, a hot pixel and a one-frame source are judged by the shipped
rule as before. Each frame also gets 20 star-like sources planted in it alone (an asteroid's or a transient's case);
how much of their light the cleaning keeps is printed, against the shipped rule's.

Importing this replaces clip3.frame (the per-frame worker both pass-mark harnesses use)."""
import numpy as np

import clip
import clip3
import stacking

shipped_frame = clip3.frame


def persistent(x, reference, moved=(0.0, 0.0)):
    """Where this frame's stars that are also the reference's sit, as a 3 by 3 mask each."""
    lum = np.dstack([x, x, x]).sum(axis=2)
    stars = stacking.find_stars(lum)
    keep = np.zeros(x.shape, bool)
    if len(stars) < 20:
        return keep
    _, r, t, matched, _, flipped = stacking.line_up(np.dstack([x, x, x]), lum, stars, reference, moved)
    if not stacking.lined_up(matched):
        return keep
    h, w = x.shape
    ref = np.asarray(reference["stars"])[:, :2]
    p = (r.T @ (ref - t).T).T              # the reference's stars in this frame's (x, y)
    if flipped:
        p = np.column_stack([w - 1 - p[:, 0], h - 1 - p[:, 1]])
    own = stars[:, :2]
    for px, py in p:
        d = np.hypot(own[:, 0] - px, own[:, 1] - py)
        if d.size and d.min() <= 1.5:
            sx, sy = own[int(np.argmin(d))]
            rr, cc = int(round(sy)), int(round(sx))
            keep[max(0, rr - 1):rr + 2, max(0, cc - 1):cc + 2] = True
    return keep


def planted_kept(x, fix, keep, seed):
    """20 star-like sources (the frame's own star width) planted in this frame alone, at random places away from
    the edge: the share of their light the cleaning keeps, with the candidate's sparing and with none."""
    rng = np.random.default_rng(seed + 1000)
    stars = stacking.find_stars(x, limit=300)
    fw = float(np.median(stars[:, 3])) if len(stars) else 3.0
    top = float(np.percentile(stars[:, 2], 90)) if len(stars) else 1e5
    sig = fw / 2.355
    h, w = x.shape
    yy, xx = np.mgrid[-6:7, -6:7]
    y = x.copy(); spots = []
    for _ in range(20):
        r0, c0 = int(rng.integers(20, h - 20)), int(rng.integers(20, w - 20))
        dy, dx = rng.uniform(-0.5, 0.5, 2)
        psf = np.exp(-((yy - dy) ** 2 + (xx - dx) ** 2) / (2 * sig * sig)); psf *= top / psf.sum()
        y[r0 - 6:r0 + 7, c0 - 6:c0 + 7] += psf; spots.append((r0, c0, psf.sum()))
    def kept(img):
        return float(np.median([(img[a - 4:a + 5, b - 4:b + 5] - x[a - 4:a + 5, b - 4:b + 5]).sum() / s for a, b, s in spots]))
    plain = fix(y, np.zeros_like(x, bool))
    spared = plain.copy(); spared[keep] = y[keep]
    return kept(plain), kept(spared)


def frame(job):
    path, exposure, gain, reference, ys, xs, vs, plain_map, fixed_map, seed = job
    x = clip.base(path, exposure, gain)
    keep = persistent(x, reference, reference.get("moved", (0.0, 0.0)))
    from scipy import ndimage as N
    back = N.median_filter(x, 7)
    brightest = N.maximum_filter(x, footprint=clip.RING) - back
    keep &= (x - back) <= 2.0 * np.maximum(brightest, 1e-6)   # a star's shape, not a star with a hit on it
    shipped_fix = clip3.fix
    def fix(img, bad):
        out = shipped_fix(img, bad)
        out[keep] = img[keep]
        return out
    try:
        a, b = planted_kept(x, shipped_fix, keep, seed)
        print(f"frame {seed}: spared {int(keep.sum())} px; planted one-frame sources keep {a:.3f} shipped, {b:.3f} candidate", flush=True)
    except Exception as e:
        print(f"frame {seed}: planting failed {e!r}", flush=True)
    clip3.fix = fix
    try:
        return shipped_frame(job)
    finally:
        clip3.fix = shipped_fix


clip3.frame = frame
