#!/usr/bin/env python3
"""Variable stars in the frames already taken: light curves of every star
bright enough, and the ones that vary more than their brightness allows.

    ./variables.py M31                every session of M31 with frames enough
    ./variables.py M31 --session 20261014-021118 --session 20261006-214958
    ./variables.py M31 --bin 20 --json
    ./variables.py M31 --offline      without asking VSX which are known

Each night's frames (those restack.py kept) are stacked in batches of
--bin, all lined up on the night's first frame, so each batch is one point
of a light curve. Every Gaia star in the picture between BRIGHTEST and
FAINTEST, with no other star near enough to share its light and not on
a galaxy's bright glow, is measured in every batch at its Gaia place.
Each batch is put on Gaia's G scale by a smooth surface fitted over the
picture to all those stars, so haze, the height of the field, and the
vignetting each night's pointing puts in a different place (there are no
flats) all cancel. Each night's measurements are kept in its session
(variables-BIN.json), so judging them again does not stack again.
A star's scatter is then set beside the scatter of the stars as bright as
it: one that scatters LOUD times more than they do, over LEAST points or
more, is listed. VSX is asked which stars are known variables: a known one
found is the proof that this works, and one that VSX does not have is a
candidate new variable for a person to look at, not a discovery yet.

Kept as frames/FIELD/variables.json with each listed star's light curve,
and a picture of each curve beside it. Nothing here moves the mount or
uses the camera; reporting a new variable to VSX is a person's decision.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.time import Time
from scipy.spatial import cKDTree

import config
import interface

BIN = 10             # frames in each point of a light curve
BRIGHTEST = 10.5     # G: brighter stars fill the camera's wells
FAINTEST = 16.0      # G: fainter ones are too noisy in one batch
ALONE = 15.0         # arcseconds: a star with a neighbour within this, less than CROWD mag fainter, shares its light
CROWD = 3.0
MARGIN = 60          # pixels from the edge of the picture
LOUD = 3.0           # scatter this many times its brightness's usual scatter is variable
LEAST = 8            # points a light curve needs before it can be called variable
MATCH = 6.0          # arcseconds to a VSX star
GLOW = 1.5           # a star on light this many times the picture's median sky is on a galaxy: left out
SURFACE = 30         # stars a batch needs before its zero point is a surface rather than one number
VERSION = 1          # of the kept measurements: a change in what is measured makes them again
STEP = 0.5           # magnitudes in each bin of the usual scatter


# --- measuring ---------------------------------------------------------------

def sessions_of(name, least):
    """The sessions of a field with at least `least` kept frames, oldest first."""
    import stacking
    import vet
    folder = config.DATA / "frames" / stacking.folder_name(name)
    return [s for s in sorted(p for p in folder.glob("*") if p.is_dir() and any(p.glob("light-*.fits")))
            if len(vet.restack_frames(s)) >= least]


def batches(paths, size):
    """The frames in groups of `size`; a last group under half that is left out."""
    groups = [paths[i:i + size] for i in range(0, len(paths), size)]
    return [g for g in groups if len(g) >= max(2, size // 2)]


def middle_time(paths):
    """The middle of a batch of frames, as a Julian date."""
    import stacking
    stamps = []
    for p in paths:
        head = stacking.load_light(p)[1]
        if head.get("DATE-OBS"):
            stamps.append(Time(head["DATE-OBS"]).jd + float(head.get("EXPTIME", 0)) / 2 / 86400)
    return float(np.mean(stamps)) if stamps else None


def placed(stars, wcs, shape, brightest=BRIGHTEST, faintest=FAINTEST):
    """The Gaia stars in range and inside the picture: their rows, pixel
    places, and whether each is alone (no neighbour within ALONE less than
    CROWD mag fainter, among all the stars given)."""
    stars = np.asarray(stars, float)
    if not len(stars):
        return stars, np.zeros((0, 2)), np.zeros(0, bool)
    x, y = wcs.world_to_pixel_values(stars[:, 0], stars[:, 1])
    inside = (x >= MARGIN) & (y >= MARGIN) & (x < shape[1] - MARGIN) & (y < shape[0] - MARGIN)
    cosd = math.cos(math.radians(float(np.median(stars[:, 1]))))
    tree = cKDTree(np.column_stack([stars[:, 0] * cosd, stars[:, 1]]) * 3600)
    rows = np.nonzero(inside & (stars[:, 2] >= brightest) & (stars[:, 2] <= faintest))[0]
    alone = np.array([all(j == i or stars[j, 2] > stars[i, 2] + CROWD
                          for j in tree.query_ball_point((stars[i, 0] * cosd * 3600, stars[i, 1] * 3600), ALONE))
                      for i in rows], bool)
    return stars[rows], np.column_stack([x[rows], y[rows]]) if len(rows) else np.zeros((0, 2)), alone


def chosen(stars, wcs, shape, brightest=BRIGHTEST, faintest=FAINTEST):
    """The Gaia stars worth a light curve: in range, inside the picture, and
    alone. Returns their rows and pixel places."""
    rows, xy, alone = placed(stars, wcs, shape, brightest, faintest)
    return rows[alone], xy[alone]


def surface(xy, values, rounds=3):
    """A smooth surface (x, y and their squares and product) through the
    values at the places, refitted with the far-off ones left out."""
    xy = np.asarray(xy, float)
    scale = np.maximum(np.abs(xy).max(axis=0), 1.0)
    u, v = (xy / scale).T
    design = np.column_stack([np.ones_like(u), u, v, u * u, v * v, u * v])
    use = np.isfinite(values)
    fit = None
    for _ in range(rounds):
        if use.sum() < design.shape[1] * 3:
            break
        fit, *_ = np.linalg.lstsq(design[use], values[use], rcond=None)
        left = values - design @ fit
        spread = 1.4826 * np.nanmedian(np.abs(left[use] - np.nanmedian(left[use])))
        use = np.isfinite(values) & (np.abs(left) <= 3 * max(spread, 1e-3))
    if fit is None:
        return np.full(len(values), np.nanmedian(values))
    return design @ fit


def on_gaia(fluxes, g, xy=None):
    """Each batch's measured light put on Gaia's G scale: by a smooth
    surface over the picture through all its stars where they are many
    (with `xy`), else by their median. Rows of batches, columns of stars,
    NaN where unmeasured."""
    fluxes = np.asarray(fluxes, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        inst = np.where(fluxes > 0, -2.5 * np.log10(fluxes), np.nan)
    offsets = g[None, :] - inst
    out = np.empty_like(inst)
    for b in range(len(inst)):
        if xy is not None and np.isfinite(offsets[b]).sum() >= SURFACE:
            out[b] = inst[b] + surface(xy, offsets[b])
        else:
            out[b] = inst[b] + np.nanmedian(offsets[b])
    return out


def measure(lum, xy, fwhm):
    """The light of each star in one stack, weighted by a star's shape."""
    import difference
    import forced
    flat = lum - difference.glow(lum)
    return forced.weighted(flat, xy, fwhm, max(fwhm, 2.0))


