#!/usr/bin/env python3
"""How many new stars the whole discovery pipeline finds: fakes planted in
the raw frames, before anything else touches them.

    ./plant.py frames/M31/20261014-021118 --reference frames/M31/20261013-232632
    ./plant.py NEW --reference REF --count 300 --workers 14
    ./plant.py NEW --reference REF --json

depth.py and difference.py --plant put their fakes into a finished stack,
which tests only the last step. This puts them into a copy of every raw
frame of the NEW session, where a real nova would be: the same star, at the
same place on the sky, at the same brightness, in every frame. The copy then
goes through the pipeline as a real night would: calibration, the quality
checks, lining up, stacking (restack.py), and proper subtraction of the
reference (difference.py). The share of the fakes found at each brightness
is the discovery completeness, and the candidates that were not planted are
the false ones a real night would bring.

Each frame is plate-solved to place the fakes on it. A fake is round, as
wide as that frame's own stars, and grey: the same light in red, green and
blue. Its brightness is set from the reference's zero point against Gaia
(depth.py must have measured the reference), unfiltered and calibrated
approximately to Gaia G. The planted copy is made under
frames/NAME-planted/, and its raw frames are deleted afterwards; the stack,
the candidates and plant.json, which lists every fake and whether it was
found, are kept. It takes a plate solve per frame and a full restack: run it
on the desktop. Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import math
import shutil
import time
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy.spatial import cKDTree

import config
import depth
import difference
import interface
import stacking
from camera import luminance

MAGNITUDES = tuple(np.arange(15.0, 19.51, 0.5))   # fakes from easy to hopeless
FOUND_WITHIN = 2.5     # pixels on the reference between a fake and the candidate that is it
SPREAD = 30            # pixels kept between fakes, so no two blend


def choose(ref, ref_wcs, count, seed=1):
    """Where the fakes go, as (ra, dec, magnitude): on the reference's usable
    area (both edges and bright stars avoided), never close to each other."""
    rng = np.random.default_rng(seed)
    usable = difference.usable_area(ref, ref)
    xy = depth.places(ref.shape, count * 3, rng, edge=difference.EDGE + 20, apart=SPREAD)
    xy = xy[usable[np.rint(xy[:, 1]).astype(int), np.rint(xy[:, 0]).astype(int)]][:count]
    ra, dec = ref_wcs.pixel_to_world_values(xy[:, 0], xy[:, 1])
    mags = rng.choice(MAGNITUDES, len(xy))
    return np.column_stack([ra, dec, mags])


def add_to_mosaic(mosaic, xy, flux, fwhm):
    """A copy of a raw RGGB frame with grey round stars added. Positions and
    width are in the half-size pixels the pipeline works in; `flux` is in
    the stack's units, the sum over its red, green and blue planes. A grey
    star puts the same amount in each of a colour cell's four pixels, and the
    pipeline's colour image counts red, the mean of the two greens, and
    blue: three of the four, so each pixel takes a third of the cell's
    share."""
    out = mosaic.astype(np.float32)
    s = max(fwhm, 1.5) / 2.355
    r = int(4 * s) + 2
    h, w = mosaic.shape[0] // 2, mosaic.shape[1] // 2
    for (x, y), f in zip(xy, flux):
        ix, iy = int(round(x)), int(round(y))
        if not (r <= ix < w - r and r <= iy < h - r):
            continue
        yy, xx = np.mgrid[iy - r:iy + r + 1, ix - r:ix + r + 1]
        star = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * s * s))
        cell = f * star / star.sum() / 3
        block = np.repeat(np.repeat(cell, 2, axis=0), 2, axis=1)
        out[2 * (iy - r):2 * (iy + r + 1), 2 * (ix - r):2 * (ix + r + 1)] += block
    return np.clip(np.rint(out), 0, 65535).astype(mosaic.dtype)


def plant_frame(source, target, fakes, zeropoint, fwhm, hint):
    """Worker: one raw frame, plate-solved, with the fakes added where they
    fall on it, written to `target`. Returns (frame name, how many landed,
    or None if it would not solve)."""
    import solve
    mosaic, header = stacking.load_light(Path(source))
    lum = luminance(mosaic)
    found = solve.solve(lum, *hint, radius=3)
    if not found or "cd" not in found:
        shutil.copyfile(source, target)     # left as it was: it will not line up either
        return Path(source).name, None
    wcs = depth.wcs_from(found, lum.shape)
    x, y = wcs.world_to_pixel_values(fakes[:, 0], fakes[:, 1])
    flux = 10 ** (-0.4 * (fakes[:, 2] - zeropoint))
    planted = add_to_mosaic(mosaic, np.column_stack([x, y]), flux, fwhm)
    stacking.save_light(Path(target).parent, int(Path(target).stem.split("-")[1]), planted, header)
    inside = (x > 0) & (y > 0) & (x < lum.shape[1]) & (y < lum.shape[0])
    return Path(source).name, int(inside.sum())


def score(fakes, ref_wcs, candidates):
    """Which fakes became candidates, and which candidates are not fakes."""
    x, y = ref_wcs.world_to_pixel_values(fakes[:, 0], fakes[:, 1])
    spots = np.column_stack([x, y])
    found = np.zeros(len(fakes), bool)
    claimed = np.zeros(len(candidates), bool)
    if candidates:
        tree = cKDTree([[c["x"], c["y"]] for c in candidates])
        d, i = tree.query(spots, distance_upper_bound=FOUND_WITHIN)
        found = np.isfinite(d)
        claimed[i[found]] = True
    rows, shares = [], []
    for m in MAGNITUDES:
        at = fakes[:, 2] == m
        share = float(found[at].mean()) if at.sum() >= 3 else None
        shares.append(share)
        rows.append({"mag": float(m), "planted": int(at.sum()), "found": int(found[at].sum()),
                     "share": None if share is None else round(share, 3)})
    return {"curve": rows, "mag_50": depth.crossing(MAGNITUDES, shares, 0.5),
            "mag_90": depth.crossing(MAGNITUDES, shares, 0.9),
            "false_candidates": int((~claimed).sum()), "found": found.tolist()}


def run(args, say=print):
    if config.DEMO:
        raise interface.Refusal("DEMO_UNSUPPORTED", "Planting needs a real session and Gaia.")
    import mount
    import restack
    started = time.monotonic()
    session = restack.find_session(args.new)
    ref_path = depth.find_stack(args.reference)
    record_of_ref = depth.record_path(ref_path)
    if not record_of_ref.exists():
        raise interface.Refusal("INVALID_REQUEST", f"Measure the reference first: ./depth.py {ref_path}")
    zeropoint = json.loads(record_of_ref.read_text(encoding="utf-8"))["zeropoint"]
    name = args.near or session.parent.name
    ref = depth.brightness(fits.getdata(ref_path))
    ref_wcs = depth.plate(ref, name)
    fakes = choose(ref, ref_wcs, args.count, args.seed)
    target = mount.find_target(name)
    lights = sorted(session.glob("light-*.fits"))
    # Each frame's star width, from the quality pass if it has run.
    quality = session / "restack.json"
    log = ({Path(f.get("file", f.get("path", ""))).name: f
            for f in json.loads(quality.read_text(encoding="utf-8")).get("frames", [])}
           if quality.exists() else {})
    copy = config.DATA / "frames" / f"{session.parent.name}-planted" / session.name
    if copy.exists():
        shutil.rmtree(copy)
    copy.mkdir(parents=True)
    say(f"{len(fakes)} fakes, G {MAGNITUDES[0]:g} to {MAGNITUDES[-1]:g}, into {len(lights)} raw frames "
        f"of {session}; the reference is {ref_path} (zero point {zeropoint:.2f})")
    widths = [log.get(p.name, {}).get("fwhm") or 5.0 for p in lights]
    with stacking.worker_pool(args.workers) as pool:
        done = list(pool.map(plant_frame, [str(p) for p in lights], [str(copy / p.name) for p in lights],
                             [fakes] * len(lights), [zeropoint] * len(lights), widths,
                             [(target["ra"], target["dec"])] * len(lights)))
    unsolved = [n for n, landed in done if landed is None]
    say(f"planted in {len(lights) - len(unsolved)} frames ({len(unsolved)} would not solve and went in "
        "unchanged)")
    stacked = restack.run(copy, workers=args.workers, say=lambda line: say("  " + line))
    new_stack = copy / "final.fits"
    new = depth.brightness(fits.getdata(new_stack))
    new_wcs = depth.plate(new, name)
    record, _ = difference.subtract(new, ref, new_wcs, ref_wcs, zeropoint)
    result = score(fakes, ref_wcs, record["candidates"])
    for f in copy.glob("light-*.fits"):
        f.unlink()      # several GB; the stack and the records are what is kept
    summary = {"new": str(session), "reference": str(ref_path), "planted_copy": str(copy),
               "fakes": [{"ra": round(float(a), 6), "dec": round(float(d), 6), "mag": float(m), "found": hit}
                         for (a, d, m), hit in zip(fakes, result.pop("found"))],
               "frames": len(lights), "unsolved": unsolved, "zeropoint": zeropoint,
               "band": "unfiltered, calibrated approximately to Gaia G",
               "candidates": len(record["candidates"]), "fading_peaks": record["fading_peaks"],
               "seconds": round(time.monotonic() - started), **result}
    (copy / "plant.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    say(f"found through the whole pipeline: half to G {result['mag_50']}, 90% to G {result['mag_90']}; "
        f"{result['false_candidates']} candidates that were not planted")
    for row in result["curve"]:
        say(f"  G {row['mag']:4.1f}: {row['found']:3d} of {row['planted']:3d}")
    say(f"kept as {copy / 'plant.json'}")
    del stacked
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("new", help="the session to plant into: an object (its newest session) or a session folder")
    ap.add_argument("--reference", required=True, help="the reference stack: an object, a session folder or a FITS file")
    ap.add_argument("--count", type=int, default=300, help="how many fakes (default 300)")
    ap.add_argument("--seed", type=int, default=1, help="where they go: the same seed, the same places")
    ap.add_argument("--workers", type=int, help="worker processes (default: one per core)")
    ap.add_argument("--near", help="the object to plate-solve near, if the folder does not say")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("plant", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
