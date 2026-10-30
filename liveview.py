#!/usr/bin/env python3
"""Show what the telescope sees now: a fresh frame on the web page every few
seconds, with nothing stacked or saved.

    ./liveview.py                  a 1 s frame every 10 s for an hour
    ./liveview.py --every 5 --exposure 0.5 --minutes 20

Use it between imaging runs: while slewing by hand, checking cloud, or just
to watch. It stops by itself when shoot.py starts a run, since the two cannot
share the camera. A run that cloud has stopped starts it as it goes, so that
the page carries on showing the sky and the cloud can be seen to clear.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

import activity
import skywatch
import snap
from camera import Camera, luminance

import config

ROOT = Path(__file__).parent


def run_active(since=0.0, seconds=45):
    """True if an imaging run has logged a frame in the last while, and
    since `since`: a run that cloud has just ended, and that started this
    live view as it went, is not one to give way to."""
    logs = list((config.DATA / "frames").glob("*/*/frames.jsonl"))
    return any(p.stat().st_mtime > since and time.time() - p.stat().st_mtime < seconds for p in logs)


# The activity lines of a lucky-imaging video that has the camera; stacking
# one does not use it.
VIDEO = ("Taking a lucky-imaging video", "Imaging the Moon")


def video_active():
    """Whether a lucky-imaging video (lucky.py, ./ty moon) has the camera:
    it keeps no frames.jsonl for run_active to see."""
    return any(e.get("what") in VIDEO for e in activity.now())


HOLD_EVERY = 20       # seconds between looks at where the Moon has drifted to
HOLD_WITHIN = 0.10    # a drift under this share of the disc's radius is left alone


def last_moon_aim():
    """Where on the Moon the newest Moon video was centred (its notes' aim,
    arcminutes east and north), or the Moon's middle."""
    import lucky
    for notes in sorted(Path(lucky.OUT).glob("Moon-*.json"), reverse=True):
        try:
            return [float(v) for v in json.loads(notes.read_text(encoding="utf-8"))["aim"]]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return [0.0, 0.0]


def hold_moon(scope, site, aim, matrix, mosaic, say=print):
    """The lunar hold for the live view: the mount tracks the stars and the
    Moon drifts about its own width an hour against them, so the disc is
    found in the frame and, once it has drifted, the mount is moved back by
    the picture's measured directions (moon.py's calibration). Returns the aim."""
    import lucky
    import lunar
    image = lucky.green(mosaic)
    disc = lunar.find_disc(image)
    if disc is None:
        return aim
    down, right = lunar.offset(disc, image.shape)
    if np.hypot(down, right) <= HOLD_WITHIN * disc["r"]:
        return aim
    east, north = lunar.correction(matrix, down, right)
    aim = [aim[0] + east, aim[1] + north]
    scope.goto_target("Moon", site, aim_off=tuple(aim))
    say(f"{time.strftime('%H:%M:%S')}  Moon re-centred: {down:+.0f} px down, {right:+.0f} px right; "
        f"aim {aim[0]:+.1f}' east, {aim[1]:+.1f}' north")
    return aim


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--every", type=float, default=10, help="seconds between frames")
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--gain", type=int, default=2000)
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--after-run", action="store_true",
                    help="started by a run as it ended: give way only to a run that logs a frame from now on")
    ap.add_argument("--hold-moon", action="store_true",
                    help="keep the Moon in the middle, moving the mount back as it drifts "
                         "(needs the picture's directions, measured by ./ty moon on this side of the pier)")
    args = ap.parse_args()

    end = time.monotonic() + args.minutes * 60
    began_at = time.time() if args.after_run else 0.0
    scope = site = matrix = aim = None
    if args.hold_moon:
        import mount
        import moon
        scope = mount.Mount(watch=False)
        site = config.load()["site"]
        matrix = moon.load_calibration("west" if scope.west() else "east")
        if matrix is None:
            raise SystemExit("No measured picture directions for this side of the pier: run ./ty moon once first.")
        aim = last_moon_aim()
    held = time.monotonic()
    with Camera(gain=args.gain) as cam, activity.doing("Live view", f"{args.exposure:g} s every {args.every:g} s"):
        while time.monotonic() < end:
            if run_active(began_at) or video_active():
                print("An imaging run has started; live view stopping.")
                return
            began = time.monotonic()
            mosaic, _ = cam.frame(args.exposure)
            stars = skywatch.count_stars(luminance(mosaic))
            seen = f"{stars} stars" if stars >= 8 else "no stars (cloud?)"
            snap.publish(mosaic, kind="live view", quick=True,
                         detail=f"{args.exposure:g} s · {seen}")
            print(f"{time.strftime('%H:%M:%S')}  {seen}", flush=True)
            if scope is not None and time.monotonic() - held >= HOLD_EVERY:
                aim, held = hold_moon(scope, site, aim, matrix, mosaic), time.monotonic()
            time.sleep(max(0, args.every - (time.monotonic() - began)))


if __name__ == "__main__":
    main()
