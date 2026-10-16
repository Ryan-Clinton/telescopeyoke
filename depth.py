#!/usr/bin/env python3
"""How faint a stack really reaches, measured on the stack itself.

    ./depth.py M31                      the newest M31 session's stack
    ./depth.py frames/M31/20261014-021118
    ./depth.py M31 --plant              also plant fake stars and count how many are found
    ./depth.py M31 --sweep              the same on 60, 120, 180, 300 and 600 s of its frames
    ./depth.py M31 --json

The stack is plate-solved and its stars are matched to Gaia DR3, which gives
the zero point: the magnitude a star of one unit of brightness would have.
From the noise in empty patches of sky that gives the faintest star the
stack would show at 5 sigma. That figure is a formula's; --plant measures
instead. Copies of the stack's own stars, scaled to set magnitudes, are
added at random places and the star finder is run again: the share it
finds at each magnitude is the completeness, given separately for open sky
and for the parts of a galaxy of each brightness, since a star is harder to
see on a bright background. --sweep asks how much depth longer stacks buy.

Magnitudes are Gaia G: the camera has no filter, and G is the nearest of
Gaia's bands to what it sees. The record is kept as depth.json beside the
stack. Nothing here moves the mount or uses the camera; it needs the
internet once per field, for Gaia.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.wcs import WCS
from scipy import ndimage
from scipy.spatial import cKDTree

import config
import interface
import stacking

GAIA_URL = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
FAINTEST = 19.5           # Gaia stars fainter than this are no use to a 150P
CALIBRATORS = (11.0, 17.5)  # G range of the stars the zero point is taken from
MATCH = 2.0               # pixels: a detected star this close to a Gaia star is that star
SIGMA = 5.0               # the detection limit is quoted at 5 sigma
PSF_HALF = 15             # the stars' shape is kept in a square 31 pixels across
MAGNITUDES = tuple(np.arange(15.0, 19.51, 0.5))   # planted stars, from bright to faint
SPACING = 25              # pixels kept between planted stars, so they never blend with each other
SWEEP = (60, 120, 180, 300, 600)    # seconds of frames for --sweep
# Surface brightness of the smooth glow under a point, magnitudes per square
# arcsecond above the sky: where each kind of background begins. Open sky is
# anything fainter than the first. The figures suit M31; they are not
# special to it, and say nothing about which galaxy is in the frame.
REGIONS = (("sky", None), ("faint glow", 22.0), ("bright glow", 20.5), ("core", 19.0))


# --- the stack -----------------------------------------------------------------

def find_stack(name):
    """The stack to measure: a FITS file, a session folder, or an object's
    newest session."""
    import restack
    path = Path(name)
    if path.suffix.lower() in (".fits", ".fit"):
        return path
    session = restack.find_session(name)
    stack = session / "final.fits"
    if not stack.exists():
        raise interface.Refusal("NO_SESSION", f"{session} has no final.fits yet: run restack.py on it.")
    return stack


def object_name(stack):
    """The object a stack is of, from its folder: frames/NAME/<date-time>/final.fits."""
    parent = stack.parent
    return (parent.parent if parent.name[:1].isdigit() or parent.name == "combined" else parent).name


def brightness(rgb):
    """One brightness image from a stack's colour planes."""
    rgb = np.asarray(rgb, dtype=np.float32)
    return rgb.sum(axis=0) if rgb.ndim == 3 else rgb


# --- where the stars are, and Gaia ---------------------------------------------

def plate(lum, name):
    """The stack's WCS, from a plate solve near the object it is of."""
    import mount
    import solve
    target = mount.find_target(name)
    found = solve.solve(lum, target["ra"], target["dec"], radius=5)
    if not found or "cd" not in found:
        raise interface.Refusal("PLATE_SOLVE_FAILED", f"The stack of {name} would not plate-solve.")
    return wcs_from(found, lum.shape)


