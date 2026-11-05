#!/usr/bin/env python3
"""Make the calibration frames that clean up every picture.

    ./calibrate.py dark --exposure 2 --gain 1500    cap ON the telescope
    ./calibrate.py bias --gain 1500                 cap ON
    ./calibrate.py flat --gain 300                  cap OFF, evenly lit view
    ./calibrate.py flat --filters B G R L --twilight    dawn sky flats, nothing over
                       the tube: waits for the twilight, one filter after another

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
import time

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


SHORTEST, LONGEST = 0.0005, 5.0   # seconds a flat may take
TWILIGHT_SUN = -12.0     # degrees: dawn flats wait for the Sun to be this high before the camera opens
TWILIGHT_WAIT = 3600     # seconds the twilight is waited for, at most, once the camera is open


class TooBright(Exception):
    """The shortest exposure still fills the sensor: the sky is too bright for flats."""


def flat_exposure(cam, target=0.4, twilight=False, sleep=time.sleep, most=TWILIGHT_WAIT):
    """An exposure that fills the sensor to about `target` of full scale.
    With `twilight`, a sky still too dark is waited for (a minute at a time,
    up to `most` seconds) instead of refused, and one already too bright for
    the shortest exposure raises TooBright."""
    seconds, waited = 0.01, 0.0
    for _ in range(200 if twilight else 8):
        mosaic, _ = cam.frame(seconds)
        level = float(np.median(mosaic[::8, ::8])) / WHITE
        print(f"  {seconds:.4f} s gives {level:.0%} of full scale", flush=True)
        if 0.3 <= level <= 0.5:
            return seconds
        if twilight and level > 0.5 and seconds <= SHORTEST:
            raise TooBright(f"{SHORTEST} s already fills {level:.0%} of the sensor")
        wanted = seconds * target / max(level, 1e-6)
        if twilight and (level < 0.005 or wanted > LONGEST):
            if waited >= most:
                raise SystemExit(f"The sky never grew bright enough for flats in {most / 60:.0f} minutes.")
            print("  the sky is still too dark for flats; waiting a minute", flush=True)
            sleep(60)
            waited += 60
            seconds = LONGEST if level >= 0.005 else 0.01
            continue
        if level < 0.005:
            raise SystemExit("Hardly any light is reaching the camera. Is the cap off?")
        seconds = float(np.clip(wanted, SHORTEST, LONGEST))
    return seconds


def sun_altitude(when=None):
    """The Sun's altitude at the site now, in degrees."""
    import mount
    from astropy.coordinates import AltAz, get_sun
    from astropy.time import Time
    when = when or Time.now()
    place = mount.location(config.load()["site"])
    return float(get_sun(when).transform_to(AltAz(obstime=when, location=place)).alt.deg)


def wait_for_twilight(sleep=time.sleep, altitude=sun_altitude):
    """Before dawn sky flats: wait, with the camera closed, for the Sun to
    reach TWILIGHT_SUN, so the cooler has settled by the time the sky is
    bright enough. Refuses once the Sun is up."""
    while True:
        sun = altitude()
        if sun > 0:
            raise SystemExit(f"The Sun is {sun:.0f}° up: too late for sky flats.")
        if sun >= TWILIGHT_SUN:
            return
        print(f"  the Sun is {-sun:.0f}° below the horizon; waiting for {-TWILIGHT_SUN:.0f}°", flush=True)
        sleep(300)


def save(path, data, **cards):
    path.parent.mkdir(exist_ok=True)
    fits.PrimaryHDU(data.astype(np.float32), fits.Header(cards)).writeto(path, overwrite=True)
    print(f"saved {path}")


