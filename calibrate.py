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

A camera whose darks are matched, never scaled (the cooled 183M, with amp
glow): it waits for its cooler first, and each master is kept as a new
version, never overwriting one, filed by everything it is matched on:
darks by exposure, gain, offset, binning, readout speed and set
temperature (made with the cap on, indoors or on a cloudy night: the
cooler holds the temperature, so no clear window is spent on them); flats
by train and filter, kept raw, with a flat-dark (a dark at the flat's
exposure) taken off when used; and a bad-pixel map from the longest dark:

    ./calibrate.py badpixels                        from the darks kept; no camera

It takes no bias. Science (difference images, photometry, transits, depth)
refuses its frames until every master matches (docs/calibration.md).
"""
import argparse

import numpy as np
from astropy.io import fits

import config
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


LOWEST_BIAS = 10        # a bias reading under this, of 4095, is the black level at zero


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=["dark", "bias", "flat", "badpixels"])
    ap.add_argument("--exposure", type=float, default=2.0, help="seconds, for darks")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    return interface.main("calibrate", lambda: run(args), args.json)


MATCHED_HOT = 8.0      # a pixel this many robust spreads above a dark's median is a bad (hot) pixel


def matched_cards(header, camera):
    """What a matched master is filed and chosen by, from a frame it was made of."""
    cards = {k: header[k] for k in stacking.DARK_CARDS if k in header}
    cards.update(INSTRUME=camera, **{k: header[k] for k in ("TELESCOP", "FILTER", "FILTPOS", "CCD-TEMP")
                                      if k in header})
    return {k: (v[0] if isinstance(v, tuple) else v) for k, v in cards.items()}


def bad_pixels(dark, hot=MATCHED_HOT):
    """A bad-pixel map from a dark: the pixels far above the rest."""
    middle = float(np.median(dark))
    spread = 1.4826 * float(np.median(np.abs(dark - middle))) + 1e-6
    return (dark > middle + hot * spread).astype(np.uint8)


def run_matched(args, camera):
    """Masters for a camera whose darks are matched, never scaled (the cooled
    183M): each kept as a new version (never overwriting one), filed by
    everything it is matched on. A cooled camera's darks need no sky: make
    them with the cap on, indoors or on a cloudy night, never in a clear
    window. A flat is kept raw; its flat-dark is a dark at the flat's
    exposure (./calibrate.py dark --exposure S), taken off when it is used."""
    folder = stacking.library(camera)
    if args.kind == "bias":
        raise SystemExit(f"The {camera}'s darks are matched to each exposure and carry the offset with them: "
                         "it takes no bias. Make darks (and flat-darks) instead.")
    if args.kind == "badpixels":
        darks = [p for p in folder.glob("dark-*-v*.fits")]
        if not darks:
            raise SystemExit(f"No darks for the {camera} yet: ./calibrate.py dark --exposure S --gain G first.")
        longest = max(darks, key=lambda p: (float(fits.getheader(p).get("EXPTIME", 0)), p.stat().st_mtime))
        mask = bad_pixels(fits.getdata(longest).astype(np.float32))
        path = stacking.keep_master(folder, "badpixels", mask, {"INSTRUME": camera, "SOURCE": longest.name,
                                                                "NBAD": int(mask.sum())})
        print(f"saved {path}: {int(mask.sum())} bad pixels, from {longest.name}")
        return {"kind": "badpixels", "file": str(path), "bad": int(mask.sum())}
    with Camera(gain=args.gain) as cam:
        settle = getattr(cam, "settle", None)
        if settle:
            settle(say=print)            # at the cooler's target, as the lights will be
        if args.kind == "dark":
            frames, header = [], None
            for i in range(args.frames):
                mosaic, header = cam.frame(args.exposure)
                frames.append(mosaic)
                print(f"  dark {i + 1} of {args.frames}  (median {np.median(mosaic[::8, ::8]):.0f})", flush=True)
            if np.median(frames[0][::8, ::8]) > 0.2 * WHITE:
                raise SystemExit("Those frames are bright. Darks need the cap on.")
            cards = matched_cards(header, camera)
            path = stacking.keep_master(folder, stacking.dark_stem(cards), master(frames),
                                        dict(cards, NFRAMES=args.frames))
        else:
            import sxwheel
            seconds = flat_exposure(cam)
            frames, header = [], None
            for i in range(args.frames):
                mosaic, header = cam.frame(seconds)
                frames.append(mosaic)
            if config.hardware()["train"].get("filterwheel"):
                found = sxwheel.confirmed()
                if found is None:
                    raise SystemExit("The filter wheel confirmed no position: no flat is kept without its filter.")
                sxwheel.cards(header, found)
            cards = matched_cards(header, camera)
            cards.setdefault("TELESCOP", config.hardware()["train"]["name"])
            cards["EXPTIME"] = seconds
            path = stacking.keep_master(folder, stacking.flat_stem(cards), master(frames),
                                        dict(cards, NFRAMES=args.frames))
            print(f"Its flat-dark: with the cap on, ./calibrate.py dark --exposure {seconds:g} --gain {args.gain}")
    print(f"saved {path}")
    return {"kind": args.kind, "frames": args.frames, "gain": args.gain, "file": str(path)}


def run(args):
    camera = config.camera_name()
    if stacking.dark_method(camera) == "matched":
        return run_matched(args, camera)
    if args.kind == "badpixels":
        raise SystemExit("The 183C's hot pixels are taken out by its scaled dark and the stack's own cleaning: "
                         "a bad-pixel map is for a camera with matched darks.")
    with Camera(gain=args.gain) as cam:
        if args.kind == "dark":
            frames = capture(cam, args.exposure, args.frames, "dark")
            if np.median(frames[0][::8, ::8]) > 0.2 * WHITE:
                raise SystemExit("Those frames are bright. Darks need the cap on.")
            save(stacking.master_path("dark", args.exposure, args.gain), master(frames),
                 EXPTIME=args.exposure, GAIN=args.gain, NFRAMES=args.frames)
        elif args.kind == "bias":
            frames = capture(cam, 0.001, args.frames, "bias")
            level = float(np.median(frames[0][::8, ::8]))
            if level < LOWEST_BIAS:
                # 18 October 2026: the offset was 0 and a bias read 1, so the
                # sky's grain was cut off at zero and the sky measured negative.
                raise SystemExit(f"That bias reads {level:.0f} with the cap on: the black level is at zero and "
                                 "faint signal is cut off. Raise the camera's offset in the settings (46 on the "
                                 "Altair 183C) and take the bias again.")
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
