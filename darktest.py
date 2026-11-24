#!/usr/bin/env python3
"""Does the 183M gain from being cooled further? Dark frames at several
temperatures, from warm to the -5 °C it runs at, measured and compared.

    ./darktest.py --plan             what it would take, and how long; opens nothing
    ./darktest.py                    +5, 0, -2.5 and -5 °C, cap on, then stays cold
    ./darktest.py --colder --temperatures -5 -7.5 -10   this one test below -5 °C
    ./darktest.py --more -5          the held run measures these next, without warming
    ./darktest.py --finish           the held run warms up slowly and ends
    ./darktest.py --warm-after       warm up by itself after the last temperature

The camera's previous owner found -5 °C enough on this sensor (altair.py's
TEC_LOWEST). The curve down to it shows whether the benefit is flattening
there, without setting the cooler any colder. At each temperature: short
frames for the zero level, then long ones, giving the dark signal, the noise
between frames, the hot pixels and the amp glow in the corners.

The results go in cache/darktest/, and no frame or master is kept: nothing
here can reach calibration/ or be used to calibrate a picture.
"""
import argparse
import json
import sys
import time

import numpy as np

import activity
import calibrate
import config
import interface
import jobs
import keeper
import records
import testmode
from altair import TEC_LOWEST, TEST_LOWEST
from camera import WHITE, Camera

TEMPERATURES = (5.0, 0.0, -2.5, -5.0)   # warm to cold: one slow way down
LONG_S, SHORT_S = 120.0, 1.0
FRAMES = 6
HOLD_S = 180            # after reaching each temperature, for the sensor to settle
GAIN = 1500
START_MARGIN_C = 1.0    # a temperature this close to the room's, or above it, cannot be held by a cooler
FLAT_BELOW = 0.02       # a last step that lowers the noise by less than this share: flattening
CORNER = 300            # pixels: the box in each corner where amp glow shows
HOT_ADU = 200           # a pixel this far above the zero level is hot: one fixed line for every temperature
CLIP = 5.0              # spreads from the middle: hot pixels left out of the averages
# Held cold after the last temperature, with nobody asking for more. Four
# hours until 24 November 2026, when the darks ended at 03:18 and the hold
# kept the camera from the video meant to follow until 07:28.
HOLD_MOST_S = 30 * 60
NEXT = config.DATA / "cache" / "darktest" / "next.json"     # the order a held run is waiting for


def robust(values):
    return 1.4826 * float(np.median(np.abs(values - np.median(values))))


def clipped(values):
    """The values without hot pixels. Means and spreads of these, as a median
    of whole-number levels moves in steps too coarse for a few ADU of dark."""
    values = np.asarray(values, dtype=np.float32).ravel()
    middle = float(np.median(values))
    return values[np.abs(values - middle) <= CLIP * max(robust(values), 1.0)]


def typical(values):
    return float(clipped(values).mean())