def plain(values):
    """Numbers for JSON: NaN as null."""
    return [None if v is None or not np.isfinite(v) else round(float(v), 6) for v in values]


def measured(session, name, size, say=print, stack=None, solve=None, gaia=None):
    """One night's measurements of every Gaia star in range in every batch,
    kept in the session (variables-BIN.json) and read back from there."""
    import depth
    import difference
    import stacking
    import vet
    kept = session / f"variables-{size}.json"
    if kept.exists():
        record = json.loads(kept.read_text(encoding="utf-8"))
        if record.get("version") == VERSION:
            say(f"{session.name}: {len(record['jd'])} batches of {size} frames, as measured before")
            return record
    stack = stack or vet.stacked
    solve = solve or (lambda lum: depth.plate(lum, name))
    gaia = gaia or depth.gaia
    groups = batches(vet.restack_frames(session), size)
    if len(groups) < 2:
        raise interface.Refusal("NO_SESSION", f"{session.name}: too few frames for {size}-frame batches.")
    say(f"{session.name}: {len(groups)} batches of {size} frames")
    images = stack(groups)
    wcs = solve(images[0])
    h, w = images[0].shape
    corners = wcs.pixel_to_world_values([0, w, 0, w, w / 2], [0, 0, h, h, h / 2])
    ra, dec = float(corners[0][4]), float(corners[1][4])
    reach = float(vet.separation(ra, dec, np.array(corners[0][:4]), np.array(corners[1][:4])).max()) / 3600
    stars, xy, alone = placed(gaia(ra, dec, round(reach + 0.01, 2)), wcs, (h, w))
    found = stacking.find_stars(images[0], limit=2000)
    fwhm = float(np.median(found[:200, 3])) if len(found) else 4.0
    light = difference.glow(images[0])
    sky = float(np.nanmedian(light))
    under = [float(light[int(round(y)), int(round(x))]) / sky if sky > 0 else 1.0 for x, y in xy]
    record = {"version": VERSION, "session": session.name, "bin": size, "fwhm_px": round(fwhm, 2),
              "jd": [middle_time(g) for g in groups],
              "stars": [plain(row) + [None] * (4 - len(row)) for row in stars], "xy": [plain(p) for p in xy],
              "alone": [bool(a) for a in alone], "glow": plain(under),
              "flux": [plain(measure(image, xy, fwhm)) for image in images]}
    kept.write_text(json.dumps(record), encoding="utf-8")
    return record


