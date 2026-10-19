#!/usr/bin/env python3
"""Every night's frames of a mosaic as one picture, growing night by night.

    ./stitch.py M31                 every session of every panel, placed on the sky, as one picture
    ./stitch.py M31 --on desktop    a session with no stack yet is stacked on the desktop (remote.py)
    ./stitch.py M31 --dry-run       say what would be restacked and joined; nothing is done

Every session of every field of the mosaic (its panels, M31-P1 to M31-P8,
and the object itself when it was also taken whole) is used, each stacked on
its own (restack.py, for a session without a stack yet) and placed on the
sky by its own plate solve, kept in mosaics/NAME-stitch.json so it is solved
once. A session only has to line up with itself, so a camera turned between
nights changes nothing. Each is resampled onto one grid (the panels' own
scale, turned to the mosaic's angle), its sky level taken off, and all are
blended: each pixel weighted by how far it is from its session's edge, so no
seam shows, and by the session's exposure, so every new night adds depth
where it lands. The whole is then finished as every picture is (process.py).

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
SKY_SHARE = 20          # percentile of a field's pixels taken as its sky level


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


def record_path(name):
    return config.DATA / "mosaics" / f"{name.lower()}-stitch.json"


def grid(placed, scale=None, angle=None):
    """One tangent-plane grid covering every placed field: [(wcs, shape)].
    Its scale is the fields' own, so nothing is enlarged. Turned by `angle`
    (degrees, the mosaic's own; either way round, whichever box is smaller)
    so a tilted mosaic is not a picture of mostly empty corners; north up
    without one."""
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
    best = None
    for turn in ([0.0] if not angle else [float(angle), -float(angle)]):
        c, s_ = np.cos(np.radians(turn)), np.sin(np.radians(turn))
        out = WCS(naxis=2)
        out.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        out.wcs.crval = [ra0, dec0]
        out.wcs.crpix = [1, 1]
        out.wcs.cd = step * np.array([[-c, s_], [s_, c]])
        x, y = out.world_to_pixel_values(corners[:, 0], corners[:, 1])
        x0, y0 = np.floor(x.min()), np.floor(y.min())
        out.wcs.crpix = [1 - x0, 1 - y0]
        shape = (int(np.ceil(y.max() - y0)) + 1, int(np.ceil(x.max() - x0)) + 1)
        if best is None or shape[0] * shape[1] < best[1][0] * best[1][1]:
            best = (out, shape)
    return best


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
        grain = []
        for c in range(laid.shape[0]):
            values = laid[c][covered][::SAMPLE]
            # The sky from the darker part: in a frame full of galaxy the
            # median is the galaxy, and taking it off left the whole-galaxy
            # field a dark rectangle in the middle (18 October 2026).
            sky = np.percentile(values, SKY_SHARE)
            dark = values[values <= np.percentile(values, 50)]
            grain.append(1.4826 * float(np.median(np.abs(dark - np.median(dark)))) + 1e-6)
            laid[c] -= sky
        # Deeper and cleaner counts more: exposure over the sky's grain
        # squared, so a striped or noisy session gives way where a better
        # one overlaps it.
        edge = ndimage.distance_transform_edt(covered)
        w = np.clip(edge / feather, 0, 1).astype(np.float32) * float(depth) / float(np.mean(grain)) ** 2
        total += laid * w
        weights += w
    out = np.where(weights > 0, total / np.maximum(weights, 1e-9), 0).astype(np.float32)
    return out, weights


def unstacked(field):
    """A field's sessions that have no stack of their own yet."""
    return [s for s in sessions(field) if not (s / "final.fits").exists()]


def restack(session, host=None, run=subprocess.run):
    """One session's own stack (restack.py)."""
    cmd = [sys.executable, str(ROOT / "restack.py"), str(session)] + (["--on", host] if host else [])
    done = run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if done.returncode != 0:
        last = (done.stderr or "").strip().splitlines()[-1:]
        raise interface.Refusal("INVALID_REQUEST", f"Restacking {session} failed: {last[0] if last else 'no reason given'}")


def exposure_of(session):
    """Seconds of exposure in a session's stack, from its restack record."""
    try:
        record = json.loads((Path(session) / "restack.json").read_text(encoding="utf-8"))
        return float(record["summary"]["total_exposure_s"]) or 1.0
    except (OSError, ValueError, KeyError, TypeError):
        return 1.0


def run(name, host=None, dry_run=False, say=print, solver=None, restacker=None):
    """Every session of every field of NAME, each stacked on its own and
    placed on the sky by its own plate solve, blended into one picture.
    Each session lines up only with itself, so frames from nights with the
    camera turned differently never have to line up with each other (18
    October 2026: restacking a panel's nights together, after the camera
    had been off for cleaning, matched its stars only to 6 px). A new
    session adds depth where it lands."""
    import depth
    import mosaic
    path = record_path(name)
    kept = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    solved = kept.setdefault("solved", {})
    names = fields(name)
    todo = [s for f in names for s in unstacked(f)]
    answer = {"mosaic": name, "fields": names, "restacked": [str(s) for s in todo]}
    if dry_run:
        say(f"{name}: {len(names)} fields, {sum(len(sessions(f)) for f in names)} sessions; would stack "
            f"{len(todo)} on their own, then place and join them all.")
        return dict(answer, dry_run=True)
    for session in todo:
        say(f"stacking {session.parent.name} {session.name}")
        try:
            (restacker or restack)(session, host)
        except interface.Refusal as refused:
            say(f"  {refused.message}")
    placed, inputs, left_out = [], [], []
    for field in names:
        for session in sessions(field):
            stack = session / "final.fits"
            if not stack.exists():
                continue
            planes = np.asarray(fits.getdata(stack), dtype=np.float32)
            key, stamp = str(session), stack.stat().st_mtime
            known = solved.get(key)
            if known and known.get("mtime") == stamp and solver is None:
                wcs = WCS(fits.Header.fromstring(known["header"], sep="\n")) if known.get("header") else None
            else:
                try:
                    lum = depth.brightness(planes)
                    wcs = (solver or (lambda image, f: depth.plate(image, f)))(lum, field)
                except interface.Refusal:
                    wcs = None
                solved[key] = {"mtime": stamp,
                               "header": wcs.to_header().tostring(sep="\n") if wcs is not None else None}
            if wcs is None:
                left_out.append(f"{field} {session.name}")
                continue
            placed.append((wcs, planes.shape[1:]))
            inputs.append((planes, wcs, exposure_of(session)))
    if solver is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        records.write(path, kept)
    if left_out:
        say(f"  would not plate-solve, left out: {', '.join(left_out)}")
    if not inputs:
        raise interface.Refusal("NO_SESSION", f"No session of {name} could be placed.")
    plan = mosaic.load(name) or {}
    out_wcs, out_shape = grid(placed, angle=plan.get("angle_deg"))
    say(f"joining {len(inputs)} sessions onto {out_shape[1]} x {out_shape[0]} pixels")
    joined, weights = blend(inputs, out_wcs, out_shape)
    folder = config.DATA / "mosaics"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{name}-mosaic.fits"
    header = out_wcs.to_header()
    header["OBJECT"] = name
    header["NSESSION"] = len(inputs)
    fits.PrimaryHDU(joined, header).writeto(out, overwrite=True)
    web = config.DATA / "web" / f"{name}-mosaic.jpg"
    web.parent.mkdir(parents=True, exist_ok=True)
    picture(joined, weights > 0, name).save(web, quality=92)
    say(f"saved {out} and {web}")
    return dict(answer, joined=len(inputs), left_out=left_out, size=[out_shape[1], out_shape[0]], fits=str(out),
                picture=str(web), saved=time.time())


def picture(joined, covered, name):
    """The blend finished as every picture is (process.py), from the part
    the sessions covered only: the empty corners would otherwise set the
    stretch, and the whole picture came out black."""
    import process
    from PIL import Image
    rows = np.flatnonzero(covered.any(axis=1))
    cols = np.flatnonzero(covered.any(axis=0))
    box = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
    rgb = np.moveaxis(joined[:, box[0], box[1]], 0, -1).copy()
    inside = covered[box]
    sky = np.median(rgb[inside][::SAMPLE], axis=0)
    rgb[~inside] = sky                     # the empty corners as plain sky, so they set nothing
    shown = process.process(rgb, background=0)
    shown[~inside] = 0
    return Image.fromarray(shown)


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
