#!/usr/bin/env python3
"""Make the best picture possible from a session's saved raw frames.

    ./restack.py M27                    the newest M27 session
    ./restack.py frames/M27/20261003-231500
    ./restack.py M27 --keep 0.8         use only the best 80% of the good frames

shoot.py stacks as it goes so there is something to watch. This goes back
over every raw frame with the whole session known: it measures them all,
drops the poor ones, lines the rest up on the sharpest frame, weights the
better frames more, and averages with outliers (satellites, aircraft, cosmic
rays) clipped out. Then it removes the sky gradient and writes a finished
picture.
"""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

import process
import stacking

ROOT = Path(__file__).parent


def find_session(name):
    path = Path(name)
    if path.is_dir():
        return path
    sessions = sorted((ROOT / "frames" / name.replace(" ", "")).glob("*/"))
    if not sessions:
        raise SystemExit(f"No saved session for {name}. shoot.py keeps raw frames in "
                         f"frames/{name}/<date-time>/.")
    return sessions[-1]


def measure(session, calibration, say=print):
    """Quality of every raw frame in the session, as a list of dicts."""
    frames = []
    for path in sorted(session.glob("light-*.fits")):
        mosaic, _ = stacking.load_light(path)
        lum = stacking.prepare(mosaic, calibration).sum(axis=2)
        q = stacking.quality(lum, stacking.find_stars(lum))
        q["file"] = path.name
        frames.append(q)
    return frames


def select(frames, keep=0.85):
    """Frames worth stacking, best first: the ones that pass the checks
    against the session as a whole, then the best `keep` fraction of those."""
    usable = [f for f in frames if f["stars"] >= 8]
    passed = [f for f in usable if stacking.judge(f, usable)[0]]
    # Sharp, round, with plenty of stars.
    passed.sort(key=lambda f: f["fwhm"] / max(f["roundness"], 0.1))
    return passed[:max(1, round(len(passed) * keep))]


def run(session, keep=0.85, say=print):
    session = Path(session)
    lights = sorted(session.glob("light-*.fits"))
    if not lights:
        raise SystemExit(f"No raw frames in {session}.")
    _, header = stacking.load_light(lights[0])
    exposure, gain = float(header.get("EXPTIME", 0)), int(float(header.get("GAIN", 0)))
    calibration = stacking.Calibration(exposure, gain)
    say(f"{session}: {len(lights)} raw frames, {exposure:g} s at gain {gain}; "
        f"calibration: {calibration.describe()}")

    frames = measure(session, calibration, say)
    chosen = select(frames, keep)
    if not chosen:
        raise SystemExit("No frame had enough stars to stack.")
    best = chosen[0]
    say(f"{len(chosen)} of {len(frames)} frames kept; best FWHM {best['fwhm']:.1f}, "
        f"typical {np.median([f['fwhm'] for f in chosen]):.1f}")

    def prepared(name):
        mosaic, _ = stacking.load_light(session / name)
        rgb = stacking.prepare(mosaic, calibration)
        return rgb, rgb.sum(axis=2)

    # Line everything up on the sharpest frame, keeping the results on disk
    # so that memory holds only one frame at a time.
    rgb, lum = prepared(best["file"])
    reference = {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}
    work = session / "registered"
    work.mkdir(exist_ok=True)
    weights = {}
    try:
        first = stacking.Stack(rgb.shape, after=10 ** 9)   # no clipping yet
        for f in chosen:
            rgb, lum = prepared(f["file"])
            registered, _ = stacking.register(rgb, lum, stacking.find_stars(lum), reference)
            weights[f["file"]] = stacking.weight(f, best)
            np.save(work / (f["file"] + ".npy"), registered.astype(np.float16))
            first.add(registered, weights[f["file"]])
        # Second pass: now that the average and its spread are known, leave
        # out whatever strays too far from them.
        final = stacking.Stack(rgb.shape)
        final.reference = (first.mean(), first.spread())
        for f in chosen:
            registered = np.load(work / (f["file"] + ".npy")).astype(np.float32)
            final.add(registered, weights[f["file"]])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    stacked = final.result()
    total = exposure * len(chosen)
    stacking.write_stack(session / "final.fits", stacked,
                         {"EXPTIME": total, "NFRAMES": len(chosen), "GAIN": gain})
    name = session.parent.name
    image = Image.fromarray(process.process(stacked))
    (ROOT / "web").mkdir(exist_ok=True)
    image.save(session / "final.jpg", quality=93)
    image.save(ROOT / "web" / f"{name}-final.jpg", quality=93)
    (session / "restack.json").write_text(json.dumps(
        {"kept": [f["file"] for f in chosen], "frames": frames}, indent=1))
    say(f"{len(frames)} captured, {len(chosen)} stacked, {len(frames) - len(chosen)} left out; "
        f"total exposure {total:.0f} s")
    say(f"saved {session / 'final.fits'}, final.jpg and web/{name}-final.jpg")
    return session / "final.jpg"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", help="object name (newest session) or a session folder")
    ap.add_argument("--keep", type=float, default=0.85,
                    help="fraction of the good frames to stack, best first")
    args = ap.parse_args()
    run(find_session(args.session), args.keep)


if __name__ == "__main__":
    main()
