#!/usr/bin/env python3
"""Does the 183M gain from being cooled further? Dark frames at several
temperatures, from warm to the -5 °C it runs at, measured and compared.

    ./darktest.py --plan             what it would take, and how long; opens nothing
    ./darktest.py                    +5, 0, -2.5 and -5 °C, cap on

The camera's previous owner found -5 °C enough on this sensor (altair.py's
TEC_LOWEST). The curve down to it shows whether the benefit is flattening
there, without setting the cooler any colder. At each temperature: short
frames for the zero level, then long ones, giving the dark signal, the noise
between frames, the hot pixels and the amp glow in the corners.

The results go in cache/darktest/, and no frame or master is kept: nothing
here can reach calibration/ or be used to calibrate a picture.
"""
import argparse
import time

import numpy as np

import calibrate
import config
import interface
import keeper
import records
from camera import WHITE, Camera

TEMPERATURES = (5.0, 0.0, -2.5, -5.0)   # warm to cold: one slow way down
LONG_S, SHORT_S = 120.0, 1.0
FRAMES = 6
HOLD_S = 180            # after reaching each temperature, for the sensor to settle
GAIN = 1500
START_MARGIN_C = 1.0    # a temperature this close to the room's, or above it, cannot be held by a cooler
FLAT_BELOW = 0.02       # a last step that lowers the noise by less than this share: flattening
CORNER = 300            # pixels: the box in each corner where amp glow shows


def robust(values):
    return 1.4826 * float(np.median(np.abs(values - np.median(values))))


def measure(longs, shorts, long_s=LONG_S, short_s=SHORT_S):
    """The figures for one temperature, in ADU, from its frames."""
    long_master = calibrate.master(longs)
    zero = float(np.median(calibrate.master(shorts)[::4, ::4]))
    level = float(np.median(long_master[::4, ::4]))
    h, w = long_master.shape
    centre = long_master[h // 2 - CORNER:h // 2 + CORNER, w // 2 - CORNER:w // 2 + CORNER]
    corners = [long_master[:CORNER, :CORNER], long_master[:CORNER, -CORNER:],
               long_master[-CORNER:, :CORNER], long_master[-CORNER:, -CORNER:]]
    # The difference of two frames holds no fixed pattern: only the noise
    # that stacking has to beat, sqrt(2) too large.
    difference = longs[0][::2, ::2].astype(np.float32) - longs[1][::2, ::2].astype(np.float32)
    return {"zero_adu": round(zero, 2), "level_adu": round(level, 2),
            "dark_adu_per_s": round((level - zero) / (long_s - short_s), 5),
            "noise_adu": round(robust(difference) / np.sqrt(2), 3),
            "hot_pixels": int(calibrate.bad_pixels(long_master).sum()),
            "amp_glow_adu": round(max(float(np.median(c)) for c in corners) - float(np.median(centre)), 2)}


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


def run(args):
    if keeper.running():
        raise interface.Refusal("CAMERA_BUSY", "The camera keeper holds the sensor at its target: ./keeper.py stop "
                                               "first, then this.")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    path = config.DATA / "cache" / "darktest" / f"{stamp}.json"
    rows = []
    with Camera(gain=args.gain) as cam:
        try:
            start = cam.temperature()
            if start is None:
                raise SystemExit("The sensor will not say its temperature: no comparison can be made.")
            print(f"sensor at {start:.1f} °C", flush=True)
            for target in args.temperatures:
                if target > start - START_MARGIN_C:
                    print(f"{target:g} °C left out: the sensor started at {start:.1f} °C", flush=True)
                    continue
                cam.cool(target)
                cam.settle(say=print)
                until = time.monotonic() + HOLD_S
                while time.monotonic() < until:
                    cam.ramp()
                    time.sleep(5)
                shorts = [cam.frame(args.short)[0] for _ in range(args.frames)]
                if np.median(shorts[0][::8, ::8]) > 0.2 * WHITE:
                    raise SystemExit("Those frames are bright. This needs the cap on.")
                longs = []
                for n in range(args.frames):
                    longs.append(cam.frame(args.long)[0])
                    print(f"  {target:g} °C: {args.long:g} s dark {n + 1} of {args.frames}", flush=True)
                row = {"target_c": target, "sensor_c": cam.temperature(), **measure(longs, shorts, args.long, args.short)}
                rows.append(row)
                print(f"{row['sensor_c']:.1f} °C: dark {row['dark_adu_per_s']:.4f} ADU/s, noise {row['noise_adu']:.2f} "
                      f"ADU, {row['hot_pixels']} hot pixels, amp glow {row['amp_glow_adu']:.1f} ADU", flush=True)
                records.write(path, {"gain": args.gain, "long_s": args.long, "short_s": args.short,
                                     "frames": args.frames, "start_c": start, "rows": rows}, stamp=True)
        finally:
            cam.warm_up(say=print)
    said = verdict(rows)
    print(said)
    records.write(path, {"gain": args.gain, "long_s": args.long, "short_s": args.short, "frames": args.frames,
                         "start_c": start, "rows": rows, "verdict": said}, stamp=True)
    print(f"kept {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="what it would do; opens nothing")
    ap.add_argument("--temperatures", type=float, nargs="+", default=list(TEMPERATURES),
                    help="°C, warm to cold; the camera refuses any below its -5 °C limit")
    ap.add_argument("--frames", type=int, default=FRAMES, help=f"of each length (default {FRAMES}, at least 2)")
    ap.add_argument("--long", type=float, default=LONG_S, help=f"seconds (default {LONG_S:g})")
    ap.add_argument("--short", type=float, default=SHORT_S, help=f"seconds, for the zero level (default {SHORT_S:g})")
    ap.add_argument("--gain", type=int, default=GAIN)
    args = ap.parse_args()
    if args.frames < 2 or args.long <= args.short:
        ap.error("needs at least 2 frames, and --long longer than --short")
    args.temperatures = sorted(args.temperatures, reverse=True)
    if args.plan:
        plan(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
