#!/usr/bin/env python3
"""Show what the telescope sees now: a fresh frame on the web page every few
seconds, with nothing stacked or saved.

    ./liveview.py                  a 1 s frame every 10 s for an hour
    ./liveview.py --every 5 --exposure 0.5 --minutes 20

Use it between imaging runs: while slewing by hand, checking cloud, or just
to watch. It stops by itself when shoot.py starts a run, since the two cannot
share the camera.
"""
import argparse
import time
from pathlib import Path

import skywatch
import snap
from camera import Camera, luminance

ROOT = Path(__file__).parent


def run_active(seconds=45):
    """True if an imaging run has logged a frame in the last while."""
    logs = list((ROOT / "frames").glob("*/*/frames.jsonl"))
    return any(time.time() - p.stat().st_mtime < seconds for p in logs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--every", type=float, default=10, help="seconds between frames")
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--gain", type=int, default=2000)
    ap.add_argument("--minutes", type=float, default=60)
    args = ap.parse_args()

    end = time.monotonic() + args.minutes * 60
    with Camera(gain=args.gain) as cam:
        while time.monotonic() < end:
            if run_active():
                print("An imaging run has started; live view stopping.")
                return
            began = time.monotonic()
            mosaic, _ = cam.frame(args.exposure)
            stars = skywatch.count_stars(luminance(mosaic))
            seen = f"{stars} stars" if stars >= 8 else "no stars (cloud?)"
            snap.publish(mosaic, kind="live view", quick=True,
                         detail=f"{args.exposure:g} s · {seen}")
            print(f"{time.strftime('%H:%M:%S')}  {seen}", flush=True)
            time.sleep(max(0, args.every - (time.monotonic() - began)))


if __name__ == "__main__":
    main()