def wcs_from(found, shape):
    """A WCS from a plate solve: the solve's centre at the image's centre."""
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [found["ra"], found["dec"]]
    w.wcs.crpix = [(shape[1] + 1) / 2, (shape[0] + 1) / 2]
    w.wcs.cd = np.array(found["cd"])
    return w


def field(wcs, shape):
    """Centre and radius (degrees) of a circle round the whole image."""
    centre = wcs.pixel_to_world_values(shape[1] / 2, shape[0] / 2)
    corner = wcs.pixel_to_world_values(0, 0)
    ra0, dec0 = np.radians(centre)
    ra1, dec1 = np.radians(corner)
    apart = math.acos(min(1.0, math.sin(dec0) * math.sin(dec1)
                          + math.cos(dec0) * math.cos(dec1) * math.cos(ra0 - ra1)))
    return float(centre[0]), float(centre[1]), math.degrees(apart) * 1.05


def gaia(ra, dec, radius, faintest=FAINTEST):
    """Gaia DR3 stars in a circle, as an array of (ra, dec, G). Kept on disk:
    a field is fetched once."""
    store = config.DATA / "cache" / "gaia"
    path = store / f"{ra:.3f}_{dec:+.3f}_{radius:.2f}_{faintest:g}.tsv"
    if not path.exists():
        reply = requests.get(GAIA_URL, timeout=120, params={
            "-source": "I/355/gaiadr3", "-c": f"{ra:.5f} {dec:+.5f}", "-c.rd": f"{radius:.3f}",
            "-out": "RA_ICRS,DE_ICRS,Gmag", "-out.max": "200000", "Gmag": f"<{faintest:g}"})
        reply.raise_for_status()
        store.mkdir(parents=True, exist_ok=True)
        path.write_text(reply.text, encoding="utf-8")
    return read_tsv(path.read_text(encoding="utf-8"))


def read_tsv(text):
    """VizieR's tab-separated answer: comments, a header, units, a rule, rows."""
    rows = []
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    for line in lines[3:]:
        parts = line.split("\t")
        try:
            rows.append([float(p) for p in parts[:3]])
        except ValueError:
            continue    # a row with no G
    return np.array(rows, dtype=float).reshape(-1, 3)


# --- measuring -----------------------------------------------------------------

