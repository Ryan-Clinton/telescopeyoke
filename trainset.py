#!/usr/bin/env python3
"""Training pairs for the denoiser (docs/image-processing-spec.md, section 5).

    ./trainset.py build --out DIR     every 183M session with 8 or more frames

Each session's frames are lined up once and split into independent halves.
The two sides of a pair share the sky and not the noise, which is what a
Noise2Noise network learns from. Reads frames only; uses no camera.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
from pathlib import Path

import astropy
import numpy as np
import scipy
from scipy import ndimage

import config
import restack
import stacking

HELD_OUT = ("NGC2174", "IC405")     # never trained on: the final judgement
CHECKING = ("M106",)                # watched during training, to stop it in time
MOST_FRAMES = 120
MIN_DITHER = 10.0                   # pixels: below this a sensor pattern survives alignment (22 November 2026)
SPLITS = ("1:1", "1:1", "1:3", "1:3")
MAX_SHARED = 0.02                   # correlation a sensor pattern may add to a pair; refused above it
FILES = ("x", "y", "s", "valid")


def role(target):
    return "test" if target in HELD_OUT else "check" if target in CHECKING else "train"


def sessions():
    found = []
    for folder in sorted((config.DATA / "frames").glob("*/2026*")):
        lights = sorted(folder.glob("light-*.fits"))
        if len(lights) >= 8 and str(stacking.fits.getheader(lights[0], 1).get("INSTRUME")) == "183m":
            found.append(folder)
    return found


def session_lights(session):
    return stacking.one_setting(stacking.on_target(sorted(session.glob("light-*.fits")), lambda *_: None),
                                lambda *_: None)


def stamp(path):
    info = Path(path).stat()
    return [Path(path).name, info.st_size, info.st_mtime_ns]


def manifest(session):
    """Everything a session's pairs were made from. Files are told apart by
    name, size and time, which rsync keeps: hashing 25 GB for each build would
    take longer than most of the build. The code that makes pairs is hashed."""
    lights = session_lights(session)
    _, header = stacking.load_light(lights[0])
    masters = getattr(stacking.Calibration(float(header["EXPTIME"]), int(float(header["GAIN"])), header), "masters", {})
    folder = stacking.library(str(header.get("INSTRUME")))
    code = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
            for name in ("trainset.py", "stacking.py", "restack.py")}
    return {"frames": [stamp(p) for p in lights],
            "masters": {kind: stamp(folder / name) for kind, name in sorted(masters.items())},
            "code": code, "commit": os.environ.get("TY_CODE_COMMIT"),
            "settings": {"most_frames": MOST_FRAMES, "min_dither": MIN_DITHER, "splits": SPLITS, "first_seed": 1000,
                         "max_shared": MAX_SHARED},
            "software": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                         "astropy": astropy.__version__}}


def fingerprint(record):
    """One value for all a session's inputs: any change rebuilds its pairs."""
    inputs = {k: v for k, v in record.items() if k != "commit"}     # a commit elsewhere changes nothing here
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def still_good(folder, wanted):
    """A kept session, if it was made from exactly these inputs and its files are all there."""
    try:
        record = json.loads((folder / "done.json").read_text())
    except (OSError, ValueError):
        return None
    if record.get("fingerprint") != wanted:
        return None
    for name in record.get("parts", []):
        if not all((folder / name / f"{k}.npy").exists() for k in FILES) or not (folder / name / "meta.json").exists():
            return None
    return record if record.get("parts") else None


def sensor_frame(job):
    """Worker: one calibrated frame where the sensor saw it, fine detail only,
    in units of its own noise, with its stars left out."""
    path, exposure, gain, store, slot, shape = job
    mosaic, header = stacking.load_light(Path(path))
    x = stacking.prepare(mosaic, stacking._calibration(exposure, gain, stacking.worker_cards(header)),
                         mono=True)[..., 0].astype(np.float32)
    d = x - ndimage.median_filter(x, size=9)
    noise = 1.4826 * np.median(np.abs(d[::3, ::3]))
    d[ndimage.binary_dilation(np.abs(d) > 3.5 * noise, iterations=3)] = np.nan
    frames = np.memmap(store, dtype=np.float32, mode="r+", shape=shape)
    frames[slot] = d / noise
    frames.flush()


def carried(job):
    """Worker: a pattern, and white noise, moved as these frames were; their sums and counts."""
    pattern_file, places, seed = job
    pattern = np.load(pattern_file)
    rng = np.random.default_rng(seed)
    total, grain, count = None, None, None
    for rotation, shift, flipped in places:
        angle = np.radians(rotation)
        r = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        both = np.dstack([pattern, rng.standard_normal(pattern.shape, dtype=np.float32)])
        if flipped:
            both = np.ascontiguousarray(both[::-1, ::-1])
        moved = stacking.warp(both, r, np.array(shift))
        seen = np.isfinite(moved[..., 0])
        if total is None:
            total, grain, count = (np.zeros(pattern.shape, np.float32) for _ in range(3))
        total += np.where(seen, moved[..., 0], 0)
        grain += np.where(seen, moved[..., 1], 0)
        count += seen
    return total, grain, count


def carried_mean(pool, pattern_file, places, seed):
    chunks = [places[i::8] for i in range(8) if places[i::8]]
    parts = list(pool.map(carried, [(pattern_file, c, seed + i) for i, c in enumerate(chunks)]))
    total, grain, count = (sum(p[k] for p in parts) for k in range(3))
    use = count >= 0.6 * len(places)
    return total / np.maximum(count, 1), grain / np.maximum(count, 1), use