LOWEST_BIAS = 10        # a bias reading under this, of 4095, is the black level at zero


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=["dark", "bias", "flat", "badpixels"])
    ap.add_argument("--exposure", type=float, nargs="+", default=[2.0],
                    help="seconds, for darks; a cooled camera takes several in one cold session "
                         "(--exposure 4 16), then warms up gently")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--filters", nargs="+", metavar="F",
                    help="flats: one after another in these filters (at dawn the sky brightens, so B G R L)")
    ap.add_argument("--twilight", action="store_true",
                    help="flats: dawn sky flats with nothing over the tube; waits for the twilight")
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
    if args.kind == "flat" and getattr(args, "twilight", False):
        wait_for_twilight()
    with Camera(gain=args.gain) as cam:
        settle = getattr(cam, "settle", None)
        if settle:
            settle(say=print)            # at the cooler's target, as the lights will be
        if args.kind == "dark":
            # 4 November 2026: one exposure a run meant closing the camera
            # between the 4 s and 16 s darks, which turns the cooler off with
            # no warm-up. Every exposure is taken in the one cold session and
            # the cooler is stepped up gently at the end (finally, below).
            try:
                paths = []
                for seconds in args.exposure:
                    frames, header = [], None
                    for i in range(args.frames):
                        mosaic, header = cam.frame(seconds)
                        frames.append(mosaic)
                        print(f"  {seconds:g} s dark {i + 1} of {args.frames}  "
                              f"(median {np.median(mosaic[::8, ::8]):.0f})", flush=True)
                    if np.median(frames[0][::8, ::8]) > 0.2 * WHITE:
                        raise SystemExit("Those frames are bright. Darks need the cap on.")
                    cards = matched_cards(header, camera)
                    path = stacking.keep_master(folder, stacking.dark_stem(cards), master(frames),
                                                dict(cards, NFRAMES=args.frames))
                    print(f"saved {path}", flush=True)
                    paths.append(str(path))
            finally:
                warm_up = getattr(cam, "warm_up", None)
                if warm_up:
                    try:
                        warm_up(say=lambda line: print(f"  {line}", flush=True))
                    except Exception as problem:
                        print(f"  camera: the warm-up failed ({problem}); closing the camera turns the cooler off")
            return {"kind": "dark", "frames": args.frames, "gain": args.gain, "exposures": args.exposure,
                    "files": paths}
        else:
            # 5 November 2026: no dawn flats were taken after the 183M's
            # first night, and the camera was packed away before any could
            # be. Every filter in one cold session, then the warm-up (a flat
            # used to close the camera cold, which stops the cooler at once).
            kept, exposures = [], []
            try:
                for band in getattr(args, "filters", None) or [None]:
                    try:
                        found = flat_in(cam, camera, folder, args, band)
                    except TooBright as problem:
                        print(f"  no flat in {band}: {problem}; the sky is too bright now", flush=True)
                        break
                    kept.append(found["file"])
                    exposures.append(found["exposure"])
            finally:
                warm_up = getattr(cam, "warm_up", None)
                if warm_up:
                    try:
                        warm_up(say=lambda line: print(f"  {line}", flush=True))
                    except Exception as problem:
                        print(f"  camera: the warm-up failed ({problem}); closing the camera turns the cooler off")
            if not kept:
                raise SystemExit("No flat was kept.")
            print("Their flat-darks: with the cap on, ./calibrate.py dark --exposure "
                  + " ".join(f"{s:g}" for s in sorted(set(exposures))) + f" --gain {args.gain}")
            return {"kind": "flat", "frames": args.frames, "gain": args.gain, "files": kept,
                    "exposures": exposures}
    print(f"saved {path}")
    return {"kind": args.kind, "frames": args.frames, "gain": args.gain, "file": str(path)}


def flat_in(cam, camera, folder, args, band=None):
    """One matched flat in filter `band` (None: whatever is in the light path)."""
    import sxwheel
    if band:
        import filters
        # As the lights were taken: LRGB are parfocal and the focus is left as it is.
        filters.change(band, say=lambda line: print(f"  {line}", flush=True), as_is=True)
    seconds = flat_exposure(cam, twilight=getattr(args, "twilight", False))
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
    print(f"saved {path} ({band or 'the filter in place'}, {seconds:g} s)", flush=True)
    return {"file": str(path), "exposure": seconds}


def run(args):
    camera = config.camera_name()
    if stacking.dark_method(camera) == "matched":
        return run_matched(args, camera)
    if args.kind == "badpixels":
        raise SystemExit("The 183C's hot pixels are taken out by its scaled dark and the stack's own cleaning: "
                         "a bad-pixel map is for a camera with matched darks.")
    if len(args.exposure) > 1:
        raise SystemExit("Several exposures in one run are for a cooled camera's matched darks: "
                         "take this camera's darks one exposure at a time.")
    args.exposure = args.exposure[0]
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
