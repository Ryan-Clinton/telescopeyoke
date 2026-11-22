"""How much of the sensor-fixed pattern survives alignment into the two halves?"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, ".")
import numpy as np
from scipy import ndimage as N

import stacking

SESSIONS = ("NGC2174/20261120-014420", "NGC281/20261119-204929", "IC405/20261122-001737", "M33/20261105-001232")


def fine(x):
    return x - N.median_filter(x, size=9)


def detector(job):
    path, exposure, gain = job
    mosaic, header = stacking.load_light(Path(path))
    x = stacking.prepare(mosaic, stacking._calibration(exposure, gain, stacking.worker_cards(header)),
                         mono=True)[..., 0].astype(np.float32)
    d = fine(x)
    s = 1.4826 * np.median(np.abs(d[::3, ::3]))
    d[N.binary_dilation(np.abs(d) > 3.5 * s, iterations=3)] = np.nan
    return d / s


def carried(job):
    """This frame's half of the pattern, and unit noise, moved as the frame was."""
    path, exposure, gain, reference, pattern, seed = job
    mosaic, header = stacking.load_light(Path(path))
    rgb = stacking.prepare(mosaic, stacking._calibration(exposure, gain, stacking.worker_cards(header)), mono=True)
    lum = rgb.sum(axis=2)
    stars = stacking.find_stars(lum)
    noise = np.random.default_rng(seed).standard_normal(pattern.shape, dtype=np.float32)
    both = np.dstack([pattern, noise])
    moved, r, t, matched, _, _ = stacking.line_up(both, lum, stars, reference, reference.get("moved", (0.0, 0.0)))
    if not stacking.lined_up(matched):
        return None
    out = stacking.warp(moved, r, t)
    return out[..., 0].astype(np.float32), out[..., 1].astype(np.float32)


def check(name, pool):
    found = stacking.one_setting(stacking.on_target(sorted((Path("frames") / name).glob("light-*.fits")),
                                                    lambda *_: None), lambda *_: None)
    found = found[:: max(1, len(found) // 32)][:32]
    _, header = stacking.load_light(found[0])
    exposure, gain = float(header["EXPTIME"]), int(float(header["GAIN"]))
    maps = pool.map(detector, [(str(p), exposure, gain) for p in found])
    a = np.nan_to_num(np.nanmean(np.stack(maps[::2]), axis=0))
    b = np.nan_to_num(np.nanmean(np.stack(maps[1::2]), axis=0))
    same = float(np.mean((a - a.mean()) * (b - b.mean())))
    best = None
    for p in found[::4]:
        mosaic, head = stacking.load_light(p)
        lum = stacking.prepare(mosaic, stacking.Calibration(exposure, gain, head), mono=True).sum(axis=2)
        stars = stacking.find_stars(lum)
        score = len(stars) / max(float(np.median(stars[:, 3])), .1) if len(stars) else 0
        if best is None or score > best[0]:
            best = score, lum, stars
    _, lum, stars = best
    reference = {"square": stacking.centre_square(lum), "stars": stars}
    jobs = [(str(p), exposure, gain, reference, (a if i % 2 == 0 else b), i) for i, p in enumerate(found)]
    out = pool.map(carried, jobs)
    pa = [o for i, o in enumerate(out) if o is not None and i % 2 == 0]
    pb = [o for i, o in enumerate(out) if o is not None and i % 2 == 1]
    half = lambda group, k: np.nan_to_num(np.nanmean(np.stack([o[k] for o in group]), axis=0))[80:-80, 80:-80]
    A, B = half(pa, 0), half(pb, 0)
    noise = half(pa, 1)
    A, B, noise = fine(A), fine(B), fine(noise)
    shared = float(np.mean((A - A.mean()) * (B - B.mean())))
    grain = float(noise.var())
    return {"session": name, "filter": str(header.get("FILTER")), "frames": len(pa) + len(pb),
            "unaligned_pattern_over_noise": round((max(same, 0) * len(maps) / 2) ** .5, 2),
            "aligned_pattern_over_noise": round((max(shared, 0) / grain) ** .5, 3),
            "predicted_half_correlation": round(shared / (shared + grain), 4)}


if __name__ == "__main__":
    with Pool(6) as pool:
        for name in SESSIONS:
            try:
                print(json.dumps(check(name, pool)), flush=True)
            except Exception as e:
                print(json.dumps({"session": name, "error": repr(e)[:300]}), flush=True)