def shared_by(sensor, first, second, places, work):
    """How much a pattern fixed to the sensor correlates this pair's two halves
    once each frame is moved as it really was. Each half's pattern comes from
    its own frames, so their noise cannot agree by itself."""
    a = np.nan_to_num(np.nanmean(sensor[first], axis=0)).astype(np.float32)
    b = np.nan_to_num(np.nanmean(sensor[second], axis=0)).astype(np.float32)
    files = [work.with_name(f"{work.stem}-{k}.npy") for k in "ab"]
    np.save(files[0], a)
    np.save(files[1], b)
    try:
        with stacking.worker_pool() as pool:
            pa, ga, ua = carried_mean(pool, str(files[0]), [places[i] for i in first], 11)
            pb, _, ub = carried_mean(pool, str(files[1]), [places[i] for i in second], 111)
    finally:
        for f in files:
            f.unlink(missing_ok=True)
    use = ua & ub
    use[:80] = use[-80:] = False
    use[:, :80] = use[:, -80:] = False
    together = float(np.mean((pa[use] - pa[use].mean()) * (pb[use] - pb[use].mean())))
    grain = float(ga[use].var())
    return together / max(max(together, 0) + grain, 1e-9)


def register(session, work):
    """The session's best frames, lined up: (frames, FWHMs, header, dither,
    how each frame was moved, its file)."""
    lights = session_lights(session)
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
    places = [(done[i][0]["rotation"], done[i][0]["shift"], done[i][0]["flipped"]) for i in good]
    return store, good, [chosen[i]["fwhm"] for i in good], header, dither, places, [chosen[i]["path"] for i in good]


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
        if len(ids) >= 5:
            centre = np.nanmedian(block, axis=0)
            spread = 1.4826 * (1 + 5 / (len(ids) - 1)) * np.nanmedian(np.abs(block - centre), axis=0)
            block[np.abs(block - centre) > 4 * spread + 0.25 * np.abs(centre)] = np.nan
        mean[start:start + 128] = np.nanmean(block, axis=0)
        scatter[start:start + 128] = np.nanstd(block, axis=0)
        count[start:start + 128] = np.isfinite(block).sum(axis=0)
    return mean, scatter, count


def pair(store, frames, fwhm, kind, seed, levels, sensor, places, work):
    rng = np.random.default_rng(seed)
    first, second = split(fwhm, kind, rng)
    shared = shared_by(sensor, first, second, places, work)
    if shared > MAX_SHARED:
        return None, shared
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
    return (x / unit, y / unit, np.maximum(s, 0.5).astype(np.float32), valid, unit, len(ids_x), len(ids_y)), shared


def build(out, say=print):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for session in sessions():
        name = f"{session.parent.name}-{session.name}"
        folder = out / name
        try:
            inputs = manifest(session)
            wanted = fingerprint(inputs)
        except Exception as problem:
            say(f"{name} left out: {problem}")
            continue
        kept = still_good(folder, wanted)
        if kept:
            made.append(kept)
            continue
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
        work = out / "registering.dat"
        sensor_file = out / "sensor.dat"
        try:
            store, frames, fwhm, header, dither, places, paths = register(session, work)
            if role(session.parent.name) == "train" and dither < MIN_DITHER:
                raise ValueError(f"median dither {dither:.0f} px is too small")
            sample = store[frames, ::4, ::4, 0]
            middle = np.nanmedian(sample, axis=0)
            levels = {f: float(np.nanmedian(sample[k] - middle)) for k, f in enumerate(frames)}
            shape = (len(paths), *store.shape[1:3])
            np.memmap(sensor_file, dtype=np.float32, mode="w+", shape=shape).flush()
            exposure, gain = float(header["EXPTIME"]), int(float(header["GAIN"]))
            with stacking.worker_pool() as pool:
                list(pool.map(sensor_frame, [(p, exposure, gain, str(sensor_file), i, shape)
                                             for i, p in enumerate(paths)]))
            sensor = np.memmap(sensor_file, dtype=np.float32, mode="r", shape=shape)
            kinds = SPLITS if role(session.parent.name) == "train" else ("1:3",)
            parts, measured = [], []
            for k, kind in enumerate(kinds):
                made_pair, shared = pair(store, frames, fwhm, kind, 1000 + k, levels, sensor, places, work)
                measured.append({"split": k, "kind": kind, "sensor_correlation": round(shared, 5),
                                 "kept": made_pair is not None})
                if made_pair is None:
                    continue
                x, y, s, valid, unit, nx, ny = made_pair
                part = folder / f"split{k}"
                part.mkdir()
                for label, data in zip(FILES, (x, y, s, valid)):
                    np.save(part / f"{label}.npy", data)
                (part / "meta.json").write_text(json.dumps({"kind": kind, "unit": unit, "input": nx, "target": ny,
                                                            "sensor_correlation": shared}))
                parts.append(part.name)
            if not parts:
                raise ValueError(f"every pair shares a sensor pattern ({measured[0]['sensor_correlation']:.3f} or more)")
            record = {"name": name, "target": session.parent.name, "role": role(session.parent.name),
                      "filter": str(header.get("FILTER")), "seconds": float(header["EXPTIME"]),
                      "frames": len(frames), "dither": round(dither, 1), "splits": len(parts), "parts": parts,
                      "checks": measured, "fingerprint": wanted, "manifest": inputs}
            (folder / "done.json").write_text(json.dumps(record))
            made.append(record)
            say(json.dumps({k: v for k, v in record.items() if k not in ("manifest", "fingerprint")}))
        except Exception as problem:
            shutil.rmtree(folder, ignore_errors=True)
            say(f"{name} left out: {problem}")
        finally:
            work.unlink(missing_ok=True)
            sensor_file.unlink(missing_ok=True)
    summary = [{k: v for k, v in r.items() if k != "manifest"} for r in made]
    (out / "index.json").write_text(json.dumps(summary, indent=1))
    say(f"{len(made)} sessions in {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["build"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