def background(lum, block=16, size=9):
    """The smooth glow under the stars: sky, gradient and galaxy, without
    the stars themselves."""
    h, w = lum.shape[0] // block * block, lum.shape[1] // block * block
    small = lum[:h, :w].reshape(h // block, block, w // block, block)
    small = np.median(small, axis=(1, 3))
    small = ndimage.median_filter(small, size, mode="nearest")
    full = ndimage.zoom(small, (lum.shape[0] / small.shape[0], lum.shape[1] / small.shape[1]), order=1)
    return full[:lum.shape[0], :lum.shape[1]].astype(np.float32)


def aperture(radius):
    """Offsets of the pixels in a round aperture."""
    r = int(math.ceil(radius))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    inside = xx ** 2 + yy ** 2 <= radius ** 2
    return yy[inside], xx[inside]


def photometry(flat, xy, radius):
    """Flux in a round aperture at each (x, y) of an image whose glow has
    been taken off. Stars too near the edge give NaN."""
    dy, dx = aperture(radius)
    x = np.rint(xy[:, 0]).astype(int)
    y = np.rint(xy[:, 1]).astype(int)
    r = int(math.ceil(radius))
    ok = (x >= r) & (y >= r) & (x < flat.shape[1] - r) & (y < flat.shape[0] - r)
    flux = np.full(len(xy), np.nan)
    flux[ok] = flat[y[ok, None] + dy, x[ok, None] + dx].sum(axis=1)
    return flux


def peaks(flat, xy):
    """The brightest pixel near each star."""
    x = np.clip(np.rint(xy[:, 0]).astype(int), 1, flat.shape[1] - 2)
    y = np.clip(np.rint(xy[:, 1]).astype(int), 1, flat.shape[0] - 2)
    return np.max([flat[y + j, x + i] for j in (-1, 0, 1) for i in (-1, 0, 1)], axis=0)


def calibrate(flat, stars, wcs, catalogue, radius):
    """Match the detected stars to Gaia and find the zero point. Returns a
    dict with the zero point, its uncertainty, the stars used, and the
    matched stars (for the star shape)."""
    if len(catalogue) == 0 or len(stars) == 0:
        return None
    px = np.column_stack(wcs.world_to_pixel_values(catalogue[:, 0], catalogue[:, 1]))
    inside = ((px[:, 0] > 0) & (px[:, 1] > 0) & (px[:, 0] < flat.shape[1])
              & (px[:, 1] < flat.shape[0]))
    px, g = px[inside], catalogue[inside, 2]
    if not len(px):
        return None
    tree = cKDTree(stars[:, :2])
    # A solve centred a pixel or two off still matches at a loose radius;
    # take the typical offset off before matching closely.
    d, i = tree.query(px, distance_upper_bound=8 * MATCH)
    near = np.isfinite(d)
    if near.sum() < 5:
        return None
    shift = np.median(stars[i[near], :2] - px[near], axis=0)
    d, i = tree.query(px + shift, distance_upper_bound=MATCH)
    matched = np.isfinite(d)
    # A Gaia star with another bright one close by is measured as a blend.
    gaia_tree = cKDTree(px)
    crowded = np.array([len(gaia_tree.query_ball_point(p, 3 * radius)) > 1 for p in px])
    use = matched & ~crowded & (g >= CALIBRATORS[0]) & (g <= CALIBRATORS[1])
    if use.sum() < 5:
        return None
    xy = stars[i[use], :2]
    flux = photometry(flat, xy, radius)
    # A saturated star is flat-topped: its brightest pixel is too faint for
    # its total. Leave those out.
    sharpness = peaks(flat, xy) / np.maximum(flux, 1e-6)
    good = np.isfinite(flux) & (flux > 0)
    typical = np.median(sharpness[good])
    good &= sharpness > 0.7 * typical
    zp = g[use][good] + 2.5 * np.log10(flux[good])
    keep = np.ones(len(zp), bool)
    for _ in range(5):
        middle = np.median(zp[keep])
        spread = 1.4826 * np.median(np.abs(zp[keep] - middle)) + 1e-3
        keep = np.abs(zp - middle) < 3 * spread
    if keep.sum() < 5:
        return None
    zps = zp[keep]
    spread = 1.4826 * float(np.median(np.abs(zps - np.median(zps))))
    return {"zeropoint": float(np.median(zps)),
            "zeropoint_error": spread / math.sqrt(len(zps)),
            "scatter": spread, "stars_used": int(len(zps)),
            "psf_stars": xy[good][keep], "shift_px": [float(shift[0]), float(shift[1])]}


def psf(flat, xy, radius, half=PSF_HALF, most=40):
    """The stars' own shape, from the matched stars: each one centred to a
    fraction of a pixel, scaled to one unit of aperture flux, and the median
    taken. Planted stars are copies of it, so they blur and trail exactly as
    the real ones do."""
    cuts = []
    for x, y in xy[:most]:
        ix, iy = int(round(x)), int(round(y))
        if not (half + 1 <= ix < flat.shape[1] - half - 1 and half + 1 <= iy < flat.shape[0] - half - 1):
            continue
        cut = flat[iy - half:iy + half + 1, ix - half:ix + half + 1].astype(np.float64)
        cut = ndimage.shift(cut, (iy - y, ix - x), order=3, mode="nearest")
        total = photometry(cut, np.array([[half, half]]), radius)[0]
        if total > 0:
            cuts.append(cut / total)
    if len(cuts) < 3:
        return None
    shape = np.median(cuts, axis=0)
    # Taper the edges to nothing: a neighbour caught in a corner must not
    # be planted along with the star.
    yy, xx = np.mgrid[-half:half + 1, -half:half + 1]
    shape *= np.clip((half - np.hypot(xx, yy)) / 4, 0, 1)
    return (shape / photometry(shape, np.array([[half, half]]), radius)[0]).astype(np.float32)


def stars_mask(lum, stars, grow=3.0):
    """Pixels on or close to a detected star."""
    mask = np.zeros(lum.shape, bool)
    for x, y, _, fwhm, _ in stars:
        r = int(grow * max(fwhm, 2))
        ix, iy = int(round(x)), int(round(y))
        mask[max(iy - r, 0):iy + r + 1, max(ix - r, 0):ix + r + 1] = True
    return mask


def regions(glow, sky, zp, pixel_arcsec):
    """Which kind of background each pixel is on (an index into REGIONS),
    from the brightness of the glow above the sky."""
    excess = np.maximum(glow - sky, 1e-9) / pixel_arcsec ** 2
    surface = zp - 2.5 * np.log10(excess)
    kind = np.zeros(glow.shape, np.int8)
    for n, (_, brighter_than) in enumerate(REGIONS):
        if brighter_than is not None:
            kind[surface < brighter_than] = n
    return kind


def empty_apertures(flat, mask, kinds, radius, count=4000, seed=1):
    """The spread of the flux in apertures dropped on empty patches: the
    noise a star has to stand out from, whatever the stacking did to it.
    Per kind of background; None where too few fell."""
    rng = np.random.default_rng(seed)
    r = int(math.ceil(radius)) + 1
    x = rng.uniform(r, flat.shape[1] - r, count)
    y = rng.uniform(r, flat.shape[0] - r, count)
    xy = np.column_stack([x, y])
    dy, dx = aperture(radius)
    ix, iy = np.rint(x).astype(int), np.rint(y).astype(int)
    clear = ~mask[iy[:, None] + dy, ix[:, None] + dx].any(axis=1)
    flux = photometry(flat, xy, radius)
    kind = kinds[iy, ix]
    spread = {}
    for n, (label, _) in enumerate(REGIONS):
        pick = clear & (kind == n) & np.isfinite(flux)
        if pick.sum() >= 30:
            values = flux[pick]
            spread[label] = 1.4826 * float(np.median(np.abs(values - np.median(values))))
    return spread


# --- planted stars -------------------------------------------------------------

def places(shape, count, rng, edge=PSF_HALF + 2, apart=SPACING):
    """Random places for planted stars, none closer than `apart` to another."""
    chosen = []
    tries = 0
    while len(chosen) < count and tries < count * 50:
        tries += 1
        p = rng.uniform((edge, edge), (shape[1] - edge, shape[0] - edge))
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= apart ** 2 for q in chosen):
            chosen.append(p)
    return np.array(chosen).reshape(-1, 2)


