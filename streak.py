#!/usr/bin/env python3
"""Which satellite made the streak across a frame.

    ./streak.py                          the newest frame with a streak in it
    ./streak.py frames/M31-P6/20261018-224628/light-0004.fits
    ./streak.py FRAME --offline          only the orbits already kept
    ./streak.py FRAME --json

It finds the straight line in the frame, plate-solves the frame to put the
line's ends on the sky, and places every active satellite as seen from the
site through the exposure (SGP4, from CelesTrak's orbits). A satellite fits
when its path lies along the streak, in the same direction, while the
shutter was open; one that fits alone is named. Two that fit are both said
and neither is named. A streak no satellite accounts for is said to be just
that: a meteor, an aircraft or a satellite missing from the list, and this
does not guess which. docs/satellites.md has the worked example it was
built from.

The orbits are CelesTrak's "active" list (no key), kept in
cache/satellites/ by the time they were fetched, and a copy up to a day
from the frame is used. A frame from an earlier night needs that night's
orbits: it says how far apart they are when that is too far to trust.
Nothing here moves the mount or uses the camera.
"""
import argparse
import csv
import io
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from scipy import ndimage

import config
import interface

ORBITS_URL = "https://celestrak.org/NORAD/elements/gp.php"
ORBITS = config.DATA / "cache" / "satellites"
FRESH = timedelta(days=1)       # orbits this close to the frame are used as they are
TOO_OLD = timedelta(days=3)     # further than this, a match is doubtful and is said to be

BIN = 4                 # pixels of the brightness image averaged together to find a streak
DETECT = 3.0            # sigma above the sky, after a 3x3 smoothing
MIN_LENGTH = 0.05       # degrees: no star trail from poor tracking is this long
MIN_ASPECT = 8.0        # a streak is at least this many times longer than it is wide
EDGE = 3                # binned pixels: an end this near the border may go on beyond it

STEP = 0.5              # seconds between the places worked out for each satellite
SLACK = 3.0             # seconds either way: orbits a day old are a second or so out along the track
NEAR = 20.0             # degrees: satellites further than this from the streak are not looked at
WITHIN = 0.2            # degrees: a path fits when it passes this close to both ends
ALONG = 5.0             # degrees: and runs along the streak this closely
EARTH_KM = 6378.137


# --- The streak ---------------------------------------------------------------