def measure(longs, shorts, long_s=LONG_S, short_s=SHORT_S):
    """The figures for one temperature, in ADU, from its frames."""
    long_master = calibrate.master(longs)
    zero = typical(calibrate.master(shorts)[::4, ::4])
    level = typical(long_master[::4, ::4])
    h, w = long_master.shape
    centre = long_master[h // 2 - CORNER:h // 2 + CORNER, w // 2 - CORNER:w // 2 + CORNER]
    corners = [long_master[:CORNER, :CORNER], long_master[:CORNER, -CORNER:],
               long_master[-CORNER:, :CORNER], long_master[-CORNER:, -CORNER:]]
    # The difference of two frames holds no fixed pattern: only the noise
    # that stacking has to beat, sqrt(2) too large.
    difference = longs[0][::2, ::2].astype(np.float32) - longs[1][::2, ::2].astype(np.float32)
    return {"zero_adu": round(zero, 2), "level_adu": round(level, 2),
            "dark_adu_per_s": round((level - zero) / (long_s - short_s), 5),
            "noise_adu": round(float(clipped(difference).std()) / np.sqrt(2), 3),
            "hot_pixels": int((long_master > zero + HOT_ADU).sum()),
            "amp_glow_adu": round(max(typical(c) for c in corners) - typical(centre), 2)}


def verdict(rows):
    """Whether the last step down still lowered the noise by a useful amount."""
    if len(rows) < 2:
        return "Too few temperatures measured to compare."
    a, b = rows[-2], rows[-1]
    fall = (a["noise_adu"] - b["noise_adu"]) / a["noise_adu"]
    said = (f"From {a['sensor_c']:.1f} to {b['sensor_c']:.1f} °C the noise fell {100 * fall:.1f}% and the dark "
            f"signal went from {a['dark_adu_per_s']:.4f} to {b['dark_adu_per_s']:.4f} ADU/s")
    return said + (": flattening, so colder is unlikely to help." if fall < FLAT_BELOW
                   else ": still falling, so a colder test could be worth raising with Gary.")


def plan(args):
    each = args.frames * (args.long + args.short) + HOLD_S
    minutes = (len(args.temperatures) * each + 20 * 60 + 10 * 60) / 60
    print(f"Cap on, 12 V in. Temperatures {', '.join(f'{t:g}' for t in args.temperatures)} °C, each {args.frames} x "
          f"{args.long:g} s and {args.frames} x {args.short:g} s at gain {args.gain}. About {minutes:.0f} minutes "
          "with the cooling and warm-up. No frames kept.")


def take(cam, args, target, start, rows, path, job):
    """Cool to one temperature, measure it and keep the figures."""
    if target > start - START_MARGIN_C:
        print(f"{target:g} °C left out: the sensor started at {start:.1f} °C", flush=True)
        return
    now = cam.temperature()
    job.expect(abs((now if now is not None else start) - target) * 60 + 900, f"cooling to {target:g} °C")
    cam.cool(target)
    cam.settle(say=print)
    job.expect(HOLD_S + 60, f"settling at {target:g} °C")
    until = time.monotonic() + HOLD_S
    while time.monotonic() < until:
        cam.ramp()
        time.sleep(5)
    job.expect(args.frames * args.short + 120, f"{target:g} °C: {args.frames} zero-level frames")
    shorts = [cam.frame(args.short)[0] for _ in range(args.frames)]
    if np.median(shorts[0][::8, ::8]) > 0.2 * WHITE:
        raise SystemExit("Those frames are bright. This needs the cap on.")
    longs = []
    for n in range(args.frames):
        job.expect(args.long * 1.5 + 60, f"{target:g} °C: {args.long:g} s dark {n + 1} of {args.frames}")
        longs.append(cam.frame(args.long)[0])
        print(f"  {target:g} °C: {args.long:g} s dark {n + 1} of {args.frames}", flush=True)
    row = {"target_c": target, "sensor_c": cam.temperature(), **measure(longs, shorts, args.long, args.short)}
    rows.append(row)
    said = (f"{row['sensor_c']:.1f} °C: dark {row['dark_adu_per_s']:.4f} ADU/s, noise {row['noise_adu']:.2f} "
            f"ADU, {row['hot_pixels']} hot pixels, amp glow {row['amp_glow_adu']:.1f} ADU")
    print(said, flush=True)
    job.reading(said)
    records.write(path, {"gain": args.gain, "long_s": args.long, "short_s": args.short,
                         "frames": args.frames, "start_c": start, "rows": rows}, stamp=True)


def hold(cam, args, start, rows, path, job):
    """Stay cold after the last temperature, so another can follow without a
    warm-up and a second cool-down. A plain kill ends it through run()'s
    slow warm-up; so does HOLD_MOST_S with nobody asking for more, and so
    does a job queued for the camera (./ty bg ... --needs camera), which
    starts once this has let it go."""
    ask = "./darktest.py --more TEMPS for further temperatures, ./darktest.py --finish to warm up slowly"
    print(f"holding the sensor cold, up to {HOLD_MOST_S / 60:g} min: {ask}", flush=True)
    job.waiting(f"darks done; holding the sensor cold up to {HOLD_MOST_S / 60:g} min for more temperatures",
                ask=ask, holds=["camera"], most_s=HOLD_MOST_S + 60)
    until = time.monotonic() + HOLD_MOST_S
    while time.monotonic() < until:
        cam.ramp()
        if jobs.wanted("camera") and not NEXT.exists():
            print("a job is queued for the camera: finishing, the slow warm-up", flush=True)
            return
        if NEXT.exists():
            asked = json.loads(NEXT.read_text())["temperatures"]
            NEXT.unlink()
            if not asked:
                print("finishing: the slow warm-up", flush=True)
                return
            job.resumed(f"more temperatures: {', '.join(f'{t:g}' for t in asked)} °C")
            for target in asked:
                lowest = TEST_LOWEST if args.colder else TEC_LOWEST
                if target < lowest:         # refused here: the cooler's own refusal would end the hold and warm it
                    print(f"{target:g} °C not taken: below the {lowest:g} °C limit", flush=True)
                    break
                take(cam, args, target, start, rows, path, job)
            until = time.monotonic() + HOLD_MOST_S
            print("holding the sensor cold again", flush=True)
            job.waiting(f"holding the sensor cold again, up to {HOLD_MOST_S / 60:g} min", ask=ask,
                        holds=["camera"], most_s=HOLD_MOST_S + 60)
        time.sleep(5)


def run(args):
    if keeper.running():
        raise interface.Refusal("CAMERA_BUSY", "The camera keeper holds the sensor at its target: ./keeper.py stop "
                                               "first, then this.")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    path = config.DATA / "cache" / "darktest" / f"{stamp}.json"
    rows = []
    each = args.frames * (args.long + args.short) + HOLD_S + 15 * 60
    with activity.job("darktest", steps=[f"{t:g} °C" for t in args.temperatures],
                      expect_s=len(args.temperatures) * each + 20 * 60) as job, Camera(gain=args.gain) as cam:
        try:
            if args.colder:
                cam.lowest = TEST_LOWEST    # this camera object only: every other command keeps -5 °C
            start = cam.temperature()
            if start is None:
                raise SystemExit("The sensor will not say its temperature: no comparison can be made.")
            print(f"sensor at {start:.1f} °C", flush=True)
            NEXT.unlink(missing_ok=True)    # an order left from an earlier run is not for this one
            for k, target in enumerate(args.temperatures, 1):
                job.step(k, f"{target:g} °C")
                take(cam, args, target, start, rows, path, job)
            temps = ", ".join(f"{r['sensor_c']:.1f}" for r in rows)
            job.milestone(f"darks done at {temps} °C", name="darks")
            if not args.warm_after:
                hold(cam, args, start, rows, path, job)
        finally:
            job.expect(15 * 60, "the slow warm-up")
            cam.warm_up(say=print)
        said = verdict(rows)
        print(said)
        job.result(said)
    records.write(path, {"gain": args.gain, "long_s": args.long, "short_s": args.short, "frames": args.frames,
                         "start_c": start, "rows": rows, "verdict": said}, stamp=True)
    print(f"kept {path}")


def main():
    sys.stdout.reconfigure(line_buffering=True)     # the cooling lines reach a log as they happen, not with the next dark
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="what it would do; opens nothing")
    ap.add_argument("--temperatures", type=float, nargs="+", default=list(TEMPERATURES),
                    help="°C, warm to cold; the camera refuses any below its -5 °C limit")
    ap.add_argument("--frames", type=int, default=FRAMES, help=f"of each length (default {FRAMES}, at least 2)")
    ap.add_argument("--long", type=float, default=LONG_S, help=f"seconds (default {LONG_S:g})")
    ap.add_argument("--short", type=float, default=SHORT_S, help=f"seconds, for the zero level (default {SHORT_S:g})")
    ap.add_argument("--gain", type=int, default=GAIN)
    ap.add_argument("--colder", action="store_true", help=f"this test may go down to {TEST_LOWEST:g} °C")
    ap.add_argument("--more", type=float, nargs="+", metavar="C", help="further temperatures for the run holding cold")
    ap.add_argument("--finish", action="store_true", help="tell the run holding cold to warm up slowly and end")
    ap.add_argument("--warm-after", action="store_true", help="warm up after the last temperature instead of holding")
    args = ap.parse_args()
    if args.more or args.finish:
        records.write(NEXT, {"temperatures": sorted(args.more or [], reverse=True)})
        print("Left for the run holding the sensor cold; it reads it within 5 s (see its log).")
        return
    if args.frames < 2 or args.long <= args.short:
        ap.error("needs at least 2 frames, and --long longer than --short")
    args.temperatures = sorted(args.temperatures, reverse=True)
    lowest = TEST_LOWEST if args.colder else TEC_LOWEST
    if args.temperatures[-1] < lowest:
        ap.error(f"{args.temperatures[-1]:g} °C is below the {lowest:g} °C limit" + ("" if args.colder else " (--colder)"))
    if args.plan:
        plan(args)
    else:
        with testmode.during("the dark temperature test"):
            run(args)


if __name__ == "__main__":
    main()