def plant(lum, shape, xy, flux):
    """A copy of the image with a star of the given shape added at each
    place, each with its own flux."""
    out = lum.astype(np.float32).copy()
    half = shape.shape[0] // 2
    for (x, y), f in zip(xy, flux):
        ix, iy = int(round(x)), int(round(y))
        star = ndimage.shift(shape, (y - iy, x - ix), order=3, mode="constant")
        out[iy - half:iy + half + 1, ix - half:ix + half + 1] += f * star
    return out


def found_again(before, after, xy, near=MATCH):
    """Which planted stars the star finder picked up: a new detection close
    to the place, and not one that was there before."""
    if len(after) == 0:
        return np.zeros(len(xy), bool)
    d, i = cKDTree(after[:, :2]).query(xy, distance_upper_bound=near)
    hit = np.isfinite(d)
    if len(before) and hit.any():
        old, _ = cKDTree(before[:, :2]).query(after[i[hit], :2], distance_upper_bound=near * 0.75)
        new = ~np.isfinite(old)
        hit[np.flatnonzero(hit)] = new
    return hit


def crossing(mags, share, level):
    """The faintest magnitude at which the share found is still `level`,
    by a straight line to the next planted magnitude. Read from the faint
    end, so a dip among the bright ones (a planted star that landed on a
    real one) does not end the curve early. None if no planted magnitude
    reaches the level; the faintest planted if all of them do."""
    pairs = [(m, s) for m, s in zip(mags, share) if s is not None]
    reached = [n for n, (_, s) in enumerate(pairs) if s >= level]
    if not reached:
        return None
    n = reached[-1]
    if n == len(pairs) - 1:
        return float(pairs[n][0])
    (m0, s0), (m1, s1) = pairs[n], pairs[n + 1]
    return round(m0 + (s0 - level) / (s0 - s1) * (m1 - m0), 2)