def night(session, name, size, say=print, stack=None, solve=None, gaia=None):
    """One night's light curves: the batches' times, and their magnitudes
    for the stars alone and off any galaxy's glow."""
    r = measured(session, name, size, say, stack, solve, gaia)
    stars = np.array([[np.nan if v is None else v for v in row] for row in r["stars"]], float).reshape(-1, 4)
    flux = np.array([[np.nan if v is None else v for v in row] for row in r["flux"]], float)
    xy = np.array(r["xy"], float).reshape(-1, 2)
    glow = np.array([np.inf if v is None else v for v in r["glow"]], float)
    keep = np.array(r["alone"], bool) & (glow <= GLOW)
    mags = on_gaia(flux[:, keep], stars[keep, 2], xy[keep])
    return {"session": r["session"], "jd": r["jd"], "stars": stars[keep], "mags": mags, "fwhm_px": r["fwhm_px"]}


# --- judging -----------------------------------------------------------------

def key(ra, dec):
    return f"{ra:.5f}{dec:+.5f}"


def gather(nights):
    """Every star's light curve over all the nights: {key: {ra, dec, g, colour,
    jd: [...], mag: [...]}}."""
    curves = {}
    for n in nights:
        for j, row in enumerate(n["stars"]):
            c = curves.setdefault(key(row[0], row[1]), {"ra": float(row[0]), "dec": float(row[1]),
                                                        "g": float(row[2]),
                                                        "colour": None if len(row) < 4 or not np.isfinite(row[3])
                                                        else float(row[3]),
                                                        "jd": [], "mag": [], "session": []})
            for t, m in zip(n["jd"], n["mags"][:, j]):
                if np.isfinite(m) and t is not None:
                    c["jd"].append(float(t))
                    c["mag"].append(float(m))
                    c["session"].append(n["session"])
    return curves


def scatter(mags):
    """A light curve's scatter, robust to one bad point."""
    mags = np.asarray(mags, float)
    return 1.4826 * float(np.median(np.abs(mags - np.median(mags))))


