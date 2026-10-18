#!/usr/bin/env python3
"""Every night's frames of a mosaic as one picture, growing night by night.

    ./stitch.py M31                 restack what is new, then join every panel into one picture
    ./stitch.py M31 --on desktop    the restacking done on the desktop (remote.py)
    ./stitch.py M31 --dry-run       say what would be restacked and joined; nothing is done

Each field of the mosaic (its panels, M31-P1 to M31-P8, and the object
itself when it was also taken whole) is restacked with every session it has,
from every night (restack.py --all), but only when a session has been added
since the last time: what was used is kept in mosaics/NAME-stitch.json. Each
field's deep stack is plate-solved, resampled onto one sky grid (north up,
the panels' own scale), its sky level taken off, and the fields are blended
where they overlap: each pixel weighted by how far it is from its field's
edge, so no seam shows, and by how deep the field is (its exposure). The
whole is then finished as every picture is (process.py).

Kept as mosaics/NAME-mosaic.fits (the linear blend, colour planes first) and
web/NAME-mosaic.jpg. The patrol runs this in the background when it ends,
so the picture grows with every night's frames by itself. Nothing here moves
the mount or uses the camera.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from scipy import ndimage

import config
import interface
import records

ROOT = Path(__file__).parent
FEATHER = 150           # pixels over which a field fades in from its edge
SAMPLE = 8              # the sky level of a field is taken from every 8th pixel


def fields(name):
    """The fields that make up NAME's picture: its mosaic panels, and the
    object itself if it was taken whole."""
    import mosaic
    plan = mosaic.load(name)
    if not plan:
        raise interface.Refusal("NO_SESSION", f"{name} has no mosaic plan (mosaic.py {name}).")
    found = [p["id"] for p in plan["panels"]]
    if sessions(name):
        found.append(name)
    return found


def sessions(field):
    """Every saved session of a field with raw frames, oldest first."""
    base = config.DATA / "frames" / field
    if not base.is_dir():
        return []
    return sorted(d for d in base.iterdir()
                  if d.is_dir() and d.name != "combined" and any(d.glob("light-*.fits")))


def stack_of(field):
    """Where restack.py --all leaves a field's picture: the session itself
    when it has only one, else the combined folder."""
    found = sessions(field)
    if not found:
        return None
    return (found[0] if len(found) == 1 else found[0].parent / "combined") / "final.fits"


def record_path(name):
    return config.DATA / "mosaics" / f"{name.lower()}-stitch.json"


def stale(name, field, kept):
    """Whether a field has a session its last deep stack did not use."""
    used = set(kept.get(field, []))
    found = [s.name for s in sessions(field)]
    stack = stack_of(field)
    return bool(found) and (set(found) != used or stack is None or not stack.exists())


def restack(field, host=None, run=subprocess.run):
    """Restack every session of a field as one picture."""
    cmd = [sys.executable, str(ROOT / "restack.py"), field, "--all"] + (["--on", host] if host else [])
    done = run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if done.returncode != 0:
        last = (done.stderr or "").strip().splitlines()[-1:]
        raise interface.Refusal("INVALID_REQUEST", f"Restacking {field} failed: {last[0] if last else 'no reason given'}")


def grid(placed, scale=None):
    """One north-up tangent-plane grid covering every placed field: [(wcs,
    shape)]. Its scale is the fields' own, so nothing is enlarged."""
    corners = []
    scales = []
    for wcs, shape in placed:
        rows, cols = shape
        corners += [wcs.pixel_to_world_values(x, y) for x, y in
                    ((0, 0), (cols - 1, 0), (0, rows - 1), (cols - 1, rows - 1))]
        scales.append(np.sqrt(abs(np.linalg.det(wcs.pixel_scale_matrix))))
    corners = np.array(corners)
    ra0 = float(np.degrees(np.arctan2(np.sin(np.radians(corners[:, 0])).mean(),
                                      np.cos(np.radians(corners[:, 0])).mean()))) % 360
    dec0 = float(corners[:, 1].mean())
    step = scale or float(np.median(scales))
    out = WCS(naxis=2)
    out.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    out.wcs.crval = [ra0, dec0]
    out.wcs.crpix = [1, 1]
    out.wcs.cdelt = [-step, step]
    x, y = out.world_to_pixel_values(corners[:, 0], corners[:, 1])
    x0, y0 = np.floor(x.min()), np.floor(y.min())
    out.wcs.crpix = [1 - x0, 1 - y0]
    shape = (int(np.ceil(y.max() - y0)) + 1, int(np.ceil(x.max() - x0)) + 1)
    return out, shape


def resample(planes, wcs, out_wcs, out_shape):
    """A field's colour planes on the grid's pixels, and where it covers."""
    rows, cols = out_shape
    yy, xx = np.mgrid[0:rows, 0:cols]
    ra, dec = out_wcs.pixel_to_world_values(xx.ravel(), yy.ravel())
    nx, ny = wcs.world_to_pixel_values(ra, dec)
    h, w = planes.shape[1:]
    inside = (nx >= 0) & (nx <= w - 1) & (ny >= 0) & (ny <= h - 1)
    out = np.zeros((planes.shape[0], rows * cols), np.float32)
    for c, plane in enumerate(planes):
        finite = np.isfinite(plane)
        filled = np.where(finite, plane, 0).astype(np.float32)
        out[c, inside] = ndimage.map_coordinates(filled, [ny[inside], nx[inside]], order=1)
    return out.reshape(planes.shape[0], rows, cols), inside.reshape(rows, cols)