BRIGHT_END = 3      # planted magnitudes, from the brightest, that make the plateau


def plateau(share):
    """The share found among the brightest planted stars: they are all bright
    enough to see, so what is missing landed on a real star. That loss is
    crowding, and no amount of exposure wins it back."""
    top = [s for s in share[:BRIGHT_END] if s is not None]
    return float(np.mean(top)) if top else None


def completeness(lum, shape, zp, kinds, trials=6, per_trial=400, seed=7, finder=None):
    """Plant stars at each of MAGNITUDES, run the star finder, and count.
    Returns, for every kind of background and for the whole image, the share
    found at each magnitude and the magnitudes at which 90% and 50% are."""
    finder = finder or (lambda image: stacking.find_stars(image, limit=10 ** 6))
    rng = np.random.default_rng(seed)
    before = finder(lum)
    planted, recovered, kind_of = [], [], []
    for _ in range(trials):
        xy = places(lum.shape, per_trial, rng)
        mags = rng.choice(MAGNITUDES, len(xy))
        flux = 10 ** (-0.4 * (mags - zp))
        hit = found_again(before, finder(plant(lum, shape, xy, flux)), xy)
        planted.append(mags)
        recovered.append(hit)
        kind_of.append(kinds[np.rint(xy[:, 1]).astype(int), np.rint(xy[:, 0]).astype(int)])
    mags, hit, kind = np.concatenate(planted), np.concatenate(recovered), np.concatenate(kind_of)
    out = {}
    for label, pick in [("all", np.ones(len(mags), bool))] + [
            (name, kind == n) for n, (name, _) in enumerate(REGIONS)]:
        if pick.sum() < 20:
            continue
        rows, shares = [], []
        for m in MAGNITUDES:
            at = pick & (mags == m)
            share = float(hit[at].mean()) if at.sum() >= 5 else None
            shares.append(share)
            rows.append({"mag": float(m), "planted": int(at.sum()),
                         "found": int(hit[at].sum()), "share": None if share is None else round(share, 3)})
        # The 90% and 50% points are of the stars not lost to crowding: how
        # faint the stack sees, apart from how crowded the field is.
        top = plateau(shares)
        relative = [None if s is None or not top else s / top for s in shares]
        out[label] = {"curve": rows, "bright_end": None if top is None else round(top, 3),
                      "mag_90": crossing(MAGNITUDES, relative, 0.9),
                      "mag_50": crossing(MAGNITUDES, relative, 0.5), "planted": int(pick.sum())}
    return out


# --- putting it together -------------------------------------------------------