def usual(curves, step=STEP):
    """The usual scatter at each brightness: the median over the stars in
    each STEP-magnitude bin, as a function of magnitude."""
    rows = [(float(np.median(c["mag"])), scatter(c["mag"])) for c in curves.values() if len(c["mag"]) >= LEAST]
    if not rows:
        return lambda m: float("nan")
    mags, spreads = np.array(rows).T
    edges = np.arange(math.floor(mags.min()), math.ceil(mags.max()) + step, step)
    centres, levels = [], []
    for lo in edges:
        inside = (mags >= lo) & (mags < lo + step)
        if inside.sum() >= 5:
            centres.append(lo + step / 2)
            levels.append(float(np.median(spreads[inside])))
    if not centres:
        level = float(np.median(spreads))
        return lambda m: level
    return lambda m: float(np.interp(m, centres, levels))


def judge(curves, known=(), loud=LOUD, least=LEAST):
    """Each star's scatter beside the usual for its brightness; the loud
    ones and every VSX star, with their light curves."""
    expected = usual(curves)
    tree = None
    if known:
        cosd = math.cos(math.radians(float(np.median([k["dec"] for k in known]))))
        tree = cKDTree([(k["ra"] * cosd * 3600, k["dec"] * 3600) for k in known])
    out = []
    for c in curves.values():
        if len(c["mag"]) < least:
            continue
        mag, spread = float(np.median(c["mag"])), scatter(c["mag"])
        ratio = spread / expected(mag) if expected(mag) > 0 else float("nan")
        vsx = None
        if tree is not None:
            d, i = tree.query((c["ra"] * cosd * 3600, c["dec"] * 3600))
            if d <= MATCH:
                vsx = known[i]
        if ratio >= loud or vsx:
            lo, hi = np.percentile(c["mag"], [5, 95])
            out.append({"ra": round(c["ra"], 5), "dec": round(c["dec"], 5), "g": round(c["g"], 2),
                        "colour": None if c["colour"] is None else round(c["colour"], 2),
                        "points": len(c["mag"]), "median": round(mag, 3), "scatter": round(spread, 3),
                        "usual": round(expected(mag), 3), "loudness": round(ratio, 1),
                        "range": round(float(hi - lo), 3), "variable": bool(ratio >= loud),
                        "vsx": None if vsx is None else {"name": vsx["name"], "type": vsx["type"]},
                        "jd": [round(t, 5) for t in c["jd"]], "mag": [round(m, 3) for m in c["mag"]],
                        "session": c["session"]})
    return sorted(out, key=lambda s: (s["vsx"] is not None, -s["loudness"]))


# --- showing -----------------------------------------------------------------

