#!/usr/bin/env python3
"""Make the best picture possible from a session's saved raw frames.

    ./restack.py M27                    the newest M27 session
    ./restack.py frames/M27/20261003-231500
    ./restack.py M27 --keep 0.8         use only the best 80% of the good frames
    ./restack.py M27 --profile          also report where the time went

shoot.py stacks as it goes so there is something to watch. This goes back
over every raw frame with the whole session known: it measures them all
quickly, drops the poor ones, prepares the rest in full and lines them up on
the sharpest frame, weights the better frames more, and averages with
outliers (satellites, aircraft, cosmic rays) clipped out. Then it removes the
sky gradient and writes a finished picture. The frame-by-frame work is shared
between the processor's cores.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

import interface
import process
import stacking

ROOT = Path(__file__).parent


def find_session(name):
    path = Path(name)
    if path.is_dir():
        return path
    sessions = sorted((ROOT / "frames" / name.replace(" ", "")).glob("*/"))
    if not sessions:
        raise interface.Refusal("NO_SESSION", f"No saved session for {name}. shoot.py keeps "
                                f"raw frames in frames/{name}/<date-time>/.")
    return sessions[-1]


def select(frames, keep=0.85):
    """Frames worth stacking, best first: the ones that pass the checks
    against the session as a whole, then the best `keep` fraction of those."""
    usable = [f for f in frames if f["stars"] >= 8]
    if not usable:
        return []
    # Judge against the better half of the session, not its average: a
    # session that was half cloud should not set a cloudy standard.
    standard = stacking.baseline(usable)
    passed = [f for f in usable if stacking.judge(f, standard)[0]]
    # Sharp, round, with plenty of stars.
    passed.sort(key=lambda f: f["fwhm"] / max(f["roundness"], 0.1))
    return passed[:max(1, round(len(passed) * keep))]


def run(session, keep=0.85, say=print, workers=None, profile=False):
    session = Path(session)
    lights = sorted(session.glob("light-*.fits"))
    if not lights:
        raise SystemExit(f"No raw frames in {session}.")
    began = time.perf_counter()
    timings = stacking.Timings()
    _, header = stacking.load_light(lights[0])
    exposure, gain = float(header.get("EXPTIME", 0)), int(float(header.get("GAIN", 0)))
    calibration = stacking.Calibration(exposure, gain)
    workers = workers or stacking.cores()
    say(f"{session}: {len(lights)} raw frames, {exposure:g} s at gain {gain}; "
        f"calibration: {calibration.describe()}; {workers} workers")

    work = session / "registered.dat"
    with stacking.worker_pool(workers) as pool:
        # First pass, every frame, cheaply: is it worth stacking?
        frames = []
        for q, spent in pool.map(stacking.measure_file, [str(p) for p in lights],
                                 [exposure] * len(lights), [gain] * len(lights)):
            frames.append(q)
            timings.add(spent)
        chosen = select(frames, keep)
        if not chosen:
            raise SystemExit("No frame had enough stars to stack.")
        best = chosen[0]
        say(f"{len(chosen)} of {len(frames)} frames kept; best FWHM {best['fwhm']:.1f}, "
            f"typical {np.median([f['fwhm'] for f in chosen]):.1f}")

        # Second pass, the kept frames only, in full: line everything up on
        # the sharpest frame. The results go into one file shared between the
        # workers, so memory holds a frame per worker and not the whole run.
        with timings.phase("calibrate and clean"):
            mosaic, _ = stacking.load_light(session / best["file"])
            rgb = stacking.prepare(mosaic, calibration)
            lum = rgb.sum(axis=2)
        reference = {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}
        shape = (len(chosen), *rgb.shape)
        np.memmap(work, dtype=np.float16, mode="w+", shape=shape).flush()
        try:
            n = len(chosen)
            results = pool.map(stacking.register_file, [str(session / f["file"]) for f in chosen],
                               [exposure] * n, [gain] * n, [reference] * n, [str(work)] * n,
                               range(n), [shape] * n)
            residuals = []
            for f, (info, spent) in zip(chosen, results):
                f.update(info)
                timings.add(spent)
                if info["residual"] is not None:
                    residuals.append(info["residual"])
            weights = [stacking.weight(f, best) for f in chosen]

            registered = np.memmap(work, dtype=np.float16, mode="r", shape=shape)
            with timings.phase("stack"):
                first = stacking.Stack(rgb.shape, after=10 ** 9)   # no clipping yet
                for i in range(n):
                    first.add(registered[i].astype(np.float32), weights[i])
                # Now that the average and its spread are known, leave out
                # whatever strays too far from them.
                final = stacking.Stack(rgb.shape)
                final.reference = (first.mean(), first.spread())
                for i in range(n):
                    final.add(registered[i].astype(np.float32), weights[i])
            del registered
        finally:
            work.unlink(missing_ok=True)

    stacked = final.result()
    total = exposure * len(chosen)
    with timings.phase("finish the picture"):
        stacking.write_stack(session / "final.fits", stacked,
                             {"EXPTIME": total, "NFRAMES": len(chosen), "GAIN": gain})
        name = session.parent.name
        image = Image.fromarray(process.process(stacked))
        (ROOT / "web").mkdir(exist_ok=True)
        image.save(session / "final.jpg", quality=93)
        image.save(ROOT / "web" / f"{name}-final.jpg", quality=93)
    (session / "restack.json").write_text(json.dumps(
        {"kept": [f["file"] for f in chosen], "frames": frames,
         "summary": {"captured": len(frames), "stacked": len(chosen),
                     "left_out": len(frames) - len(chosen), "total_exposure_s": total,
                     "median_residual_px": round(float(np.median(residuals)), 3) if residuals else None,
                     "seconds": round(time.perf_counter() - began, 1),
                     "picture": str(session / "final.jpg"), "stack": str(session / "final.fits")}},
        indent=1))
    say(f"{len(frames)} captured, {len(chosen)} stacked, {len(frames) - len(chosen)} left out; "
        f"total exposure {total:.0f} s")
    if residuals:
        # If this creeps up towards a pixel, rotation and shift are no longer
        # enough and the alignment needs to allow for scale or distortion.
        say(f"alignment: stars matched to {np.median(residuals):.2f} pixel (worst frame "
            f"{max(residuals):.2f})")
    say(f"saved {session / 'final.fits'}, final.jpg and web/{name}-final.jpg")
    if profile:
        say("Where the time went (work is summed over the workers):")
        say(timings.report(time.perf_counter() - began))
    return session / "final.jpg"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", help="object name (newest session) or a session folder")
    ap.add_argument("--keep", type=float, default=0.85,
                    help="fraction of the good frames to stack, best first")
    ap.add_argument("--workers", type=int,
                    help="worker processes (default: one per processor core)")
    ap.add_argument("--profile", action="store_true", help="report where the time went")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()

    def work():
        session = find_session(args.session)
        run(session, args.keep, workers=args.workers, profile=args.profile)
        return json.loads((session / "restack.json").read_text())["summary"]

    interface.main("restack", work, args.json)


if __name__ == "__main__":
    main()