def measure(lum, wcs, catalogue, plant_stars=False, trials=6, seed=7, finder=None):
    """Everything this script knows about one stack."""
    finder = finder or (lambda image: stacking.find_stars(image, limit=10 ** 6))
    glow = background(lum)
    flat = lum - glow
    stars = finder(lum)
    if len(stars) < 5:
        raise interface.Refusal("NO_STARS", "Too few stars in the stack to measure it.")
    fwhm = float(np.median(stars[:200, 3]))
    radius = max(fwhm, 2.0)     # an aperture as wide as the star is about the best for faint ones
    cal = calibrate(flat, stars, wcs, catalogue, radius)
    if cal is None:
        raise interface.Refusal("PLATE_SOLVE_FAILED", "Too few of the stack's stars matched Gaia "
                                "to set its brightness scale.")
    zp = cal["zeropoint"]
    scale = float(np.sqrt(abs(np.linalg.det(wcs.wcs.cd))) * 3600)
    sky = float(np.percentile(glow, 5))
    kinds = regions(glow, sky, zp, scale)
    noise = empty_apertures(flat, stars_mask(lum, stars), kinds, radius)
    limits = {label: round(zp - 2.5 * math.log10(SIGMA * s), 2) for label, s in noise.items() if s > 0}
    record = {
        "zeropoint": round(zp, 3), "zeropoint_error": round(cal["zeropoint_error"], 3),
        "calibration_scatter": round(cal["scatter"], 3), "calibration_stars": cal["stars_used"],
        "fwhm_px": round(fwhm, 2), "fwhm_arcsec": round(fwhm * scale, 2),
        "scale_arcsec_per_px": round(scale, 3), "aperture_px": round(radius, 2),
        "sky_level": round(sky, 2),
        "sky_mag_per_arcsec2": round(zp - 2.5 * math.log10(max(sky, 1e-9) / scale ** 2), 2),
        "stars_detected": int(len(stars)),
        "limit_5sigma": limits,
        "share_of_image": {name: round(float((kinds == n).mean()), 3) for n, (name, _) in enumerate(REGIONS)},
        "band": "Gaia G (camera unfiltered)",
        "kinds": {"zeropoint": "measured", "limit_5sigma": "inferred",
                  "completeness": "simulated"},
    }
    if plant_stars:
        shape = psf(flat, cal["psf_stars"], radius)
        if shape is None:
            raise interface.Refusal("NO_STARS", "Too few clean stars to copy for planting.")
        record["completeness"] = completeness(lum, shape, zp, kinds, trials=trials, seed=seed,
                                              finder=finder)
        record["planted_per_trial"] = 400
        record["trials"] = trials
    return record


def frames_for_sweep(session):
    """The session's frames worth stacking, in the order they were taken."""
    import restack
    log = session / "restack.json"
    if log.exists():
        kept = json.loads(log.read_text(encoding="utf-8")).get("kept", [])
        names = sorted(Path(k).name for k in kept)
        return [session / n for n in names if (session / n).exists()]
    frames = stacking.read_log(session)
    return [Path(f["path"]) for f in restack.select(frames)] if frames else sorted(session.glob("light-*.fits"))


def sweep_stacks(paths, seconds_list, say=print):
    """Stacks of the first so many seconds of frames, one per entry in
    seconds_list, all lined up on the first frame so one plate solve serves
    them all. Nothing is trimmed: the first frame covers the whole picture,
    and trimming each stack differently would move its pixels from under
    the solve. Returns {seconds: (brightness image, seconds really used)}."""
    mosaic, header = stacking.load_light(paths[0])
    exposure, gain = float(header.get("EXPTIME", 0)), int(float(header.get("GAIN", 0)))
    if exposure <= 0:
        raise interface.Refusal("INVALID_REQUEST", f"{paths[0]} does not say its exposure.")
    calibration = stacking.Calibration(exposure, gain)
    rgb = stacking.prepare(mosaic, calibration)
    lum = rgb.sum(axis=2)
    reference = {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}
    wanted = sorted({min(len(paths), max(1, round(s / exposure))): s for s in seconds_list}.items())
    stack = stacking.Stack(rgb.shape)
    out, n = {}, 0
    for path in paths[:wanted[-1][0]]:
        if n:
            mosaic, _ = stacking.load_light(path)
            rgb = stacking.prepare(mosaic, calibration)
            rgb, _ = stacking.register(rgb, rgb.sum(axis=2), stacking.find_stars(rgb.sum(axis=2)),
                                       reference)
        stack.add(rgb)
        n += 1
        for count, seconds in wanted:
            if count == n:
                out[seconds] = (stack.result().sum(axis=2), n * exposure)
                say(f"  {seconds} s asked: {n} frames, {n * exposure:g} s")
    return out


