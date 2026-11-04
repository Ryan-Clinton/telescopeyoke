#!/usr/bin/env python3
"""Star shapes in the corners of a frame against its middle: whether the
corrector's spacing, a tilt or the collimation is spoiling the edges.

    ./corners.py                      take one frame (5 s) and measure it
    ./corners.py --exposure 10
    ./corners.py --file frames/X/light-0001.fits
    ./corners.py --json

A mono frame is measured at full resolution (a colour one at its 2x2
brightness). In each corner and the middle: the stars' width (FWHM), their
roundness (1 is round) and which way the stretched ones point, measured
against the line to the frame's centre: along it (radial) or across it
(tangential). The pattern says which fault it is (docs/mono-upgrade.md,
first night): all four corners stretched alike, radially or tangentially,
is the corrector's spacing (55 mm); corners unlike each other, one side
worse, is tilt; stars soft or flared even in the middle is collimation.
Uses the camera only (no mount); with --file, nothing at all.
"""
import argparse
import math

import numpy as np

import interface
import stacking

REGION = 0.18        # each corner box, and the middle one, as a share of the frame's width and height
ROUND_OK = 0.85      # median roundness at or above this: round enough
WIDER_OK = 1.25      # a corner's stars this much wider than the middle's: soft corner
LEAST = 5            # stars needed in a region to say anything about it


def shapes(lum, stars, box=7):
    """For each star (x, y, flux, fwhm, roundness): its long axis's angle in
    degrees, from its second moments in a small box round it."""
    h, w = lum.shape
    out = []
    for x, y, flux, fwhm, roundness in stars:
        r = int(max(box, 2.5 * fwhm))
        x0, x1, y0, y1 = max(0, int(x) - r), min(w, int(x) + r + 1), max(0, int(y) - r), min(h, int(y) + r + 1)
        cut = lum[y0:y1, x0:x1].astype(np.float64)
        cut = np.clip(cut - np.median(cut), 0, None)
        total = cut.sum()
        if total <= 0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cx, cy = (cut * xx).sum() / total, (cut * yy).sum() / total
        sxx = (cut * (xx - cx) ** 2).sum() / total
        syy = (cut * (yy - cy) ** 2).sum() / total
        sxy = (cut * (xx - cx) * (yy - cy)).sum() / total
        angle = 0.5 * math.degrees(math.atan2(2 * sxy, sxx - syy))
        out.append((float(x), float(y), float(fwhm), float(roundness), angle))
    return out


def region_of(x, y, w, h):
    fx, fy = x / w, y / h
    near = lambda f: "low" if f < REGION else ("high" if f > 1 - REGION else None)
    side_x, side_y = near(fx), near(fy)
    if side_x and side_y:
        return {("low", "low"): "top left", ("high", "low"): "top right",
                ("low", "high"): "bottom left", ("high", "high"): "bottom right"}[(side_x, side_y)]
    if abs(fx - 0.5) < REGION / 2 and abs(fy - 0.5) < REGION / 2:
        return "middle"
    return None


def measure(lum, scale=None):
    """The frame's regions: {name: {stars, fwhm_px, fwhm_arcsec, roundness,
    radial}}, radial being the share of stretched stars pointing along the
    line to the centre (1 all radial, 0 all tangential, None when too few
    are stretched to say), and the verdict."""
    h, w = lum.shape
    found = shapes(lum, stacking.find_stars(lum, limit=2000))
    regions = {}
    for name in ("middle", "top left", "top right", "bottom left", "bottom right"):
        here = [s for s in found if region_of(s[0], s[1], w, h) == name]
        if len(here) < LEAST:
            regions[name] = {"stars": len(here)}
            continue
        fwhm = float(np.median([s[2] for s in here]))
        roundness = float(np.median([s[3] for s in here]))
        stretched = [s for s in here if s[3] < ROUND_OK]
        radial = None
        if len(stretched) >= LEAST:
            along = 0
            for x, y, _, _, angle in stretched:
                to_centre = math.degrees(math.atan2(y - h / 2, x - w / 2))
                off = abs((angle - to_centre + 90) % 180 - 90)          # 0 radial, 90 tangential
                along += off < 45
            radial = round(along / len(stretched), 2)
        regions[name] = {"stars": len(here), "fwhm_px": round(fwhm, 2), "roundness": round(roundness, 2),
                         "radial": radial,
                         "fwhm_arcsec": round(fwhm * scale, 2) if scale else None}
    return regions, verdict(regions)


def verdict(regions):
    """Which fault the pattern shows, in words, from the rules in the docstring."""
    mid = regions.get("middle", {})
    corners = [regions[n] for n in ("top left", "top right", "bottom left", "bottom right")
               if "fwhm_px" in regions.get(n, {})]
    if "fwhm_px" not in mid or len(corners) < 3:
        return "too few stars in the middle or the corners to judge: a richer field, or a longer exposure"
    soft = [c for c in corners if c["fwhm_px"] > WIDER_OK * mid["fwhm_px"] or c["roundness"] < ROUND_OK]
    if mid["roundness"] < ROUND_OK:
        return "stars stretched even in the middle: collimation (or tracking, if they all point one way)"
    if not soft:
        return "corners as good as the middle: the spacing, tilt and collimation are fine"
    if len(soft) == len(corners):
        radials = [c["radial"] for c in corners if c["radial"] is not None]
        way = ""
        if radials:
            share = sum(radials) / len(radials)
            way = (" (stretched along the line to the centre)" if share > 0.6 else
                   " (stretched across the line to the centre)" if share < 0.4 else "")
        return f"all four corners soft alike{way}: the corrector's 55 mm spacing is off"
    names = [n for n in ("top left", "top right", "bottom left", "bottom right")
             if regions.get(n) in soft]
    return f"corners unlike each other ({', '.join(names)} worse): tilt in the camera, wheel or focuser"


def run(args, say=print):
    if args.file:
        mosaic, header = stacking.load_light(args.file) if args.file.endswith((".fits", ".fit", ".fz")) and \
            _compressed(args.file) else _plain(args.file)
    else:
        from camera import Camera
        with Camera(gain=args.gain) as cam:
            mosaic, header = cam.frame(args.exposure)
    mono = stacking.is_mono(header)
    from camera import luminance
    lum = mosaic.astype(np.float32) if mono else luminance(mosaic)
    focal = header.get("FOCALLEN")
    pixel = 2.4 * (1 if mono else 2)
    scale = 206.265 * pixel / float(focal) if focal else None
    regions, said = measure(lum, scale)
    for name, r in regions.items():
        if "fwhm_px" in r:
            arc = f" ({r['fwhm_arcsec']}\")" if r.get("fwhm_arcsec") else ""
            way = "" if r["radial"] is None else f", stretched ones {100 * r['radial']:.0f}% radial"
            say(f"  {name:12s} {r['stars']:4d} stars  FWHM {r['fwhm_px']:5.2f} px{arc}  roundness {r['roundness']:.2f}{way}")
        else:
            say(f"  {name:12s} {r['stars']:4d} stars: too few to measure")
    say(said)
    return {"regions": regions, "verdict": said, "full_resolution": bool(mono), "scale_arcsec": scale}


def _compressed(path):
    from astropy.io import fits
    with fits.open(path) as hdul:
        return len(hdul) > 1 and hdul[1].data is not None


def _plain(path):
    from astropy.io import fits
    with fits.open(path) as hdul:
        return hdul[0].data, hdul[0].header


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="measure this FITS frame instead of taking one")
    ap.add_argument("--exposure", type=float, default=5.0)
    ap.add_argument("--gain", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    return interface.main("corners", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
