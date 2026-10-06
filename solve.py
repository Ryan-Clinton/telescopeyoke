#!/usr/bin/env python3
"""Work out where the telescope is pointing from a photo of stars.

    ./solve.py                      take a frame and solve it
    ./solve.py --file frames/x.fits solve a saved frame
    ./solve.py --near M57           tell the solver roughly where to look
    ./solve.py --json               the answer as JSON

Uses ASTAP with its D20 star database. Prints the centre of the frame as
J2000 RA/Dec, the camera's rotation and the image scale.
"""
import argparse
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from astropy.io import fits

import config
import interface
from camera import Camera, luminance

import host

ROOT = Path(__file__).parent
SOLVER = config.solver()
ASTAP, DATABASE = SOLVER["program"], SOLVER["database"]
# Height of the camera's view in degrees, from the sensor and focal length
# in config.toml (0.67° for the 183C behind 750 mm).
FIELD_HEIGHT = round(config.field_height(), 3)


# Stars a little out of focus are discs tens of pixels wide, which ASTAP does
# not take for stars. Averaged in blocks of this many pixels they are points
# again: the first frames at dusk on 6 October 2026 solved only this way.
COARSE = 4


def coarse(image, block=COARSE):
    """The image averaged in blocks, with the sky's level taken off."""
    image = np.asarray(image, dtype=float)
    h, w = (image.shape[0] // block) * block, (image.shape[1] // block) * block
    small = image[:h, :w].reshape(h // block, block, w // block, block).mean((1, 3))
    return np.clip((small - np.median(small)) * block * block + 1000, 0, 65535)


def solve(image, ra_hint=None, dec_hint=None, radius=30, field=FIELD_HEIGHT, timeout=180):
    """Plate-solve a 2-D brightness image. Hints are in degrees; with none,
    the whole sky is searched, which is slow. Returns a dict with ra, dec
    (degrees, J2000), rotation (degrees), scale (arcsec per pixel of the
    image given) and seconds, or None if no match was found. A frame that
    does not solve as it is gets a second try averaged in blocks, when a
    hint keeps that search short."""
    if config.DEMO:
        import simulator
        return simulator.solve(image, ra_hint, dec_hint, radius)
    found = astap(image, ra_hint, dec_hint, radius, field, timeout)
    if found is None and ra_hint is not None and min(np.shape(image)) >= 400 * COARSE:
        found = astap(coarse(image), ra_hint, dec_hint, radius, field, timeout)
        if found:
            found["scale"] /= COARSE
            found["coarse"] = COARSE
            if "cd" in found:
                found["cd"] = [[v / COARSE for v in row] for row in found["cd"]]
    return found


def astap(image, ra_hint, dec_hint, radius, field, timeout):
    """One run of ASTAP on the image as given."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "frame.fits"
        fits.PrimaryHDU(np.clip(image, 0, 65535).astype(np.uint16)).writeto(path)
        cmd = [ASTAP, "-f", str(path), "-d", DATABASE, "-D", "d20",
               "-fov", str(field), "-z", "0"]
        if ra_hint is None:
            cmd += ["-r", "180"]
        else:
            cmd += ["-ra", f"{ra_hint / 15:.5f}", "-spd", f"{dec_hint + 90:.4f}",
                    "-r", str(radius)]
        started = time.monotonic()
        subprocess.run(cmd, capture_output=True, timeout=timeout, **host.QUIET)
        result = dict(
            line.split("=", 1) for line in
            (path.with_suffix(".ini").read_text(encoding="utf-8", errors="replace").splitlines()
             if path.with_suffix(".ini").exists() else []) if "=" in line)
    if result.get("PLTSOLVD") != "T":
        return None
    found = {
        "ra": float(result["CRVAL1"]), "dec": float(result["CRVAL2"]),
        "rotation": float(result.get("CROTA2", 0)),
        "scale": abs(float(result["CDELT2"])) * 3600,
        "seconds": round(time.monotonic() - started, 1),
    }
    if all(k in result for k in ("CD1_1", "CD1_2", "CD2_1", "CD2_2")):
        # Degrees of sky (east-west, north-south) per pixel across and up.
        found["cd"] = [[float(result["CD1_1"]), float(result["CD1_2"])],
                       [float(result["CD2_1"]), float(result["CD2_2"])]]
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="solve this FITS frame instead of taking one")
    ap.add_argument("--exposure", type=float, default=3.0)
    ap.add_argument("--gain", type=int, default=300)
    ap.add_argument("--near", help="object the scope is roughly aimed at")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("solve", lambda: run(args), args.json)


def run(args):
    from astropy import units as u
    from astropy.coordinates import Angle

    if args.file:
        data = fits.getdata(args.file)
    else:
        with Camera(gain=args.gain) as cam:
            data, _ = cam.frame(args.exposure)
    # Raw colour frames are solved on the half-size brightness image.
    image = luminance(data) if data.shape[0] > 3000 else data

    hint = (None, None)
    if args.near:
        import mount
        target = mount.find_target(args.near)
        hint = (target["ra"], target["dec"])
    found = solve(image, *hint)
    if not found:
        raise interface.Refusal("PLATE_SOLVE_FAILED",
                                "No solution: too few stars, out of focus, or cloud.")
    ra = Angle(found["ra"] * u.deg).to_string(unit=u.hour, sep="hms", precision=1)
    dec = Angle(found["dec"] * u.deg).to_string(sep="dms", precision=0, alwayssign=True)
    print(f"centre RA {ra}  Dec {dec}  (J2000)")
    print(f"rotation {found['rotation']:.1f}°, scale {found['scale']:.2f} arcsec/pixel, "
          f"solved in {found['seconds']}s")
    return {"ra_deg": found["ra"], "dec_deg": found["dec"], "ra": ra, "dec": dec,
            "rotation_deg": found["rotation"], "scale_arcsec_per_pixel": found["scale"],
            "seconds": found["seconds"]}


if __name__ == "__main__":
    main()
