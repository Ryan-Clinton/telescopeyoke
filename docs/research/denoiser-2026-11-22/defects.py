"""Stage B: how large a planted sensor defect would reach the aligned training pair?"""
import json, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, ".")
import numpy as np
from scipy import ndimage as N
import stacking
SESSIONS = ("NGC281/20261119-204929", "M33/20261105-001232", "NGC281/20261104-232332")
def fine(x): return x - N.median_filter(x, size=9)
def where(job):
    path, exposure, gain, reference = job
    mosaic, header = stacking.load_light(Path(path))
    rgb = stacking.prepare(mosaic, stacking._calibration(exposure, gain, stacking.worker_cards(header)), mono=True)
    lum = rgb.sum(axis=2)
    _, r, t, matched, _, flipped = stacking.line_up(rgb[..., :1], lum, stacking.find_stars(lum), reference)
    return (r, t, flipped) if stacking.lined_up(matched) else None
def moved(p, place):
    r, t, flipped = place
    q = p[::-1, ::-1] if flipped else p
    return np.nan_to_num(stacking.warp(np.ascontiguousarray(q[..., None]), r, t)[..., 0])
def check(name, pool):
    found = stacking.one_setting(stacking.on_target(sorted((Path("../data/frames") / name).glob("light-*.fits")), lambda *_: None), lambda *_: None)
    found = found[:: max(1, len(found) // 32)][:32]
    _, h = stacking.load_light(found[0]); e, g = float(h["EXPTIME"]), int(float(h["GAIN"]))
    m, head = stacking.load_light(found[len(found) // 2])
    lum = stacking.prepare(m, stacking.Calibration(e, g, head), mono=True).sum(axis=2)
    ref = {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}
    places = [p for p in pool.map(where, [(str(f), e, g, ref) for f in found]) if p is not None]
    H, W = lum.shape; rng = np.random.default_rng(3)
    unit = lambda a: (a / a.std()).astype(np.float32)
    makers = {"hot/dark pixels": lambda: unit(rng.standard_normal((H, W))),
              "rows": lambda: unit(np.repeat(rng.standard_normal((H, 1)), W, 1)),
              "columns": lambda: unit(np.repeat(rng.standard_normal((1, W)), H, 0)),
              "flat mottling": lambda: unit(N.gaussian_filter(rng.standard_normal((H, W)), 1.5))}
    white = lambda: rng.standard_normal((H, W), dtype=np.float32)
    A, B = places[::2], places[1::2]
    half = lambda ps, pat=None: np.mean([moved(pat if pat is not None else white(), q) for q in ps], axis=0)[80:-80, 80:-80]
    grain = float(half(A).var()); out = {"session": name, "frames": len(places)}
    for k, make in makers.items():
        c = []
        for _ in range(6):
            pat = make(); a, b = half(A, pat), half(B, pat); c.append(float(np.mean((a - a.mean()) * (b - b.mean()))) / grain)
        mean, se = float(np.mean(c)), float(np.std(c, ddof=1) / np.sqrt(len(c)))
        real = mean - 2 * se > 0
        out[k] = {"shared_per_unit": round(mean, 4), "uncertainty": round(se, 4), "detected": real,
                  "smallest_defect_for_0.02": round((0.0204 / mean) ** .5, 2) if real else None}
    return out
if __name__ == "__main__":
    with Pool(8) as pool:
        for s in SESSIONS: print(json.dumps(check(s, pool)), flush=True)
