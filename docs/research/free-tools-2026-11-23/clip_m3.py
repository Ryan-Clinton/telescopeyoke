"""clip.measure with one change, fixed before any re-scoring: a star whose centre is a lone spike in the uncleaned stack (the measure's own lone-spike test) is left out (with no dark, fixed hot pixels survive the stack and were measured as stars)."""
import numpy as np
from scipy import ndimage as N
import stacking
from clip import RING, NAMES


def measure(stacks):
    ref = stacks["none"]
    stars = stacking.find_stars(ref, limit=300)
    if len(stars):   # measure 3: a real star, not a hot pixel the dark did not take (the lone-spike test below, at its centre)
        z = np.nan_to_num(ref); local = N.median_filter(z, 3); s = 1.4826 * np.median(np.abs(z - local)) + 1e-6
        second = N.rank_filter(z, rank=-2, footprint=RING) - N.median_filter(z, 7)
        spike = (z - local > 8 * s) & (second < 3 * s)
        near = N.maximum_filter(spike, size=3)
        ys, xs = np.clip(np.round(stars[:, 1]).astype(int), 0, z.shape[0] - 1), np.clip(np.round(stars[:, 0]).astype(int), 0, z.shape[1] - 1)
        stars = stars[~near[ys, xs]]
    if len(stars) < 20:
        return {}
    fw = float(np.median(stars[:, 3]))
    r = max(5, int(round(2.5 * fw)))
    far = np.hypot(*(stars[:, :2][:, None] - stars[:, :2][None]).transpose(2, 0, 1))
    np.fill_diagonal(far, 1e9)
    use = [(int(round(y)), int(round(x))) for (x, y), d in zip(stars[:, :2], far.min(axis=1))
           if d > 4 * r and 3 * r + 2 < x < ref.shape[1] - 3 * r - 2 and 3 * r + 2 < y < ref.shape[0] - 3 * r - 2]
    yy, xx = np.mgrid[-3 * r:3 * r + 1, -3 * r:3 * r + 1]
    rad = np.hypot(yy, xx)
    def one(im, a, b):
        p = im[a - 3 * r:a + 3 * r + 1, b - 3 * r:b + 3 * r + 1]
        p = p - np.nanmedian(p[(rad > 2 * r) & (rad <= 3 * r)])
        q = np.where(rad <= r, np.nan_to_num(p), 0)
        tot = q.sum()
        pos = np.maximum(q, 0)
        v = ((yy ** 2 + xx ** 2) * pos).sum() / max(pos.sum(), 1e-9) / 2
        return tot, float(np.nanmax(q)), 2.355 * v ** .5
    base_m = np.array([one(ref, a, b) for a, b in use])
    top = np.percentile(base_m[:, 1], 95)
    good = (base_m[:, 0] > 0) & (base_m[:, 1] < top)
    order = np.argsort(base_m[good, 1])
    out = {"stars": int(good.sum()), "aperture_px": r, "median_fwhm": round(fw, 2)}
    fine = lambda z: z - N.median_filter(z, 9)
    base_noise = 1.4826 * np.nanmedian(np.abs(fine(ref)[::3, ::3]))
    for name in ("current", "aware"):
        m = np.array([one(stacks[name], a, b) for a, b in use])[good]
        b = base_m[good]
        bits = {"all": np.arange(len(b)), "brightest_third": order[-len(order) // 3:]}
        for label, i in bits.items():
            out[f"{name}_{label}"] = {"flux": round(float(np.median(m[i, 0] / b[i, 0])), 4),
                                      "peak": round(float(np.median(m[i, 1] / b[i, 1])), 4),
                                      "width": round(float(np.median(m[i, 2] / b[i, 2])), 4)}
        out[f"{name}_grain"] = round(float(1.4826 * np.nanmedian(np.abs(fine(stacks[name])[::3, ::3])) / base_noise), 4)
    for name in NAMES:
        z = np.nan_to_num(stacks[name])
        local = N.median_filter(z, 3)
        s = 1.4826 * np.median(np.abs(z - local)) + 1e-6
        second = N.rank_filter(z, rank=-2, footprint=RING) - N.median_filter(z, 7)
        out[f"{name}_lone_spikes"] = int(((z - local > 8 * s) & (second < 3 * s)).sum())
    return out


