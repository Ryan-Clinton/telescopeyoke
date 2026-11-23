#!/usr/bin/env python3
"""Training pairs from another observer's raw mono subs (docs/image-processing-spec.md, 5).

    ./externalpairs.py --lights DIR --dark F --bias F --flats DIR --name NAME --out DIR

Calibrates them with that observer's own masters, bins until the stars are
about our width in pixels, lines them up, and passes every pair through the
same checks as our own frames. Uses no camera and changes none of our data.
"""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy import ndimage

import stacking
import trainset

WORKERS = 4     # the GPU's training job needs the processor too
FULL_SCALE = 65535.0
WORST_WIDTH = 1.5   # a sub's stars this many times wider than the session's median are refused


def master(path):
    """A calibration master in the lights' counts; some tools keep them scaled 0 to 1."""
    data = fits.getdata(path).astype(np.float32)
    fill = float(np.nanmedian(data))
    data = np.where(np.isfinite(data), data, fill)
    return data * FULL_SCALE if np.percentile(data[::8, ::8], 99.9) <= 1.0 else data


def binned(x, by):
    h, w = x.shape[0] // by, x.shape[1] // by
    return x[:h * by, :w * by].reshape(h, by, w, by).mean(axis=(1, 3)).astype(np.float32)


def calibrated(path, dark, flat, by):
    return binned((fits.getdata(path).astype(np.float32) - dark) / flat, by)


def one(job):
    """Worker: a sub lined up in one file, and where the sensor saw it in another."""
    path, dark_file, flat_file, by, reference, store, sensor, slot, count, shape = job
    x = calibrated(path, np.load(dark_file, mmap_mode="r"), np.load(flat_file, mmap_mode="r"), by)
    stars = stacking.find_stars(x)
    moved, r, t, matched, residual, flipped = stacking.line_up(x[..., None], x, stars, reference)
    frames = np.memmap(store, dtype=np.float32, mode="r+", shape=(count, *shape, 1))
    frames[slot] = stacking.warp(moved, r, t)
    frames.flush()
    d = x - ndimage.median_filter(x, size=9)
    noise = 1.4826 * np.median(np.abs(d[::3, ::3]))
    d[ndimage.binary_dilation(np.abs(d) > 3.5 * noise, iterations=3)] = np.nan
    seen = np.memmap(sensor, dtype=np.float32, mode="r+", shape=(count, *shape))
    seen[slot] = d / noise
    seen.flush()
    good = len(stars) >= 8 and stacking.lined_up(matched) and residual is not None and residual <= stacking.FLIP_RESIDUAL
    wide = stars[stars[:, 4] > 0.6, 3] if len(stars) else np.array([])
    return {"file": Path(path).name, "good": bool(good), "matched": matched, "residual": residual,
            "fwhm": float(np.median(wide)) if len(wide) else 99.0,
            "place": (float(np.degrees(np.arctan2(r[1, 0], r[0, 0]))), [float(t[0]), float(t[1])], bool(flipped))}


