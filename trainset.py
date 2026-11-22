#!/usr/bin/env python3
"""Training pairs for the denoiser (docs/image-processing-spec.md, section 5).

    ./trainset.py build --out DIR     every 183M session with 8 or more frames

Each session's frames are lined up once and split into independent halves.
The two sides of a pair share the sky and not the noise, which is what a
Noise2Noise network learns from. Reads frames only; uses no camera.
"""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from scipy import ndimage

import config
import restack
import stacking

HELD_OUT = ("NGC2174", "IC405")     # never trained on: the final judgement
CHECKING = ("M106",)                # watched during training, to stop it in time
MOST_FRAMES = 120
MIN_DITHER = 10.0                   # pixels: below this a sensor pattern survives alignment (22 November 2026)
SPLITS = ("1:1", "1:1", "1:3", "1:3")


def role(target):
    return "test" if target in HELD_OUT else "check" if target in CHECKING else "train"


def sessions():
    found = []
    for folder in sorted((config.DATA / "frames").glob("*/2026*")):
        lights = sorted(folder.glob("light-*.fits"))
        if len(lights) >= 8 and str(stacking.fits.getheader(lights[0], 1).get("INSTRUME")) == "183m":
            found.append(folder)
    return found


def register(session, work):
    """The session's best frames, lined up: (frames, FWHMs, header, dither)."""
    lights = stacking.one_setting(stacking.on_target(sorted(session.glob("light-*.fits")), lambda *_: None),
                                  lambda *_: None)
    _, header = stacking.load_light(lights[0])
    exposure, gain = float(header["EXPTIME"]), int(float(header["GAIN"]))
    if getattr(stacking.Calibration(exposure, gain, header), "missing", ()):
        raise ValueError("its masters are not all there")
    with stacking.worker_pool() as pool:
        measured = list(pool.map(stacking.measure_file, map(str, lights), [exposure] * len(lights),
                                 [gain] * len(lights)))
        frames = [dict(q, path=str(p), exposure=exposure, scale=1.0) for (q, _), p in zip(measured, lights)]
        chosen = restack.select(frames)
        if len(chosen) < 8:
            raise ValueError(f"only {len(chosen)} usable frames")
        best = chosen[0]
        chosen = chosen[:: max(1, len(chosen) // MOST_FRAMES)][:MOST_FRAMES]
        mosaic, head = stacking.load_light(Path(best["path"]))
        rgb = stacking.prepare(mosaic, stacking.Calibration(exposure, gain, head), mono=True)
        lum = rgb.sum(axis=2)
        reference = {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}
        shape = (len(chosen), *rgb.shape[:2], 1)
        np.memmap(work, dtype=np.float32, mode="w+", shape=shape).flush()
        n = len(chosen)
        done = list(pool.map(stacking.register_file, [f["path"] for f in chosen], [exposure] * n, [gain] * n,
                             [reference] * n, [str(work)] * n, range(n), [shape] * n, [1.0] * n))
    good = [i for i, (info, _) in enumerate(done) if stacking.lined_up(info["matched"])]
    if len(good) < 8:
        raise ValueError(f"only {len(good)} frames lined up")
    shifts = np.array([done[i][0]["shift"] for i in good])
    dither = float(np.median(np.hypot(*(shifts - np.median(shifts, axis=0)).T)))
    store = np.memmap(work, dtype=np.float32, mode="r", shape=shape)
    return store, good, [chosen[i]["fwhm"] for i in good], header, dither


def split(fwhm, kind, rng):
    """Two disjoint sets of frames with matching star shapes."""
    order = np.argsort(fwhm)
    first, second = [], []
    for start in range(0, len(order), 4):
        block = rng.permutation(order[start:start + 4]).tolist()
        cut = len(block) // 2 if kind == "1:1" else 1
        first += block[:cut]
        second += block[cut:]
    return first, second


def mean_of(store, ids, levels):
    """A half's own clipped mean, its scatter, and how many frames reached each pixel."""
    shape = store.shape[1:3]
    mean, scatter, count = (np.empty(shape, np.float32) for _ in range(3))
    for start in range(0, shape[0], 128):
        block = np.stack([np.asarray(store[i, start:start + 128, :, 0], np.float32) - levels[i] for i in ids])
        block[block == -levels[ids[0]]] = np.nan
        if len(ids) >= 5:
            centre = np.nanmedian(block, axis=0)
            spread = 1.4826 * (1 + 5 / (len(ids) - 1)) * np.nanmedian(np.abs(block - centre), axis=0)
            block[np.abs(block - centre) > 4 * spread + 0.25 * np.abs(centre)] = np.nan
        mean[start:start + 128] = np.nanmean(block, axis=0)
        scatter[start:start + 128] = np.nanstd(block, axis=0)
        count[start:start + 128] = np.isfinite(block).sum(axis=0)
    return mean, scatter, count


def pair(store, frames, fwhm, kind, seed, levels):
    rng = np.random.default_rng(seed)
    first, second = split(fwhm, kind, rng)
    ids_x, ids_y = [frames[i] for i in first], [frames[i] for i in second]
    x, scatter, nx = mean_of(store, ids_x, levels)
    y, _, ny = mean_of(store, ids_y, levels)
    valid = (nx >= max(1, 0.6 * len(ids_x))) & (ny >= max(1, 0.6 * len(ids_y)))
    valid = ndimage.binary_erosion(valid, iterations=8, border_value=0)
    if valid.mean() < 0.3:
        raise ValueError("too little of the field is shared")
    x, y = x - np.nanmedian(x[valid]), y - np.nanmedian(y[valid])
    x, y = np.nan_to_num(x), np.nan_to_num(y)
    fine = (x - ndimage.gaussian_filter(x, 2))[valid][::3]
    unit = 1.4826 * float(np.median(np.abs(fine - np.median(fine))))
    if len(ids_x) >= 4:
        s = ndimage.median_filter(np.nan_to_num(scatter) / np.sqrt(np.maximum(nx, 1)), size=5) / unit
    else:
        s = np.ones_like(x)
    return x / unit, y / unit, np.maximum(s, 0.5).astype(np.float32), valid, unit, len(ids_x), len(ids_y)


def build(out, say=print):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for session in sessions():
        name = f"{session.parent.name}-{session.name}"
        folder = out / name
        if (folder / "done.json").exists():
            made.append(json.loads((folder / "done.json").read_text()))
            continue
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
        work = out / "registering.dat"
        try:
            store, frames, fwhm, header, dither = register(session, work)
            sample = store[frames, ::4, ::4, 0]
            sample = np.where(sample == 0, np.nan, sample)
            middle = np.nanmedian(sample, axis=0)
            levels = {f: float(np.nanmedian(sample[k] - middle)) for k, f in enumerate(frames)}
            kinds = SPLITS if role(session.parent.name) == "train" else ("1:3",)
            if role(session.parent.name) == "train" and dither < MIN_DITHER:
                raise ValueError(f"median dither {dither:.0f} px is too small")
            for k, kind in enumerate(kinds):
                x, y, s, valid, unit, nx, ny = pair(store, frames, fwhm, kind, 1000 + k, levels)
                part = folder / f"split{k}"
                part.mkdir()
                for label, data in (("x", x), ("y", y), ("s", s), ("valid", valid)):
                    np.save(part / f"{label}.npy", data)
                (part / "meta.json").write_text(json.dumps({"kind": kind, "unit": unit, "input": nx, "target": ny}))
            record = {"name": name, "target": session.parent.name, "role": role(session.parent.name),
                      "filter": str(header.get("FILTER")), "seconds": float(header["EXPTIME"]),
                      "frames": len(frames), "dither": round(dither, 1), "splits": len(kinds)}
            (folder / "done.json").write_text(json.dumps(record))
            made.append(record)
            say(json.dumps(record))
        except Exception as problem:
            shutil.rmtree(folder, ignore_errors=True)
            say(f"{name} left out: {problem}")
        finally:
            work.unlink(missing_ok=True)
    (out / "index.json").write_text(json.dumps(made, indent=1))
    say(f"{len(made)} sessions in {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["build"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
