#!/usr/bin/env python3
"""Make the calibration frames that clean up every picture.

    ./calibrate.py dark --exposure 2 --gain 1500    cap ON the telescope
    ./calibrate.py bias --gain 1500                 cap ON
    ./calibrate.py flat --gain 300                  cap OFF, evenly lit view

A dark is what the camera records with no light: its hot pixels, glow and
fixed pattern. Subtracting it removes them from every frame. Darks must match
the exposure and gain you shoot at, and should be taken at a similar
temperature, so make them on the night.

A bias is the camera's zero level, used when there is no matching dark.

A flat is a picture of an evenly lit surface. It records the darkening
towards the corners and the dust shadows, so dividing by it removes them.
Point at the twilight sky with a white T-shirt stretched over the tube, or at
an evenly lit wall. A flat stays valid until the camera is turned or removed,
so each is filed under the 'setup' name in config.toml; change that name when
the arrangement changes and take a new flat.

A bias taken at the same gain as the dark also lets the dark adapt to the
sensor's temperature, which this camera cannot report: the dark is scaled to
match each frame's own hot pixels.

Masters are saved in calibration/ and picked up automatically by shoot.py
and restack.py.
"""
import argparse

import numpy as np
from astropy.io import fits

import interface
import stacking
from camera import WHITE, Camera


def capture(cam, exposure, count, label):
    frames = []
    for i in range(count):
        mosaic, _ = cam.frame(exposure)
        frames.append(mosaic)
        print(f"  {label} {i + 1} of {count}  (median {np.median(mosaic[::8, ::8]):.0f})", flush=True)
    return frames


def master(frames, clip=3.0):
    """Per-pixel average with outliers left out, a strip at a time so memory
    stays modest. Values more than `clip` robust standard deviations from the
    pixel's median (a cosmic ray, a passing light) are ignored; averaging the
    rest is less grainy than taking the median alone."""
    rows = frames[0].shape[0]
    out = np.empty(frames[0].shape, np.float32)
    for start in range(0, rows, 256):
        strip = np.array([f[start:start + 256] for f in frames], dtype=np.float32)
        middle = np.median(strip, axis=0)
        spread = 1.4826 * np.median(np.abs(strip - middle), axis=0)
        keep = np.abs(strip - middle) <= clip * spread + 1.0
        out[start:start + 256] = (strip * keep).sum(axis=0) / np.maximum(keep.sum(axis=0), 1)
    return out


def normalise_flat(flat):
    """Scale each of the four Bayer colours to average 1, so dividing by the
    flat evens out the illumination without changing the colour balance."""
    out = np.empty_like(flat, dtype=np.float32)
    for dy in (0, 1):
        for dx in (0, 1):
            plane = flat[dy::2, dx::2]
            out[dy::2, dx::2] = plane / np.median(plane)
    # A dead or unlit pixel would otherwise blow up the division.
    return np.clip(out, 0.2, None)


def flat_exposure(cam, target=0.4):
    """An exposure that fills the sensor to about `target` of full scale."""
    seconds = 0.01
    for _ in range(8):
        mosaic, _ = cam.frame(seconds)
        level = float(np.median(mosaic[::8, ::8])) / WHITE
        print(f"  {seconds:.4f} s gives {level:.0%} of full scale", flush=True)
        if 0.3 <= level <= 0.5:
            return seconds
        if level < 0.005:
            raise SystemExit("Hardly any light is reaching the camera. Is the cap off?")
        seconds = float(np.clip(seconds * target / level, 0.0005, 5.0))
    return seconds


def save(path, data, **cards):
    path.parent.mkdir(exist_ok=True)
    fits.PrimaryHDU(data.astype(np.float32), fits.Header(cards)).writeto(path, overwrite=True)
    print(f"saved {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=["dark", "bias", "flat"])
    ap.add_argument("--exposure", type=float, default=2.0, help="seconds, for darks")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    return interface.main("calibrate", lambda: run(args), args.json)


def run(args):
    with Camera(gain=args.gain) as cam:
        if args.kind == "dark":
            frames = capture(cam, args.exposure, args.frames, "dark")
            if np.median(frames[0][::8, ::8]) > 0.2 * WHITE:
                raise SystemExit("Those frames are bright. Darks need the cap on.")
            save(stacking.master_path("dark", args.exposure, args.gain), master(frames),
                 EXPTIME=args.exposure, GAIN=args.gain, NFRAMES=args.frames)
        elif args.kind == "bias":
            frames = capture(cam, 0.001, args.frames, "bias")
            save(stacking.master_path("bias", gain=args.gain), master(frames),
                 GAIN=args.gain, NFRAMES=args.frames)
        else:
            seconds = flat_exposure(cam)
            flat = master(capture(cam, seconds, args.frames, "flat"))
            bias_path = stacking.master_path("bias", gain=args.gain)
            if bias_path.exists():
                flat -= fits.getdata(bias_path)
            else:
                print("No bias for this gain; the flat will be slightly weak. "
                      f"Run: ./calibrate.py bias --gain {args.gain}")
            save(stacking.master_path("flat"), normalise_flat(flat),
                 EXPTIME=seconds, GAIN=args.gain, NFRAMES=args.frames, SETUP=stacking.setup_name())
            print(f"This flat is filed under the camera setup \"{stacking.setup_name()}\". If "
                  "you rotate or remove the camera, change 'setup' under [camera] in "
                  "config.toml and take a new one.")
    return {"kind": args.kind, "frames": args.frames, "gain": args.gain}


if __name__ == "__main__":
    main()