def run(args, say=print):
    if config.DEMO:
        raise interface.Refusal("DEMO_UNSUPPORTED", "Measuring depth needs a real stack and Gaia.")
    stack = find_stack(args.target)
    name = args.near or object_name(stack)
    lum = brightness(fits.getdata(stack))
    header = fits.getheader(stack)
    say(f"{stack}: {lum.shape[1]} x {lum.shape[0]}, {header.get('EXPTIME', '?')} s "
        f"in {header.get('NFRAMES', '?')} frames")
    wcs = plate(lum, name)
    catalogue = gaia(*field(wcs, lum.shape))
    say(f"{len(catalogue)} Gaia stars in the field")
    record = measure(lum, wcs, catalogue, plant_stars=args.plant, trials=args.trials)
    record.update(stack=str(stack), object=name, exposure_s=header.get("EXPTIME"),
                  frames=header.get("NFRAMES"))
    report(record, say)
    if args.sweep:
        session = stack.parent
        paths = frames_for_sweep(session)
        if not paths:
            raise interface.Refusal("NO_SESSION", f"No raw frames in {session} for a sweep.")
        say(f"sweep over {len(paths)} frames:")
        stacks = sweep_stacks(paths, SWEEP, say)
        first = max(stacks)
        big, _ = stacks[first]
        sweep_wcs = plate(big, name)
        rows = []
        for seconds in sorted(stacks):
            image, used = stacks[seconds]
            one = measure(image, sweep_wcs, catalogue, plant_stars=True, trials=max(2, args.trials // 2))
            rows.append({"asked_s": seconds, "exposure_s": used, "zeropoint": one["zeropoint"],
                         "limit_5sigma": one["limit_5sigma"],
                         "mag_90": {k: v["mag_90"] for k, v in one["completeness"].items()},
                         "mag_50": {k: v["mag_50"] for k, v in one["completeness"].items()}})
            say(f"  {used:5.0f} s: 5-sigma {one['limit_5sigma'].get('sky')}, "
                f"50% found at {one['completeness'].get('all', {}).get('mag_50')}")
        record["sweep"] = rows
    (stack.parent / "depth.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    say(f"kept as {stack.parent / 'depth.json'}")
    return record


def report(r, say=print):
    say(f"zero point {r['zeropoint']:.2f} ± {r['zeropoint_error']:.2f} (G) from "
        f"{r['calibration_stars']} Gaia stars, scatter {r['calibration_scatter']:.2f}")
    say(f"stars {r['fwhm_arcsec']:.1f}\" across ({r['fwhm_px']:.1f} px); "
        f"sky {r['sky_mag_per_arcsec2']:.1f} mag per square arcsecond")
    for label, limit in r["limit_5sigma"].items():
        say(f"5-sigma limit on {label}: {limit:.2f} (a formula's figure)")
    for label, c in r.get("completeness", {}).items():
        lost = "" if c["bright_end"] is None else f"; {100 * (1 - c['bright_end']):.0f}% lost on real stars"
        say(f"planted stars on {label}: 90% found to {c['mag_90']}, 50% to {c['mag_50']} "
            f"({c['planted']} planted{lost})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="an object (its newest session), a session folder, or a FITS stack")
    ap.add_argument("--plant", action="store_true", help="plant fake stars and count how many are found")
    ap.add_argument("--trials", type=int, default=6, help="rounds of 400 planted stars (default 6)")
    ap.add_argument("--sweep", action="store_true",
                    help="also measure stacks of 60, 120, 180, 300 and 600 s of the session's frames")
    ap.add_argument("--near", help="the object to plate-solve near, if the folder does not say")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("depth", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
