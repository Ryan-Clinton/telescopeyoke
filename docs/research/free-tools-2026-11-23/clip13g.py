"""The pair-aware candidate (clip12) and today's cleaning, both stacked as restack.py stacks: every frame judged against
the median of all of them (stacking.robust_reference, as restack does for 5 to 40 frames), then averaged.

clip4 to clip12 stacked every layer with a single running average, which cannot judge the first 8 frames, so a
cosmic ray there always reached the stack, for both cleanings; restack never stacks that way. The pass mark is
unchanged and was fixed before clip8: brightest-third flux within 0.5%, peak within 1%, grain within 1%, fixed
defects left no worse than today's, visible cosmic pixels at most today's plus 10. Copies only.
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, ".")
import numpy as np
from scipy import ndimage as N

import clip
import clip3
import clip12  # noqa: F401  sets clip3.fix to the pair-aware candidate
import stacking


def guarded(middle):
    """The map as stacking.defect_map makes it: a pixel whose third-brightest neighbour stands out too is a star
    that did not move between frames, and is left (deviation 7: the harness had no such guard)."""
    third = N.rank_filter(middle, rank=-3, footprint=clip.RING)
    return (middle > 5) & (third < np.maximum(0.2 * middle, 3))


def restacked(cube):
    n = len(cube)
    final = stacking.Stack(cube[0].shape)
    if 5 <= n <= 40:
        final.reference = stacking.robust_reference(cube, n, [True] * n)
    else:
        first = stacking.Stack(cube[0].shape, after=10 ** 9)
        for f in cube:
            first.add(f.astype(np.float32))
        final.reference = (first.mean(), first.spread())
    for f in cube:
        final.add(f.astype(np.float32))
    return final.result()


def check(name, pool):
    files = sorted((clip.WORK / "input" / name.replace("/", "-")).glob("light-*.fits"))
    _, header = stacking.load_light(files[0])
    exposure, gain = float(header["EXPTIME"]), int(float(header["GAIN"]))
    first = clip.base(files[0], exposure, gain)
    h, w = first.shape
    rng = np.random.default_rng(7)
    ys, xs = rng.integers(3, h - 3, 600), rng.integers(3, w - 3, 600)
    vs = rng.choice((10., 30., 100.), 600).astype(np.float32)
    ys, xs, vs = np.r_[ys, ys[::3], ys[::6]], np.r_[xs, xs[::3] + 1, xs[::6] - 1], np.r_[vs, vs[::3], vs[::6]]
    got = pool.map(clip3.scores, [(str(p), exposure, gain, ys, xs, vs) for p in files])
    plain_map, fixed_map = (guarded(np.median(np.stack([g[i] for g in got]), axis=0)) for i in (0, 1))
    del got
    best = None
    for p in files[::4]:
        x = clip.current(clip.base(p, exposure, gain))
        lum = np.dstack([x, x, x]).sum(axis=2)
        stars = stacking.find_stars(lum)
        value = len(stars) / max(float(np.median(stars[:, 3])), .1) if len(stars) else 0
        if best is None or value > best[0]:
            best = value, lum, stars
    reference = {"square": stacking.centre_square(best[1]), "stars": best[2]}
    jobs = [(str(p), exposure, gain, reference, ys, xs, vs, plain_map, fixed_map, i) for i, p in enumerate(files)]
    cubes, energy = [[] for _ in range(9)], 0.0
    for out in pool.imap(clip3.frame, jobs, chunksize=1):
        if out is None:
            continue
        out, e = out
        for i in range(9):
            cubes[i].append(out[..., i].astype(np.float16))
        energy += e
    used = len(cubes[0])
    result = []
    for i in range(9):
        result.append(restacked(cubes[i]))
        cubes[i] = None
    none, now, plain, none_fixed, now_fixed, plain_fixed, none_cosmic, now_cosmic, plain_cosmic = result
    real = {k.replace("aware", "robust"): v for k, v in clip.measure({"none": none, "current": now, "aware": plain}).items()}
    sigma = 1.4826 * np.median(np.abs((first - N.median_filter(first, 3))[::2, ::2]))
    share = lambda a, b, total: round(float(np.maximum(a - b, 0).sum() / total), 4)
    fixed_total, cosmic_total = float(vs.sum() * sigma), energy / used

    def honest(a, b, total):
        d = np.nan_to_num(a - b)
        grain = 1.4826 * np.median(np.abs(np.nan_to_num(b - N.median_filter(np.nan_to_num(b), 9))[::3, ::3])) + 1e-6
        return {"signed": round(float(d.sum() / total), 4), "visible": int((d > 5 * grain).sum())}
    return {"session": name, "filter": str(header.get("FILTER")), "frames": used, "rejected_share": 0.0, "real": real,
            "left": {"current": {"fixed": share(now_fixed, now, fixed_total), "cosmic": share(now_cosmic, now, cosmic_total)},
                     "robust": {"fixed": share(plain_fixed, plain, fixed_total), "cosmic": share(plain_cosmic, plain, cosmic_total)}},
            "honest": {"current": {"fixed": honest(now_fixed, now, fixed_total), "cosmic": honest(now_cosmic, now, cosmic_total)},
                       "robust": {"fixed": honest(plain_fixed, plain, fixed_total), "cosmic": honest(plain_cosmic, plain, cosmic_total)}}}


if __name__ == "__main__":
    with Pool(3) as pool, open(clip.WORK / "clip13g.jsonl", "a") as log:
        for name in clip12.SESSIONS:
            try:
                row = check(name, pool)
            except Exception as e:
                row = {"session": name, "error": repr(e)[:400]}
            log.write(json.dumps(row) + "\n")
            log.flush()
            c = row.get("honest", {})
            print(name, "cosmic visible", c.get("robust", {}).get("cosmic"), "against", c.get("current", {}).get("cosmic"),
                  row.get("error", ""), flush=True)
