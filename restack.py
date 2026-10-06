#!/usr/bin/env python3
"""Make the best picture possible from a session's saved raw frames.

    ./restack.py M27                    the newest M27 session
    ./restack.py frames/M27/20261003-231500
    ./restack.py M27 --keep 0.8         use only the best 80% of the good frames
    ./restack.py M27 --profile          also report where the time went
    ./restack.py M27 --all              every M27 session as one picture
    ./restack.py frames/M27/A frames/M27/B    these sessions as one picture

shoot.py stacks as it goes so there is something to watch. This goes back
over every raw frame with the whole session known: it measures them all
quickly, drops the poor ones, prepares the rest in full and lines them up on
the sharpest frame, weights the better frames more, and averages with
outliers (satellites, aircraft, cosmic rays) clipped out. Then it removes the
sky gradient and writes a finished picture. The frame-by-frame work is shared
between the processor's cores.

Several sessions, from one night or many, can go into one picture, written
to frames/NAME/combined/. They may differ in exposure length but not in
gain, and the camera must not have been turned in the focuser between
them: frames that will not line up on the reference are left out. Frames
taken after the mount has swung to the other side of the meridian come out
upside down and are turned back automatically.
"""
import argparse
import json
import time
from pathlib import Path

import config

import numpy as np
from PIL import Image

import interface
import process
import stacking

ROOT = Path(__file__).parent
COMBINED = "combined"   # folder under frames/NAME/ for a picture made from several sessions
MIN_MATCHED = 8         # stars a frame must share with the reference to count as lined up


def find_session(name):
    path = Path(name)
    if path.is_dir():
        return path
    sessions = all_sessions(name)
    if not sessions:
        raise interface.Refusal("NO_SESSION", f"No saved session for {name}. shoot.py keeps "
                                f"raw frames in frames/{name}/<date-time>/.")
    return sessions[-1]


