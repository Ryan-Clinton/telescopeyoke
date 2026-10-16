#!/usr/bin/env python3
"""How bright one place on the sky was in every stack of an object: a
candidate's history, including the nights it was not seen.

    ./forced.py M31 11.10554 41.57670          RA and Dec in degrees
    ./forced.py M31 11.10554 41.57670 --json

Each stack of the object with a depth.py measurement is plate-solved, and
the light in an aperture at the place is measured against the glow round
it, through the stack's own zero point. Where nothing stands out, the
answer is an upper limit: fainter than the magnitude a 3-sigma star would
have there, judged from apertures dropped on a ring round the place. So
"not detected" says how faint it must have been, which a report needs.

Magnitudes are unfiltered, calibrated approximately to Gaia G. A star
already there contributes its light too: this measures the place, so a
candidate's history is clean only where the catalogues show nothing bright
underneath it (vet.py says so). Kept as forced-RA-DEC.json under the
object's frames folder. Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from astropy.io import fits

import config
import depth
import difference
import interface
import stacking

SEEN = 3.0       # a measurement this many times its noise is a detection; below it, an upper limit
RING = (18, 30)  # pixels: the ring of empty apertures that sets the noise at the place


def located(record, r):
    """The stack a depth record is of: as written, or beside the record when
    the path was written relative to another folder."""
    stack = Path(r.get("stack", ""))
    if stack.is_file():
        return stack
    beside = record.parent / stack.name
    return beside if beside.is_file() else None


def stacks_of(name):
    """Every stack of an object with a kept depth measurement, oldest first."""
    out = []
    for record in sorted((config.DATA / "frames" / stacking.folder_name(name)).glob("*/*depth.json")):
        r = json.loads(record.read_text(encoding="utf-8"))
        stack = located(record, r)
        if stack is not None and r.get("zeropoint"):
            out.append({"stack": stack, "zeropoint": r["zeropoint"], "fwhm": r.get("fwhm_px", 4.0),
                        "exposure_s": r.get("exposure_s"), "session": record.parent.name})
    return out


def weighted(flat, xy, fwhm, aperture_radius):
    """The light at each place, weighted by a star's shape: the best
    estimate for a faint point, deeper than a plain aperture. Scaled to what
    an aperture as wide as the stars holds, the zero point's scale."""
    s = max(fwhm, 1.5) / 2.355
    r = int(3 * s) + 1
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    inside = 1 - math.exp(-aperture_radius ** 2 / (2 * s * s))
    out = []
    for x, y in xy:
        ix, iy = int(round(x)), int(round(y))
        if not (r <= ix < flat.shape[1] - r and r <= iy < flat.shape[0] - r):
            out.append(np.nan)
            continue
        shape = np.exp(-((xx - (x - ix)) ** 2 + (yy - (y - iy)) ** 2) / (2 * s * s))
        shape /= shape.sum()
        cut = flat[iy - r:iy + r + 1, ix - r:ix + r + 1]
        out.append(inside * float((cut * shape).sum() / (shape ** 2).sum()))
    return np.array(out)


def measure_at(lum, x, y, fwhm, zeropoint, rng):
    """(magnitude or None, its error or None, the 3-sigma limit) at one place."""
    flat = lum - difference.glow(lum)
    radius = max(fwhm, 2.0)
    flux = weighted(flat, [(x, y)], fwhm, radius)[0]
    angles = rng.uniform(0, 2 * math.pi, 24)
    dist = rng.uniform(*RING, 24)
    ring = np.column_stack([x + dist * np.cos(angles), y + dist * np.sin(angles)])
    others = weighted(flat, ring, fwhm, radius)
    others = others[np.isfinite(others)]
    spread = 1.4826 * float(np.median(np.abs(others - np.median(others)))) if len(others) >= 8 else float("nan")
    limit = zeropoint - 2.5 * math.log10(SEEN * spread) if spread > 0 else None
    if np.isfinite(flux) and spread > 0 and flux > SEEN * spread:
        mag = zeropoint - 2.5 * math.log10(flux)
        return round(mag, 2), round(1.0857 * spread / flux, 2), None if limit is None else round(limit, 2)
    return None, None, None if limit is None else round(limit, 2)


def history(name, ra, dec, say=print, solve_with=None):
    """The place measured in every stack of the object, oldest first."""
    rng = np.random.default_rng(5)
    solve_with = solve_with or (lambda lum: depth.plate(lum, name))
    rows = []
    for s in stacks_of(name):
        lum = depth.brightness(fits.getdata(s["stack"]))
        wcs = solve_with(lum)
        x, y = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
        inside = 40 <= x < lum.shape[1] - 40 and 40 <= y < lum.shape[0] - 40
        row = {"session": s["session"], "stack": str(s["stack"]), "exposure_s": s["exposure_s"],
               "x": round(x, 1), "y": round(y, 1), "in_picture": inside}
        if inside:
            mag, err, limit = measure_at(lum, x, y, s["fwhm"], s["zeropoint"], rng)
            row.update(mag=mag, error=err, limit=limit, kind="measured")
        rows.append(row)
        if not inside:
            say(f"  {s['session']}: outside the picture")
        elif row["mag"] is not None:
            say(f"  {s['session']}: G {row['mag']:.2f} ± {row['error']:.2f}")
        else:
            say(f"  {s['session']}: not seen, fainter than G {row['limit']}")
    return rows


def run(args, say=print):
    if config.DEMO:
        raise interface.Refusal("DEMO_UNSUPPORTED", "Forced photometry needs real stacks.")
    say(f"RA {args.ra:.5f} Dec {args.dec:+.5f} in every measured stack of {args.name}:")
    rows = history(args.name, args.ra, args.dec, say)
    if not rows:
        raise interface.Refusal("NO_SESSION", f"No measured stack of {args.name}: run ./depth.py on them first.")
    answer = {"name": args.name, "ra": args.ra, "dec": args.dec, "measurements": rows,
              "band": "unfiltered, calibrated approximately to Gaia G"}
    kept = config.DATA / "frames" / stacking.folder_name(args.name) / f"forced-{args.ra:.5f}{args.dec:+.5f}.json"
    kept.write_text(json.dumps(answer, indent=1), encoding="utf-8")
    say(f"kept as {kept}")
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="the object whose stacks to measure")
    ap.add_argument("ra", type=float, help="degrees")
    ap.add_argument("dec", type=float, help="degrees")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("forced", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
