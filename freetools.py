#!/usr/bin/env python3
"""The free image-processing tools TelescopeYoke can drive. Each person installs their own.

    ./freetools.py status                         which tools are here, and where to get the rest
    ./freetools.py denoise IN.fits OUT.fits       GraXpert's noise reduction on a copy of a stack

The tools are separate programs and are never bundled. They work on temporary copies: a
stack is only read, and what they make is for pictures, never for measurements.
TY_GRAXPERT, TY_SIRIL and TY_COSMIC_CLARITY name a program that is not on the PATH.
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

STRENGTH = 0.6      # about half the grain on this rig's stacks (23 November 2026)
RUN_LIMIT = 3 * 3600

TOOLS = {
    "graxpert": {"name": "GraXpert", "env": "TY_GRAXPERT", "programs": ("GraXpert", "graxpert"),
                 "for": "noise reduction, background, deconvolution", "url": "https://graxpert.com/"},
    "siril": {"name": "Siril", "env": "TY_SIRIL", "programs": ("siril-cli",),
              "for": "stretch, colour calibration, stacking comparisons", "url": "https://siril.org/download/"},
    "cosmicclarity": {"name": "Cosmic Clarity", "env": "TY_COSMIC_CLARITY",
                      "programs": ("SetiAstroCosmicClarity_denoise",),
                      "for": "noise reduction, sharpening, star removal", "url": "https://www.setiastro.com/cosmic-clarity"},
}


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
    extra = os.environ.get("TY_GRAXPERT_LIBS") if tool == "graxpert" else None
    if extra:
        env["LD_LIBRARY_PATH"] = extra + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    return env


def version(tool):
    program = find(tool)
    if not program or tool == "cosmicclarity":     # it has no version option
        return None
    try:
        done = subprocess.run([program, "--version"], capture_output=True, text=True, timeout=60, env=tool_env(tool),
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


def status():
    for tool, entry in TOOLS.items():
        program = find(tool)
        if program:
            print(f"{entry['name']}: {version(tool) or 'version not reported'} at {program} ({entry['for']})")
        else:
            print(f"{entry['name']}: not installed ({entry['for']}). Get it from {entry['url']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="what", required=True)
    sub.add_parser("status")
    d = sub.add_parser("denoise")
    d.add_argument("input", type=Path)
    d.add_argument("output", type=Path)
    d.add_argument("--strength", type=float, default=STRENGTH)
    args = ap.parse_args()
    if args.what == "status":
        return status()
    if not 0 < args.strength <= 1:
        sys.exit("--strength is above 0 and at most 1")
    if args.output.exists() or args.output.resolve() == args.input.resolve():
        sys.exit(f"{args.output} exists: this never writes over a file")
    with fits.open(args.input) as f:
        data, header = f[0].data.astype(np.float32), f[0].header.copy()
    try:
        out = np.stack([denoise(p, args.strength) for p in data]) if data.ndim == 3 else denoise(data, args.strength)
    except ToolUnavailable as e:
        sys.exit(str(e))
    header["HISTORY"] = f"GraXpert {version('graxpert') or '?'} denoise, strength {args.strength:g}: not for measurement"
    fits.PrimaryHDU(out, header).writeto(args.output)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