def all_sessions(name):
    """Every saved session of an object, oldest first."""
    folder = config.DATA / "frames" / stacking.folder_name(name)
    return sorted(p for p in folder.glob("*/") if p.name != COMBINED and any(p.glob("light-*.fits")))


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
    """Stack one session, or a list of sessions into one picture."""
    sessions = [Path(s) for s in session] if isinstance(session, (list, tuple)) else [Path(session)]
    several = len(sessions) > 1
    began = time.perf_counter()
    timings = stacking.Timings()
    workers = workers or stacking.cores()
    lights, exposures, gains = [], [], set()
    for one in sessions:
        found = sorted(one.glob("light-*.fits"))
        if not found:
            raise interface.Refusal("NO_SESSION", f"No raw frames in {one}.")
        _, header = stacking.load_light(found[0])
        seconds, gain = float(header.get("EXPTIME", 0)), int(float(header.get("GAIN", 0)))
        calibration = stacking.Calibration(seconds, gain)
        say(f"{one}: {len(found)} raw frames, {seconds:g} s at gain {gain}; "
            f"calibration: {calibration.describe()}")
        lights += found
        exposures += [seconds] * len(found)
        gains.add(gain)
    if len(gains) > 1:
        raise interface.Refusal("INVALID_REQUEST", "These sessions were taken at different gains "
                                f"({sorted(gains)}); they cannot go into one picture.")
    # Frames of other lengths are scaled to the first session's, so a 4 s
    # frame and a 2 s frame of the same star agree before they are averaged.
    exposure = exposures[0]
    scales = [exposure / e if e else 1.0 for e in exposures]
    session = sessions[0].parent / COMBINED if several else sessions[0]
    session.mkdir(exist_ok=True)
    say(f"{len(lights)} frames in all; {workers} workers")

    work = session / "registered.dat"
    with stacking.worker_pool(workers) as pool:
        # First pass, every frame, cheaply: is it worth stacking?
        frames = []
        measured = pool.map(stacking.measure_file, [str(p) for p in lights],
                            exposures, [gain] * len(lights))
        for (q, spent), path, seconds, scale in zip(measured, lights, exposures, scales):
            for key in ("flux", "background", "noise"):
                if q.get(key) is not None:
                    q[key] *= scale
            q.update(path=str(path), exposure=seconds, scale=scale)
            if several:
                q["file"] = f"{path.parent.name}/{path.name}"
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
            mosaic, _ = stacking.load_light(Path(best["path"]))
            rgb = stacking.prepare(mosaic, stacking.Calibration(best["exposure"], gain))
            lum = rgb.sum(axis=2)
        reference = {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}
        # Line up on the sharpest frame, but frame the picture where most of
        # the frames sat: the sharpest may be one that had drifted.
        moved = stacking.framing([f.get("spots", []) for f in chosen], best.get("spots", []))
        if moved is not None:
            reference["stars"] = reference["stars"].copy()
            reference["stars"][:, :2] += moved
            reference["moved"] = (float(moved[0]), float(moved[1]))
            say(f"framed where most frames sat, {np.hypot(*moved):.0f} pixels from the sharpest")
        for f in frames:
            f.pop("spots", None)    # not worth keeping in the session's record
        shape = (len(chosen), *rgb.shape)
        np.memmap(work, dtype=np.float16, mode="w+", shape=shape).flush()
        try:
            n = len(chosen)
            results = pool.map(stacking.register_file, [f["path"] for f in chosen],
                               [f["exposure"] for f in chosen], [gain] * n, [reference] * n,
                               [str(work)] * n, range(n), [shape] * n, [f["scale"] for f in chosen],
                               [several] * n)
            residuals = []
            for f, (info, spent) in zip(chosen, results):
                f.update(info)
                timings.add(spent)
                if info["residual"] is not None:
                    residuals.append(info["residual"])
            weights = [stacking.weight(f, best) for f in chosen]
            if several:
                # A frame from another session that found few of the reference's
                # stars has not lined up (the camera was turned, or it is a
                # different field); it would only smear the picture.
                turned = sum(f["flipped"] for f in chosen)
                if turned:
                    say(f"{turned} frames were taken on the other side of the meridian and "
                        "were turned the right way up")
                lost = [i for i, f in enumerate(chosen) if f["matched"] < MIN_MATCHED]
                for i in lost:
                    weights[i] = 0.0
                if lost:
                    say(f"{len(lost)} frames would not line up on the reference and were left out")
                if len(lost) == n - 1 and n > 1:
                    say("Nothing from the other sessions lined up: was the camera turned?")

            registered = np.memmap(work, dtype=np.float16, mode="r", shape=shape)
            with timings.phase("stack"):
                first = stacking.Stack(rgb.shape, after=10 ** 9)   # no clipping yet
                for i in range(n):
                    if weights[i]:
                        first.add(registered[i].astype(np.float32), weights[i])
                # Now that the average and its spread are known, leave out
                # whatever strays too far from them.
                final = stacking.Stack(rgb.shape)
                final.reference = (first.mean(), first.spread())
                for i in range(n):
                    if weights[i]:
                        final.add(registered[i].astype(np.float32), weights[i])
            del registered
        finally:
            work.unlink(missing_ok=True)

    stacked = final.result()
    chosen = [f for f, w in zip(chosen, weights) if w]
    total = sum(f["exposure"] for f in chosen)
    with timings.phase("finish the picture"):
        stacking.write_stack(session / "final.fits", stacked,
                             {"EXPTIME": total, "NFRAMES": len(chosen), "GAIN": gain})
        name = session.parent.name
        image = Image.fromarray(process.process(stacked, background=process.sky_for(name)))
        (config.DATA / "web").mkdir(exist_ok=True)
        image.save(session / "final.jpg", quality=93)
        image.save(config.DATA / "web" / f"{name}-final.jpg", quality=93)
    (session / "restack.json").write_text(json.dumps(
        {"kept": [f["file"] for f in chosen], "frames": frames,
         "summary": {"captured": len(frames), "stacked": len(chosen),
                     "left_out": len(frames) - len(chosen), "total_exposure_s": total,
                     "sessions": [str(s) for s in sessions],
                     "median_residual_px": round(float(np.median(residuals)), 3) if residuals else None,
                     "seconds": round(time.perf_counter() - began, 1),
                     "picture": str(session / "final.jpg"), "stack": str(session / "final.fits")}},
        indent=1), encoding="utf-8")
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
    ap.add_argument("session", nargs="+",
                    help="object name (newest session), or one or more session folders")
    ap.add_argument("--all", action="store_true",
                    help="with an object name: every saved session of it, as one picture")
    ap.add_argument("--keep", type=float, default=0.85,
                    help="fraction of the good frames to stack, best first")
    ap.add_argument("--workers", type=int,
                    help="worker processes (default: one per processor core)")
    ap.add_argument("--profile", action="store_true", help="report where the time went")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()

    def work():
        if args.all:
            sessions = all_sessions(args.session[0])
            if not sessions:
                raise interface.Refusal("NO_SESSION", f"No saved session for {args.session[0]}.")
        else:
            sessions = [find_session(name) for name in args.session]
        picture = run(sessions if len(sessions) > 1 else sessions[0], args.keep,
                      workers=args.workers, profile=args.profile)
        return json.loads((picture.parent / "restack.json").read_text(encoding="utf-8"))["summary"]

    interface.main("restack", work, args.json)


if __name__ == "__main__":
    main()