def draw(star, path, size=(640, 320)):
    """A light curve as a picture: brighter up, each night's points in turn."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, "white")
    pen = ImageDraw.Draw(image)
    jd, mag = np.array(star["jd"]), np.array(star["mag"])
    nights = sorted(set(star["session"]))
    # Each night side by side, as the gaps between them are days long.
    slot = (size[0] - 60) / max(len(nights), 1)
    lo, hi = float(mag.min()) - 0.05, float(mag.max()) + 0.05
    for k, n in enumerate(nights):
        pick = np.array([s == n for s in star["session"]])
        t = jd[pick]
        span = max(float(t.max() - t.min()), 1e-6)
        left = 50 + k * slot
        pen.text((left + 4, size[1] - 16), f"{n[4:6]}-{n[6:8]} {n[9:11]}:{n[11:13]}", fill="grey")
        for tt, mm in zip(t, mag[pick]):
            x = left + 6 + (tt - t.min()) / span * (slot - 12)
            y = 10 + (mm - lo) / (hi - lo) * (size[1] - 40)
            pen.ellipse([x - 3, y - 3, x + 3, y + 3], fill="black")
    pen.text((4, 4), f"{lo:.2f}", fill="grey")                    # brighter at the top
    pen.text((4, size[1] - 34), f"{hi:.2f}", fill="grey")
    title = star["vsx"]["name"] if star["vsx"] else f"{star['ra']:.5f} {star['dec']:+.5f}"
    pen.text((60, 4), f"{title}  G {star['g']:.2f}  scatter {star['scatter']:.3f} ({star['loudness']}x usual)",
             fill="black")
    image.save(path)
    return str(path)


def run(args, say=print):
    if config.DEMO:
        raise interface.Refusal("DEMO_UNSUPPORTED", "Light curves need real frames.")
    import depth
    import stacking
    import vet
    folder = config.DATA / "frames" / stacking.folder_name(args.name)
    sessions = [folder / s for s in args.session] if args.session else sessions_of(args.name, 2 * args.bin)
    if not sessions:
        raise interface.Refusal("NO_SESSION", f"No session of {args.name} with {2 * args.bin} frames or more.")
    nights, skipped = [], []
    for s in sessions:
        try:
            nights.append(night(s, args.name, args.bin, say))
        except interface.Refusal as error:
            say(f"  {s.name}: left out: {error}")
            skipped.append({"session": s.name, "why": str(error)})
    if not nights:
        raise interface.Refusal("NO_SESSION", "No night could be measured.")
    curves = gather(nights)
    known = []
    if not args.offline:
        stars = np.array([(c["ra"], c["dec"]) for c in curves.values()])
        ra, dec = float(np.median(stars[:, 0])), float(np.median(stars[:, 1]))
        reach = float(vet.separation(ra, dec, stars[:, 0], stars[:, 1]).max()) / 3600 + 0.02
        try:
            known = vet.variables(ra, dec, reach)
        except requests.RequestException as error:
            say(f"  VSX not asked ({error.__class__.__name__})")
    listed = judge(curves, known)
    out = folder / "variables"
    out.mkdir(parents=True, exist_ok=True)
    for s in listed:
        s["picture"] = draw(s, out / f"{key(s['ra'], s['dec'])}.png")
    measured = sum(len(c["mag"]) >= LEAST for c in curves.values())
    new = [s for s in listed if s["variable"] and not s["vsx"]]
    found = [s for s in listed if s["variable"] and s["vsx"]]
    quiet = [s for s in listed if not s["variable"]]
    answer = {"field": args.name, "bin": args.bin, "sessions": [n["session"] for n in nights], "skipped": skipped,
              "stars": measured, "vsx_asked": not args.offline,
              "known_found": len(found), "known_quiet": len(quiet), "candidates": len(new),
              "stars_listed": listed, "kind": "measured"}
    (folder / "variables.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
    say(f"{measured} stars measured over {len(nights)} nights in batches of {args.bin} frames")
    for s in found:
        say(f"  known, and seen to vary: {s['vsx']['name']} ({s['vsx']['type']}), G {s['median']:.2f}, "
            f"scatter {s['scatter']:.3f} = {s['loudness']}x usual")
    for s in quiet:
        say(f"  known, flat here: {s['vsx']['name']} ({s['vsx']['type']}), G {s['median']:.2f}, "
            f"scatter {s['scatter']:.3f} = {s['loudness']}x usual")
    for s in new:
        say(f"  NOT IN VSX: RA {s['ra']:.5f} Dec {s['dec']:+.5f}, G {s['median']:.2f}, scatter {s['scatter']:.3f} = "
            f"{s['loudness']}x usual, range {s['range']:.2f}: {s['picture']}")
    if new:
        say("Look at each curve. A real variable repeats on another night; a blend or an edge does not.")
    say(f"kept as {folder / 'variables.json'}")
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="the field, as the frames' folder is named (M31)")
    ap.add_argument("--session", action="append", help="one session folder's name (repeat for more; default all)")
    ap.add_argument("--bin", type=int, default=BIN, help=f"frames in each point (default {BIN})")
    ap.add_argument("--offline", action="store_true", help="do not ask VSX which stars are known")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("variables", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
