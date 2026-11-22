"""Stage B pilot: are a session's two halves independent enough to train on?"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, ".")
import numpy as np
from scipy import ndimage as N

import restack
import stacking

MOST = 40   # frames per session, so memory stays near 2 GB a session


def one(job):
    path, exposure, gain, reference = job
    mosaic, header = stacking.load_light(Path(path))
    rgb = stacking.prepare(mosaic, stacking._calibration(exposure, gain, stacking.worker_cards(header)),
                           mono=stacking.is_mono(header))
    lum = rgb.sum(axis=2)
    stars = stacking.find_stars(lum)
    raw = np.ascontiguousarray(rgb[..., :1])
    moved, r, t, matched, residual, flipped = stacking.line_up(raw, lum, stars, reference,
                                                               reference.get("moved", (0.0, 0.0)))
    warped = stacking.warp(moved, r, t)[..., 0].astype(np.float32)
    good = stacking.lined_up(matched)
    # Detector coordinates: sky only, each frame's stars and level taken out.
    d = raw[..., 0].astype(np.float32)
    small = N.zoom(d[::4, ::4], 0.25, order=1)
    big = N.zoom(N.median_filter(small, 9), np.array(d.shape) / np.array(small.shape), order=1)
    big = big[:d.shape[0], :d.shape[1]]
    d = d[:big.shape[0], :big.shape[1]] - big
    s = 1.4826 * np.median(np.abs(d[::4, ::4]))
    d[N.binary_dilation(d > 3 * s, iterations=4)] = np.nan
    return warped, d, [float(t[0]), float(t[1])], good


def high(x, sigma=4):
    x = np.nan_to_num(x)
    return x - N.gaussian_filter(x, sigma)


def rho(a, b, mask):
    a, b = a[mask], b[mask]
    return float(np.corrcoef(a[::3], b[::3])[0, 1])


def check(session, pool):
    found = stacking.one_setting(stacking.on_target(sorted(session.glob("light-*.fits")), lambda *_: None),
                                 lambda *_: None)
    _, header = stacking.load_light(found[0])
    exposure, gain = float(header["EXPTIME"]), int(float(header["GAIN"]))
    if getattr(stacking.Calibration(exposure, gain, header), "missing", ()):
        return None
    measured = pool.starmap(stacking.measure_file, [(str(p), exposure, gain) for p in found])
    frames = []
    for (q, _), p in zip(measured, found):
        q.update(path=str(p), exposure=exposure, scale=1.0)
        frames.append(q)
    chosen = restack.select(frames)[:MOST]
    if len(chosen) < 8:
        return None
    best = chosen[0]
    mosaic, head = stacking.load_light(Path(best["path"]))
    rgb = stacking.prepare(mosaic, stacking.Calibration(exposure, gain, head), mono=True)
    lum = rgb.sum(axis=2)
    reference = {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}
    out = pool.map(one, [(f["path"], exposure, gain, reference) for f in chosen])
    keep = [i for i, o in enumerate(out) if o[3]]
    order = sorted(keep, key=lambda i: chosen[i]["fwhm"])
    A, B = order[::2], order[1::2]
    cube = np.stack([out[i][0] for i in keep])
    middle = np.nanmedian(cube[:, ::2, ::2], axis=0)
    level = {i: float(np.nanmedian(out[i][0][::2, ::2] - middle)) for i in keep}
    half = lambda ids: np.nanmean(np.stack([out[i][0] - level[i] for i in ids]), axis=0)
    a, b = half(A), half(B)
    ha, hb = high(a), high(b)
    both = high((a + b) / 2)
    noise = 1.4826 * np.median(np.abs(both[::3, ::3]))
    star = both > 4 * noise
    sky = ~N.binary_dilation(star, iterations=6)
    ring = N.binary_dilation(star, iterations=9) & ~N.binary_dilation(star, iterations=4)
    edge = np.zeros_like(sky)
    edge[60:-60, 60:-60] = True
    da = np.nanmean(np.stack([out[i][1] for i in A]), axis=0)
    db = np.nanmean(np.stack([out[i][1] for i in B]), axis=0)
    fine = np.isfinite(da) & np.isfinite(db)
    fine[:60] = fine[-60:] = False
    fine[:, :60] = fine[:, -60:] = False
    hda, hdb = high(da), high(db)
    shifts = np.array([out[i][2] for i in keep])
    spread = np.hypot(*(shifts - np.median(shifts, axis=0)).T)
    drift = N.gaussian_filter(np.nan_to_num(a - b), 32)[60:-60, 60:-60]
    jumps = [abs(v) >= 3 for v in level.values()]
    return {"session": f"{session.parent.name}/{session.name}", "filter": str(header.get("FILTER")),
            "seconds": exposure, "frames": len(keep),
            "sky_rho": round(rho(ha, hb, sky & edge), 3), "ring_rho": round(rho(ha, hb, ring & edge), 3),
            "detector_rho": round(rho(hda, hdb, fine), 3),
            "detector_fixed_over_half_noise": round(float(np.nanstd(((hda + hdb) / 2)[fine]) /
                                                          max(np.nanstd(((hda - hdb) / 2)[fine]), 1e-6)), 3),
            "level_jumps": int(sum(jumps)), "median_dither_px": round(float(np.median(spread)), 1),
            "half_difference_large_over_noise": round(float(drift.std() / max(noise, 1e-6)), 3)}


def pick():
    chosen, seen = [], set()
    root = Path("frames")
    sessions = [s for t in root.iterdir() if t.is_dir() for s in t.glob("202611*") if s.is_dir()]
    for s in sorted(sessions, key=lambda p: (-len(list(p.glob("light-*.fits"))), p.name)):
        files = sorted(s.glob("light-*.fits"))
        if len(files) < 12:
            continue
        h = stacking.fits.getheader(files[0], 1)
        band = str(h.get("FILTER"))
        if band not in ("Ha", "OIII", "SII", "L") or (s.parent.name, band) in seen:
            continue
        if sum(k[1] == band for k in seen) >= 3:
            continue
        seen.add((s.parent.name, band))
        chosen.append(s)
    order = {"Ha": 0, "OIII": 1, "SII": 2, "L": 3}
    chosen.sort(key=lambda s: order[str(stacking.fits.getheader(next(s.glob("light-*.fits")), 1).get("FILTER"))])
    return chosen[:8]


if __name__ == "__main__":
    with Pool(8) as pool:
        for s in pick():
            try:
                print(json.dumps(check(s, pool)), flush=True)
            except Exception as e:
                print(json.dumps({"session": str(s), "error": repr(e)[:300]}), flush=True)
