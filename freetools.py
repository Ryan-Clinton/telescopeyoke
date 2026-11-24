#!/usr/bin/env python3
"""The free image-processing tools TelescopeYoke can drive. Each person installs their own.

    ./freetools.py status                         which tools are here, and where to get the rest
    ./freetools.py denoise IN.fits OUT.fits       GraXpert's noise reduction on a copy of a stack
    ./freetools.py stars IN.fits OUT.fits         Dark Star's star removal on a copy of a stack

The tools are separate programs and are never bundled. They work on temporary copies: a
stack is only read, and what they make is for pictures, never for measurements.
TY_GRAXPERT, TY_SIRIL and TY_SETIASTRO (its cosmicclarity command) name a program not on the PATH.
TY_GRAXPERT_LIBS adds library folders, for a GPU whose libraries are not installed system-wide.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy import ndimage

import stacking

STRENGTH = 0.6      # about half the grain on this rig's stacks (23 November 2026)
RUN_LIMIT = 3 * 3600

TOOLS = {
    "graxpert": {"name": "GraXpert", "env": "TY_GRAXPERT", "programs": ("GraXpert", "graxpert"),
                 "for": "noise reduction", "url": "https://graxpert.com/",
                 "how": "its AI denoise model downloads on first use (CC BY-NC-SA 4.0: non-commercial)"},
    "siril": {"name": "Siril", "env": "TY_SIRIL", "programs": ("siril-cli",),
              "for": "not used by the pictures yet", "url": "https://siril.org/download/", "how": ""},
    # Cosmic Clarity's own repository was archived in 2026; it lives on inside the suite, whose AI models
    # each person downloads and accepts in the suite itself (personal, non-commercial use).
    "setiastro": {"name": "Seti Astro Suite Pro", "env": "TY_SETIASTRO", "programs": ("cosmicclarity",),
                  "for": "star removal (Dark Star) in narrowband pictures", "url": "https://www.setiastro.com/",
                  "how": "then download its AI models from inside the suite and accept their licence there"},
}
TESTED = {"graxpert": "3.0.2", "siril": "1.4.5", "setiastro": "1.24.8"}    # 23 and 24 November 2026


class ToolUnavailable(Exception):
    """A tool is missing or failed. The picture carries on without it and says so."""


def find(tool):
    entry = TOOLS[tool]
    named = os.environ.get(entry["env"])
    if named:
        return named if Path(named).is_file() and os.access(named, os.X_OK) else None
    return next(filter(None, map(shutil.which, entry["programs"])), None)


def tool_env(tool):
    env = dict(os.environ)
    if tool == "setiastro":
        env.setdefault("QT_QPA_PLATFORM", "offscreen")     # a Qt program, run with no window
    extra = os.environ.get("TY_GRAXPERT_LIBS") if tool == "graxpert" else None
    if extra:
        env["LD_LIBRARY_PATH"] = extra + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    return env


def version(tool):
    program = find(tool)
    if not program:
        return None
    try:
        done = subprocess.run([program, "--version"], capture_output=True, text=True, timeout=300, env=tool_env(tool),
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"\b(\d+\.\d+\.\d+\S*)", done.stdout + done.stderr)
    return found.group(1) if found else None


def denoise(plane, strength=STRENGTH):
    """One linear plane through GraXpert's own command line. NaNs stay NaN, and the level is kept."""
    program = find("graxpert")
    if not program:
        raise ToolUnavailable(f"GraXpert is not installed: get it from {TOOLS['graxpert']['url']}")
    plane = np.asarray(plane, dtype=np.float32)
    good = np.isfinite(plane)
    if not good.any():
        raise ToolUnavailable("the stack has no valid pixels")
    low, high = float(plane[good].min()), float(plane[good].max())
    if high <= low:
        raise ToolUnavailable("the stack is flat")
    high = low + (high - low) * 1.001
    filled = np.where(good, plane, float(np.median(plane[good])))
    with tempfile.TemporaryDirectory(prefix="ty-graxpert-") as folder:
        source, made = Path(folder) / "in.fits", Path(folder) / "out"
        fits.PrimaryHDU(((filled - low) / (high - low)).astype(np.float32)).writeto(source)
        try:
            done = subprocess.run([program, str(source), "-cli", "-cmd", "denoising", "-output", str(made),
                                   "-strength", f"{strength:g}", "-batch_size", "4"],
                                  capture_output=True, text=True, timeout=RUN_LIMIT, env=tool_env("graxpert"),
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            raise ToolUnavailable(f"GraXpert did not run: {e}") from e
        result = made.with_suffix(".fits")
        if done.returncode or not result.exists():
            tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no message"]
            raise ToolUnavailable(f"GraXpert failed: {tail[0][:200]}")
        out = np.squeeze(fits.getdata(result)).astype(np.float32)
    if out.shape != plane.shape or not np.isfinite(out).all():
        raise ToolUnavailable(f"GraXpert returned an unusable image {out.shape}")
    return np.where(good, out * (high - low) + low, np.nan).astype(np.float32)


def grain(plane):
    """A plane's grain, the robust spread of its pixels, NaNs left out."""
    plane = np.asarray(plane, dtype=np.float32)
    plane = plane[np.isfinite(plane)]
    return 1.4826 * float(np.median(np.abs(plane - np.median(plane)))) if plane.size else 0.0


def _stretch(plane, noise):
    """The asinh stretch Dark Star was tested with (sky at 3 sigma, the top 0.01% clipped), and its inverse."""
    sky = float(np.median(plane))
    soft = 3 * noise + 1e-6
    bottom = float(np.arcsinh(-1.0))
    span = max(float(np.arcsinh((np.percentile(plane, 99.99) - sky) / soft)) - bottom, 1e-6)
    return (lambda a: np.clip((np.arcsinh((a - sky) / soft) - bottom) / span, 0, 1).astype(np.float32),
            lambda u: (sky + soft * np.sinh(u * span + bottom)).astype(np.float32))


def _darkstar(u):
    program = find("setiastro")
    if not program:
        raise ToolUnavailable(f"Seti Astro Suite Pro is not installed: get it from {TOOLS['setiastro']['url']}")
    with tempfile.TemporaryDirectory(prefix="ty-darkstar-") as folder:
        source, made = Path(folder) / "in.fits", Path(folder) / "out.fits"
        fits.PrimaryHDU(u).writeto(source)
        try:
            # In its own empty folder: started in a busy one (the desktop's tool folder) it hung (24 November 2026).
            done = subprocess.run([program, "darkstar", "-i", str(source), "-o", str(made), "--gpu"], capture_output=True,
                                  text=True, timeout=RUN_LIMIT, env=tool_env("setiastro"), stdin=subprocess.DEVNULL,
                                  cwd=folder)
        except (OSError, subprocess.SubprocessError) as e:
            raise ToolUnavailable(f"Dark Star did not run: {e}") from e
        if done.returncode or not made.exists():
            tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no message"]
            raise ToolUnavailable(f"Dark Star failed (are its models downloaded in the suite?): {tail[0][:200]}")
        out = np.squeeze(fits.getdata(made)).astype(np.float32)
    if out.shape != u.shape or not np.isfinite(out).all():
        raise ToolUnavailable(f"Dark Star returned an unusable image {out.shape}")
    return out


def _change(u, ds):
    change = ndimage.gaussian_filter(u - ds, 1.0)
    return change, 1.4826 * float(np.median(np.abs(change - np.median(change)))) + 1e-6


def _discs(u, change, noise):
    """Where the stars Dark Star took off are: a disc round each one really found, growing with its brightness
    for its halo and spikes."""
    rows, cols = u.shape
    discs = np.zeros(u.shape, bool)
    for x, y, _, fwhm, round_ in stacking.find_stars(u, limit=4000):
        r0, c0 = int(round(y)), int(round(x))
        if not (0 <= r0 < rows and 0 <= c0 < cols):
            continue
        near = (slice(max(r0 - 2, 0), r0 + 3), slice(max(c0 - 2, 0), c0 + 3))
        height = float(change[near].max())
        # Not round, it may be a filament, which Dark Star must not touch. But a clipped core (IC 1848) and a
        # close double (NGC 2174's SII, left red) read as not round too: one Dark Star took far down is a star.
        # The planted faint line, 5 sigma high, is 0.15 to 0.22 after this stretch (24 November 2026).
        if round_ < .45 and height < .3:
            continue
        radius = int(np.clip(1.6 * max(fwhm, 2.5) * (1 + 5 * max(height - .25, 0)), 5, 45))
        top, left = max(r0 - radius, 0), max(c0 - radius, 0)
        yy, xx = np.ogrid[top - r0:min(r0 + radius + 1, rows) - r0, left - c0:min(c0 + radius + 1, cols) - c0]
        discs[top:r0 + radius + 1, left:c0 + radius + 1] |= yy ** 2 + xx ** 2 <= radius ** 2
    # Stars the finder called not round (on a filament, or touching another): compact and solid, unlike a line.
    labels, _ = ndimage.label(change > 6 * noise)
    for n, box in enumerate(ndimage.find_objects(labels), 1):
        h, w = box[0].stop - box[0].start, box[1].stop - box[1].start
        area = int((labels[box] == n).sum())
        if area >= 6 and max(h, w) <= 40 and max(h, w) / max(min(h, w), 1) < 2.5 and area / (h * w) >= .5:
            top, left = max(box[0].start - 5, 0), max(box[1].start - 5, 0)
            near = (slice(top, box[0].stop + 5), slice(left, box[1].stop + 5))
            discs[near] |= ndimage.binary_dilation(labels[near] == n, iterations=4)
    return discs


def _blend(u, ds, discs=None):
    """Dark Star's result only inside the star discs (`_discs`, this plane's own unless given), so a thin
    filament is never replaced: on its own it took off up to 72% of a faint planted glow and half of a thin line
    (23 November 2026). Only what Dark Star changed there, above the broad change, is taken."""
    change, noise = _change(u, ds)
    rows, cols = u.shape
    if discs is None:
        discs = _discs(u, change, noise)
    mask = ndimage.gaussian_filter((discs & (change > 2 * noise)).astype(np.float32), 1.5)
    mask = np.clip(mask * 1.6, 0, 1) * ndimage.gaussian_filter(discs.astype(np.float32), 1.0)
    # On a noisy stack Dark Star also lowers the broad level, which showed as dark discs.
    small = ndimage.median_filter((u - ds)[::4, ::4], 31)
    broad = ndimage.zoom(small, (rows / small.shape[0], cols / small.shape[1]), order=1)
    return (u - mask * np.maximum(u - ds - broad, 0)).astype(np.float32)


def remove_stars(plane, noise=None):
    """One linear plane without its stars, by Seti Astro Suite Pro's Dark Star, blended. `noise` is the plane's
    grain before any noise reduction (`grain`), which sets the stretch as in the tests; by default the plane's own.
    NaNs stay NaN; a pixel the blend leaves alone keeps its own value exactly."""
    plane = np.asarray(plane, dtype=np.float32)
    good = np.isfinite(plane)
    if not good.any():
        raise ToolUnavailable("the stack has no valid pixels")
    filled = np.where(good, plane, float(np.median(plane[good])))
    forward, back = _stretch(filled, grain(filled) if noise is None else noise)
    u = forward(filled)
    starless = _blend(u, _darkstar(u))
    out = np.where(starless != u, back(starless), filled)
    return np.where(good, out, np.nan).astype(np.float32)


def remove_stars_together(planes, noises=None):
    """Several lined-up linear planes (a picture's filters, {band: plane}) without their stars, each star decided
    once for all of them: a star found in any filter is taken out of every filter Dark Star took it from. Decided
    filter by filter, a close double read as not round in one filter only and stayed there in that filter's
    colour, red or blue in NGC 2174 (24 November 2026)."""
    noises = noises or {}
    work = {}
    for band, plane in planes.items():
        plane = np.asarray(plane, dtype=np.float32)
        good = np.isfinite(plane)
        if not good.any():
            raise ToolUnavailable(f"the {band} stack has no valid pixels")
        filled = np.where(good, plane, float(np.median(plane[good])))
        forward, back = _stretch(filled, noises.get(band) or grain(filled))
        u = forward(filled)
        ds = _darkstar(u)
        work[band] = (good, filled, back, u, ds)
    shapes = {w[3].shape for w in work.values()}
    if len(shapes) != 1:
        raise ToolUnavailable(f"the planes are not the same size: {sorted(shapes)}")
    discs = np.zeros(shapes.pop(), bool)
    for good, filled, back, u, ds in work.values():
        discs |= _discs(u, *_change(u, ds))
    out = {}
    for band, (good, filled, back, u, ds) in work.items():
        starless = _blend(u, ds, discs)
        out[band] = np.where(good, np.where(starless != u, back(starless), filled), np.nan).astype(np.float32)
    return out


def status():
    for tool, entry in TOOLS.items():
        program = find(tool)
        if program:
            found = version(tool)
            tried = "" if found == TESTED[tool] else f"; tried with {TESTED[tool]}"
            print(f"{entry['name']}: {found or 'version not reported'} at {program} ({entry['for']}{tried})")
        else:
            how = f", {entry['how']}" if entry["how"] else ""
            print(f"{entry['name']}: not installed ({entry['for']}). Get it from {entry['url']}{how}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="what", required=True)
    sub.add_parser("status")
    d = sub.add_parser("denoise")
    d.add_argument("input", type=Path)
    d.add_argument("output", type=Path)
    d.add_argument("--strength", type=float, default=STRENGTH)
    s = sub.add_parser("stars")
    s.add_argument("input", type=Path)
    s.add_argument("output", type=Path)
    args = ap.parse_args()
    if args.what == "status":
        return status()
    if args.what == "denoise" and not 0 < args.strength <= 1:
        sys.exit("--strength is above 0 and at most 1")
    if args.output.exists() or args.output.resolve() == args.input.resolve():
        sys.exit(f"{args.output} exists: this never writes over a file")
    with fits.open(args.input) as f:
        data, header = f[0].data.astype(np.float32), f[0].header.copy()
    step = (lambda p: denoise(p, args.strength)) if args.what == "denoise" else remove_stars
    try:
        out = np.stack([step(p) for p in data]) if data.ndim == 3 else step(data)
    except ToolUnavailable as e:
        sys.exit(str(e))
    if args.what == "denoise":
        header["HISTORY"] = f"GraXpert {version('graxpert') or '?'} denoise, strength {args.strength:g}: not for measurement"
    else:
        header["HISTORY"] = f"Seti Astro Suite Pro {version('setiastro') or '?'} Dark Star, blended: not for measurement"
    fits.PrimaryHDU(out, header).writeto(args.output)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