def build(args, say=print):
    out = Path(args.out)
    folder = out / args.name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    lights = sorted(Path(args.lights).glob("*.fit*"))
    dark, bias = master(args.dark), master(args.bias)
    heads = [fits.getheader(p) for p in lights]
    provenance = {"exposures": sorted({float(h.get("EXPOSURE", h.get("EXPTIME", 0))) for h in heads}),
                  "filters": sorted({str(h.get("FILTER")) for h in heads}), "gains": sorted({h.get("GAIN") for h in heads}),
                  "sensor_temperature": [float(min(h["CCD-TEMP"] for h in heads)), float(max(h["CCD-TEMP"] for h in heads))],
                  "dark": Path(args.dark).name, "bias": Path(args.bias).name, "flats": len(list(Path(args.flats).glob("*.fit*"))),
                  "camera": str(heads[0].get("INSTRUME")), "pixel_um": heads[0].get("XPIXSZ"), "focal_mm": heads[0].get("FOCALLEN")}
    if len(provenance["filters"]) != 1 or provenance["filters"][0] != args.band or len(provenance["exposures"]) != 1:
        raise SystemExit(f"these subs are not one filter and exposure: {provenance}")
    flat = np.median([fits.getdata(p).astype(np.float32) - bias for p in sorted(Path(args.flats).glob("*.fit*"))], axis=0)
    flat = (flat / np.median(flat)).astype(np.float32)
    flat[flat < 0.2] = 1
    dark_file, flat_file = out / f"{args.name}-dark.npy", out / f"{args.name}-flat.npy"
    np.save(dark_file, dark)
    np.save(flat_file, flat)
    widths = []
    for path in lights[:: max(1, len(lights) // 9)]:
        x = calibrated(path, dark, flat, 1)
        found = stacking.find_stars(x)
        found = found[found[:, 4] > 0.6, 3]
        widths.append((float(np.median(found)) if len(found) >= 20 else 99.0, str(path)))
    width = float(np.median([w for w, _ in widths]))
    first = calibrated(min(widths)[1], dark, flat, 1)
    by = max(1, int(round(width / 4)))
    reference_image = binned(first, by)
    reference = {"square": stacking.centre_square(reference_image), "stars": stacking.find_stars(reference_image)}
    shape = reference_image.shape
    say(f"{len(lights)} subs; stars {width:.1f} px, binned {by}x to {shape[1]}x{shape[0]}")
    store, sensor_file = out / f"{args.name}-frames.dat", out / f"{args.name}-sensor.dat"
    np.memmap(store, dtype=np.float32, mode="w+", shape=(len(lights), *shape, 1)).flush()
    np.memmap(sensor_file, dtype=np.float32, mode="w+", shape=(len(lights), *shape)).flush()
    try:
        jobs = [(str(p), str(dark_file), str(flat_file), by, reference, str(store), str(sensor_file), i,
                 (len(lights), *shape)) for i, p in enumerate(lights)]
        with stacking.worker_pool(WORKERS) as pool:
            done = list(pool.map(one_slot, jobs))
        typical = float(np.median([d["fwhm"] for d in done if d["good"]]))
        for d in done:
            if d["good"] and d["fwhm"] > WORST_WIDTH * typical:
                d["good"] = False
                d["why"] = f"stars {d['fwhm']:.1f} px against {typical:.1f}"
        keep = [i for i, d in enumerate(done) if d["good"]]
        if len(keep) < 8:
            raise SystemExit(f"only {len(keep)} subs lined up")
        frames = np.memmap(store, dtype=np.float32, mode="r", shape=(len(lights), *shape, 1))
        all_seen = np.memmap(sensor_file, dtype=np.float32, mode="r", shape=(len(lights), *shape))
        seen = all_seen[keep]
        places = [done[i]["place"] for i in keep]
        shifts = np.array([p[1] for p in places])
        dither = float(np.median(np.hypot(*(shifts - np.median(shifts, axis=0)).T)))
        if dither < trainset.MIN_DITHER:
            raise SystemExit(f"median dither {dither:.1f} px is too small")
        sample = frames[keep, ::4, ::4, 0]
        middle = np.nanmedian(sample, axis=0)
        levels = {f: float(np.nanmedian(sample[k] - middle)) for k, f in enumerate(keep)}
        fwhm = [done[i]["fwhm"] for i in keep]
        parts, checks = [], []
        for k, kind in enumerate(trainset.SPLITS):
            made, shared, agree = trainset.pair(frames, keep, fwhm, kind, 1000 + k, levels, seen, places, store)
            checks.append({"split": k, "kind": kind, "sensor_correlation": round(float(shared), 5), "halves": agree,
                           "kept": made is not None})
            if made is None:
                continue
            x, y, s, valid, unit, nx, ny = made
            part = folder / f"split{k}"
            part.mkdir()
            for label, data in zip(trainset.FILES, (x, y, s, valid)):
                np.save(part / f"{label}.npy", data)
            (part / "meta.json").write_text(json.dumps({"kind": kind, "unit": unit, "input": nx, "target": ny,
                                                        "sensor_correlation": shared, "halves": agree}))
            parts.append(part.name)
        record = {"name": args.name, "target": args.name, "role": "train", "filter": args.band,
                  "frames": len(keep), "subs": len(lights), "binned": by, "dither": round(dither, 1), "splits": len(parts),
                  "parts": parts, "checks": checks, "credit": args.credit, "provenance": provenance,
                  "frames_refused": [{k: d.get(k) for k in ("file", "matched", "residual", "why")}
                                     for d in done if not d["good"]]}
        (folder / "done.json").write_text(json.dumps(record))
        index = out / "index.json"
        kept = [r for r in json.loads(index.read_text()) if r["name"] != args.name] if index.exists() else []
        index.write_text(json.dumps([*kept, record], indent=1))
        say(json.dumps({k: v for k, v in record.items() if k != "frames_refused"}))
        say(f"{len(keep)} of {len(lights)} subs used; {len(parts)} of {len(trainset.SPLITS)} pairs passed")
    finally:
        for f in (store, sensor_file, dark_file, flat_file):
            f.unlink(missing_ok=True)


def one_slot(job):
    path, dark, flat, by, reference, store, sensor, slot, shape = job
    return one((path, dark, flat, by, reference, store, sensor, slot, shape[0], shape[1:]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("lights", "dark", "bias", "flats", "name", "out", "band", "credit"):
        ap.add_argument(f"--{name}", required=True)
    build(ap.parse_args())


if __name__ == "__main__":
    main()