def binned(image, block=BIN):
    image = np.asarray(image, dtype=float)
    h, w = (image.shape[0] // block) * block, (image.shape[1] // block) * block
    return image[:h, :w].reshape(h // block, block, w // block, block).mean((1, 3))


def sky_removed(small, block=32):
    """The binned image less its sky, which in a galaxy's field is anything
    but flat: the median of each block, spread smoothly back over it."""
    h, w = small.shape
    rows, cols = max(1, h // block), max(1, w // block)
    grid = np.array([[np.median(small[r * h // rows:(r + 1) * h // rows, c * w // cols:(c + 1) * w // cols])
                      for c in range(cols)] for r in range(rows)])
    sky = ndimage.zoom(grid, (h / rows, w / cols), order=1, mode="nearest")
    return small - sky[:h, :w]


def find_streaks(image):
    """Every straight line in a brightness image much longer than a star or
    a star's trail, longest first: each with its two ends in the image's
    pixels and whether each end is at the border (where the streak may go on
    beyond the frame). The image is binned and smoothed so that a faint
    streak is found whole; a star is round however bright it is."""
    small = ndimage.uniform_filter(sky_removed(binned(image)), 3)
    noise = 1.4826 * np.median(np.abs(small - np.median(small)))
    labels, count = ndimage.label(small > DETECT * noise, structure=np.ones((3, 3)))
    if not count:
        return []
    h, w = small.shape
    # Degrees a pixel before a solve gives the real figure: from the rig's field of view.
    scale = config.field_height() / image.shape[0]
    found = []
    for index, where in enumerate(ndimage.find_objects(labels), 1):
        ys, xs = np.nonzero(labels[where] == index)
        if len(ys) < 10:
            continue
        ys, xs = ys + where[0].start, xs + where[1].start
        mean = np.array([xs.mean(), ys.mean()])
        values, vectors = np.linalg.eigh(np.cov(np.vstack([xs, ys])))
        axis = vectors[:, 1]
        # A line of length L has a spread of L²/12 along itself.
        length, width = math.sqrt(12 * max(values[1], 0)), math.sqrt(12 * max(values[0], 0)) or 1.0
        if length * BIN * scale < MIN_LENGTH or length / width < MIN_ASPECT:
            continue
        along = (xs - mean[0]) * axis[0] + (ys - mean[1]) * axis[1]
        ends = [mean + along.min() * axis, mean + along.max() * axis]
        at_edge = [bool(e[0] < EDGE or e[1] < EDGE or e[0] > w - 1 - EDGE or e[1] > h - 1 - EDGE)
                   for e in ends]
        # Back to the image's own pixels: the middle of each block.
        ends = [[float(e[0] * BIN + (BIN - 1) / 2), float(e[1] * BIN + (BIN - 1) / 2)] for e in ends]
        # Its brightness in eighths along it: a satellite's is even, a meteor's
        # flares and fades, an aircraft's blinks.
        order = np.argsort(along)
        pieces = [float(np.median(small[ys[i], xs[i]])) for i in np.array_split(order, 8)]
        found.append({"ends": ends, "at_edge": at_edge, "pixels": float(length * BIN),
                      "brightness": float(small[ys, xs].mean() / noise),
                      "profile": [round(v / np.mean(pieces), 2) for v in pieces]})
    return sorted(found, key=lambda s: -s["pixels"])


# --- When and where -------------------------------------------------------------

def exposure(path, header):
    """(start as a UTC datetime, seconds, how it is known). The frame's own
    DATE-OBS is the start; a frame without one is placed from when the run
    kept it, less the exposure, which is said to be an inference."""
    seconds = float(header.get("EXPTIME", 0)) or None
    if header.get("DATE-OBS"):
        start = datetime.fromisoformat(header["DATE-OBS"]).replace(tzinfo=timezone.utc)
        return start, seconds, "the frame's own start time"
    log = Path(path).parent / "frames.jsonl"
    index = int("".join(ch for ch in Path(path).stem if ch.isdigit()) or 0)
    if seconds and log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("index") == index and row.get("taken"):
                landed = datetime.fromtimestamp(row["taken"], timezone.utc)
                return landed - timedelta(seconds=seconds), seconds, "when the frame arrived, less its exposure"
    raise interface.Refusal("INVALID_REQUEST", f"{path} says neither when it was taken nor for how long.")


def solved(path, image):
    """The frame's plate solution as a WCS on the brightness image, and its
    scale. The session's name is the hint (a mosaic panel's too)."""
    import depth
    import solve
    hint = (None, None)
    try:
        import mount
        name = json.loads((Path(path).parent / "session.json").read_text(encoding="utf-8"))["name"]
        target = mount.find_target(name)
        hint = (target["ra"], target["dec"])
    except (OSError, KeyError, ValueError, SystemExit):
        pass
    found = solve.solve(image, *hint, radius=5) if hint[0] is not None else None
    found = found or solve.solve(image)
    if not found or "cd" not in found:
        raise interface.Refusal("PLATE_SOLVE_FAILED", f"{path} would not plate-solve, so the streak "
                                                      "cannot be put on the sky.")
    return depth.wcs_from(found, image.shape), found["scale"]


# --- Orbits ----------------------------------------------------------------------

def kept_orbits():
    """{fetched (UTC datetime): path} of every copy of the orbits kept."""
    kept = {}
    for path in ORBITS.glob("active-*.csv"):
        try:
            kept[datetime.strptime(path.stem, "active-%Y%m%d-%H%M").replace(tzinfo=timezone.utc)] = path
        except ValueError:
            pass
    return kept


def fetch_orbits(now=None):
    """Today's orbits from CelesTrak, kept under the time they came."""
    now = now or datetime.now(timezone.utc)
    r = requests.get(ORBITS_URL, params={"GROUP": "active", "FORMAT": "csv"}, timeout=60,
                     headers={"User-Agent": "telescopeyoke/0.1 (personal observing)"})
    r.raise_for_status()
    if not r.text.startswith("OBJECT_NAME"):
        raise ValueError(f"CelesTrak answered: {r.text[:200]}")
    ORBITS.mkdir(parents=True, exist_ok=True)
    path = ORBITS / f"active-{now:%Y%m%d-%H%M}.csv"
    part = path.with_suffix(".part")
    part.write_text(r.text, encoding="utf-8")
    os.replace(part, path)
    return path


def orbits_for(when, offline=False, now=None):
    """(path, fetched) of the orbits nearest the frame's time, fetching
    today's when the frame is recent and no kept copy is within a day of it.
    (None, None) when there are none."""
    now = now or datetime.now(timezone.utc)
    kept = kept_orbits()
    nearest = min(kept, key=lambda t: abs(t - when), default=None)
    if not offline and abs(now - when) < FRESH and (nearest is None or abs(nearest - when) > FRESH):
        try:
            path = fetch_orbits(now)
            return path, now.replace(second=0, microsecond=0)
        except (requests.RequestException, ValueError, OSError) as problem:
            print(f"CelesTrak could not be reached ({problem}); using the orbits kept.")
    return (kept[nearest], nearest) if nearest else (None, None)


def read_orbits(path):
    """[(name, catalogue number, Satrec)] from a kept CSV of orbits."""
    from sgp4 import omm
    from sgp4.api import Satrec
    found = []
    for row in csv.DictReader(io.StringIO(Path(path).read_text(encoding="utf-8"))):
        sat = Satrec()
        try:
            omm.initialize(sat, row)
        except (KeyError, ValueError):
            continue
        found.append((row["OBJECT_NAME"].strip(), int(row["NORAD_CAT_ID"]), sat))
    return found


def sgp4_or_refuse():
    try:
        import sgp4  # noqa: F401
    except ImportError:
        raise interface.Refusal("INVALID_REQUEST", "Naming satellites needs the sgp4 library: "
                                                   "sudo apt install python3-sgp4, or pip install sgp4.")


def places(satellites, times, site):
    """Where each satellite was as seen from the site at each time:
    (ra, dec) in degrees, each of shape (satellites, times), the distance
    in km, and whether it was in sunlight. NaN where an orbit fails."""
    from astropy import units as u
    from astropy.coordinates import GCRS, TEME, CartesianRepresentation, EarthLocation, get_sun
    from astropy.time import Time
    from sgp4.api import SatrecArray

    t = Time(times)
    error, teme, _ = SatrecArray([s for _, _, s in satellites]).sgp4(t.utc.jd1, t.utc.jd2)
    # From the true equator of date to the axes of the catalogues: a turn of
    # the whole sky, the same for every satellite over a few seconds.
    middle = t[len(t) // 2]
    axes = TEME(CartesianRepresentation(np.eye(3) * 1e4 * u.km), obstime=middle).transform_to(GCRS(obstime=middle))
    turn = (axes.cartesian.xyz.to_value(u.km) / 1e4)   # columns: where TEME's x, y and z go
    gcrs = teme @ turn.T
    place = EarthLocation(lon=site["longitude"] * u.deg, lat=site["latitude"] * u.deg, height=site.get("elevation_m", 0) * u.m)
    here = place.get_gcrs(t).cartesian.xyz.to_value(u.km).T          # (times, 3)
    seen = gcrs - here[None]
    distance = np.linalg.norm(seen, axis=2)
    ra = np.degrees(np.arctan2(seen[..., 1], seen[..., 0])) % 360
    dec = np.degrees(np.arcsin(seen[..., 2] / distance))
    sun = get_sun(middle).cartesian.xyz.to_value(u.km)
    sun = sun / np.linalg.norm(sun)
    # In the Earth's shadow, taken as a cylinder: behind the Earth and within its radius of the axis.
    towards = gcrs @ sun
    sunlit = (towards > 0) | (np.linalg.norm(gcrs - towards[..., None] * sun, axis=2) > EARTH_KM)
    bad = error != 0
    for a in (ra, dec, distance):
        a[bad] = np.nan
    return ra, dec, distance, sunlit & ~bad


# --- Matching ------------------------------------------------------------------

def separation(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(np.radians, (ra1, dec1, ra2, dec2))
    c = np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(r1 - r2)
    return np.degrees(np.arccos(np.clip(c, -1, 1)))


def match(streak, wcs, scale, satellites, times, start, seconds, site):
    """Each satellite that passed near the streak, best first, with how well
    it fits. Worked in the frame's own pixels, where a short stretch of a
    satellite's path is a straight line."""
    (x1, y1), (x2, y2) = streak["ends"]
    mid_ra, mid_dec = wcs.pixel_to_world_values((x1 + x2) / 2, (y1 + y2) / 2)
    ra, dec, distance, sunlit = places(satellites, times, site)
    apart = separation(ra, dec, float(mid_ra), float(mid_dec))
    near = np.where(np.isnan(apart), 180, apart).min(axis=1) < NEAR
    degree = scale / 3600     # degrees per pixel
    ends = np.array(streak["ends"])
    middle = ends.mean(0)
    direction = (ends[1] - ends[0]) / np.linalg.norm(ends[1] - ends[0])
    offsets = np.array([(t - start).total_seconds() for t in times])
    found = []
    for k in np.flatnonzero(near):
        if np.isnan(ra[k]).any():
            continue
        px, py = wcs.world_to_pixel_values(ra[k], dec[k])
        path = np.column_stack([px, py])
        # The stretch of path whose nearest point to the streak's middle is nearest.
        best = None
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            step = b - a
            run = float(np.hypot(*step))
            if run == 0:
                continue
            f = float(np.clip((middle - a) @ step / run ** 2, 0, 1))
            gap = float(np.hypot(*(a + f * step - middle)))
            if best is None or gap < best[0]:
                best = (gap, i, f, step / run, run / STEP)
        if best is None:
            continue
        gap, i, f, heading, speed = best
        when = offsets[i] + f * STEP          # seconds after the shutter opened
        # Where along the path the streak's two ends are, as times.
        at = [when + float((e - middle) @ heading) / speed for e in ends]
        nearest = path[i] + f * (path[i + 1] - path[i])
        crossing = [float(abs((e - nearest) @ np.array([-heading[1], heading[0]]))) for e in ends]
        angle = math.degrees(math.acos(min(1.0, abs(float(direction @ heading)))))
        lit = bool(sunlit[k, i])
        # The part of the path the shutter saw, in sunlight: what the streak could be at most.
        shown = speed * float(np.sum(sunlit[k, :-1] & (offsets[:-1] >= 0) & (offsets[:-1] < seconds))) * STEP
        found.append({
            "name": satellites[k][0], "number": satellites[k][1],
            "offset_deg": round(max(crossing) * degree, 3), "angle_deg": round(angle, 1),
            "at": (start + timedelta(seconds=when)).isoformat(timespec="milliseconds"),
            "ends_at_s": [round(min(at), 1), round(max(at), 1)],
            "distance_km": round(float(np.interp(when, offsets, distance[k]))),
            "speed_deg_s": round(speed * degree, 3), "sunlit": lit,
            "sunlit_length_deg": round(shown * degree, 3),
        })
    for row in found:
        row["fits"] = fits_streak(row, streak, seconds)
    return sorted(found, key=lambda r: (not r["fits"], r["offset_deg"] + r["angle_deg"] / 25))[:5]


def fits_streak(row, streak, seconds):
    """Whether a satellite's pass accounts for the streak: along it, in the
    same direction, in sunlight, and at the streak while the shutter was open
    (a few seconds either way). An end at the frame's border may go on
    beyond it, so only an end inside the frame has to be reached in time."""
    if row["offset_deg"] > WITHIN or row["angle_deg"] > ALONG or not row["sunlit"]:
        return False
    first, last = row["ends_at_s"]
    inside = [not e for e in streak["at_edge"]]
    if not all(inside):
        # Only the overlap matters: some of the streak was crossed while the shutter was open.
        return last > -SLACK and first < seconds + SLACK
    return first > -SLACK and last < seconds + SLACK


def verdict(streak, matches, scale):
    length = streak["pixels"] * scale / 3600
    fit = [m for m in matches if m["fits"]]
    if not fit:
        return (f"A streak {length:.2f}° long. No satellite in the list accounts for it: a meteor, "
                "an aircraft, or a satellite the list does not have.")
    if len(fit) > 1:
        return (f"A streak {length:.2f}° long. {len(fit)} satellites fit it: "
                f"{', '.join(m['name'] for m in fit)}; neither can be named.")
    m = fit[0]
    when = datetime.fromisoformat(m["at"])
    said = (f"A streak {length:.2f}° long. {m['name']} (catalogue {m['number']}) passed "
            f"{m['offset_deg']:.2f}° from it at {when:%H:%M:%S} UTC, {m['distance_km']:,} km away, "
            f"moving {m['speed_deg_s']:.2f}° a second, along it to {m['angle_deg']:.0f}°")
    if all(not e for e in streak["at_edge"]) and m["sunlit_length_deg"] < 1.3 * length:
        said += "; its length fits."
    elif any(streak["at_edge"]):
        said += "; the streak runs off the frame, so its length cannot be checked."
    else:
        said += (f"; in sunlight it would have crossed {m['sunlit_length_deg']:.2f}° while the shutter "
                 "was open, so the streak's ends are not where it entered or left the frame.")
    return said


# --- The command ---------------------------------------------------------------

def newest_with_streak(limit=40):
    """The newest frame of the newest run that has a streak in it, looking
    back at most `limit` frames."""
    from camera import luminance
    sessions = sorted((config.DATA / "frames").glob("*/*/session.json"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        raise interface.Refusal("NO_SESSION", "No imaging run has been recorded yet.")
    frames = sorted(sessions[-1].parent.glob("light-*.fits"), reverse=True)[:limit]
    for path in frames:
        if find_streaks(luminance(fits.getdata(path))):
            return path
    raise interface.Refusal("INVALID_REQUEST", f"None of the newest {len(frames)} frames in "
                                               f"{sessions[-1].parent} has a streak; name the frame.")


def check(path, offline=False, say=print):
    """The streaks in one frame and the satellite each was, if any."""
    from camera import luminance
    sgp4_or_refuse()
    path = Path(path)
    with fits.open(path) as hdul:
        hdu = next(h for h in hdul if h.data is not None)
        header, data = hdu.header, hdu.data
        image = luminance(data) if data.shape[0] > 3000 else np.asarray(data, dtype=float)
    streaks = find_streaks(image)
    start, seconds, timed = exposure(path, header)
    answer = {"frame": str(path), "start": start.isoformat(timespec="milliseconds"), "exposure_s": seconds,
              "timed_by": timed, "orbits": None, "streaks": []}
    if not streaks:
        say(f"No streak in {path.name}.")
        return answer, []
    warnings = []
    orbit_file, fetched = orbits_for(start, offline)
    if orbit_file is None:
        raise interface.Refusal("INVALID_REQUEST", "No orbits are kept and CelesTrak was not asked "
                                                   "(--offline, or the frame is older than a day).")
    apart = abs(fetched - start)
    if apart > TOO_OLD:
        warnings.append(f"The orbits are from {fetched:%d %B}, {apart.days} days from the frame: "
                        "a satellite may be several seconds out along its path, or missing.")
    satellites = read_orbits(orbit_file)
    answer["orbits"] = {"file": orbit_file.name, "fetched": fetched.isoformat(), "satellites": len(satellites),
                        "days_from_frame": round(apart.total_seconds() / 86400, 2)}
    say(f"{len(streaks)} streak{'s' * (len(streaks) > 1)} in {path.name}; solving the frame...")
    wcs, scale = solved(path, image)
    times = [start + timedelta(seconds=s) for s in np.arange(-SLACK - STEP, seconds + SLACK + STEP, STEP)]
    for streak in streaks:
        sky = [list(map(float, wcs.pixel_to_world_values(*e))) for e in streak["ends"]]
        matches = match(streak, wcs, scale, satellites, times, start, seconds, config.load()["site"])
        named = [m for m in matches if m["fits"]]
        row = {"ends": streak["ends"], "at_edge": streak["at_edge"], "ends_sky": sky, "profile": streak["profile"],
               "length_deg": round(streak["pixels"] * scale / 3600, 3), "satellites": matches,
               "named": named[0]["name"] if len(named) == 1 else None,
               "said": verdict(streak, matches, scale)}
        answer["streaks"].append(row)
    taken = f"{start:%H:%M:%S} UTC, {seconds:g} s ({timed})"
    say(f"{path.name}, taken {taken}.")
    for row in answer["streaks"]:
        say(row["said"])
    for w in warnings:
        say(w)
    return answer, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("frame", nargs="?", help="a FITS frame (default: the newest with a streak)")
    ap.add_argument("--offline", action="store_true", help="use only the orbits already kept")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()

    def work():
        return check(args.frame or newest_with_streak(), args.offline)
    interface.main("streak", work, args.json)


if __name__ == "__main__":
    main()