def blend(fields_in, out_wcs, out_shape, feather=FEATHER):
    """[(planes, wcs, depth)] blended onto the grid: each field's sky level
    taken off, then a mean weighted by distance from the field's edge and by
    its depth (seconds of exposure)."""
    total = np.zeros((3,) + tuple(out_shape), np.float32)
    weights = np.zeros(out_shape, np.float32)
    for planes, wcs, depth in fields_in:
        laid, covered = resample(planes, wcs, out_wcs, out_shape)
        if not covered.any():
            continue
        for c in range(laid.shape[0]):
            laid[c] -= np.median(laid[c][covered][::SAMPLE])
        edge = ndimage.distance_transform_edt(covered)
        w = np.clip(edge / feather, 0, 1).astype(np.float32) * float(depth)
        total += laid * w
        weights += w
    out = np.where(weights > 0, total / np.maximum(weights, 1e-9), 0).astype(np.float32)
    return out, weights


def depth_of(field):
    """Seconds of exposure in a field's deep stack, from its restack record."""
    stack = stack_of(field)
    try:
        record = json.loads((stack.parent / "restack.json").read_text(encoding="utf-8"))
        return float(record["summary"]["total_exposure_s"]) or 1.0
    except (OSError, ValueError, AttributeError, TypeError):
        return 1.0


def run(name, host=None, dry_run=False, say=print, solver=None, restacker=None):
    """Restack what is new, then join every field into one picture."""
    import depth
    path = record_path(name)
    kept = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    names = fields(name)
    todo = [f for f in names if stale(name, f, kept)]
    answer = {"mosaic": name, "fields": names, "restacked": todo}
    if dry_run:
        say(f"{name}: {len(names)} fields; would restack {', '.join(todo) or 'none'}, then join them all.")
        return dict(answer, dry_run=True)
    for field in todo:
        say(f"restacking {field}: {len(sessions(field))} sessions")
        (restacker or restack)(field, host)
        kept[field] = [s.name for s in sessions(field)]
        path.parent.mkdir(parents=True, exist_ok=True)
        records.write(path, kept)
    placed, inputs = [], []
    for field in names:
        stack = stack_of(field)
        if stack is None or not stack.exists():
            say(f"  {field}: no stack yet, left out")
            continue
        planes = np.asarray(fits.getdata(stack), dtype=np.float32)
        try:
            wcs = (solver or (lambda lum, f: depth.plate(lum, f)))(depth.brightness(planes), field)
        except interface.Refusal as refused:
            say(f"  {field}: {refused.message} Left out.")
            continue
        placed.append((wcs, planes.shape[1:]))
        inputs.append((planes, wcs, depth_of(field)))
        say(f"  {field}: placed")
    if not inputs:
        raise interface.Refusal("NO_SESSION", f"No field of {name} could be placed.")
    out_wcs, out_shape = grid(placed)
    say(f"joining {len(inputs)} fields onto {out_shape[1]} x {out_shape[0]} pixels")
    joined, weights = blend(inputs, out_wcs, out_shape)
    folder = config.DATA / "mosaics"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{name}-mosaic.fits"
    header = out_wcs.to_header()
    header["OBJECT"] = name
    header["NFIELDS"] = len(inputs)
    fits.PrimaryHDU(joined, header).writeto(out, overwrite=True)
    import process
    from PIL import Image
    picture = process.process(np.moveaxis(joined, 0, -1), background=process.sky_for(name))
    picture[weights == 0] = 0
    web = config.DATA / "web" / f"{name}-mosaic.jpg"
    web.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(picture).save(web, quality=92)
    say(f"saved {out} and {web}")
    return dict(answer, joined=len(inputs), size=[out_shape[1], out_shape[0]], fits=str(out), picture=str(web),
                saved=time.time())


def later(name, start=subprocess.Popen):
    """Stitch in the background at low priority, its lines in
    mosaics/NAME-stitch.log: the patrol calls this when it ends."""
    import os
    folder = config.DATA / "mosaics"
    folder.mkdir(parents=True, exist_ok=True)
    lowly = {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == "nt" else \
        {"preexec_fn": lambda: os.nice(19), "start_new_session": True}
    with open(folder / f"{name}-stitch.log", "w", encoding="utf-8") as log:
        start([sys.executable, str(ROOT / "stitch.py"), name], stdout=log, stderr=subprocess.STDOUT,
              stdin=subprocess.DEVNULL, **lowly)
    return str(folder / f"{name}-stitch.log")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="the mosaic, as mosaic.py names it (M31)")
    ap.add_argument("--on", metavar="HOST", help="restack on another computer, named in ~/.ssh/config")
    ap.add_argument("--dry-run", action="store_true", help="say what would be done; do nothing")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    return interface.main("stitch", lambda: run(args.name, args.on, args.dry_run), args.json)


if __name__ == "__main__":
    main()
