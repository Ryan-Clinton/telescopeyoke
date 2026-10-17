#!/usr/bin/env python3
"""Which of difference.py's candidates could be something new: each one
checked, and the evidence kept.

    ./vet.py frames/M31/20261014-021118          the candidates difference.py left there
    ./vet.py frames/M31/20261014-021118 --offline   only the checks that need no internet
    ./vet.py frames/M31/20261014-021118 --json

For each candidate it records:

- in both halves of the night: the session's frames are split in two, each
  half stacked and subtracted from the reference on its own. A new star is
  in both; a satellite, an aeroplane, a cosmic ray or one bad frame is in
  one at most.
- a known asteroid there at the time (IMCCE SkyBoT, for the middle of the
  session, with each one's motion);
- a known variable star (the AAVSO's VSX);
- already reported: the novae and supernovae listed by the Rochester pages
  for this year and last, whose designations give their positions;
- a Gaia star at the place, which makes it a known star brightening, not a
  new one;
- the light already in the reference there.

Each figure says whether it was measured here or reported by someone else,
and each candidate gets a verdict. Only those left "unexplained" are worth a
person's eyes. Kept as vetted.json beside the candidates. The Transient
Name Server is not asked: its search needs an account (a TNS bot key).
Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

import config
import depth
import difference
import interface
import records
import stacking

SKYBOT_URL = "https://ssp.imcce.fr/webservices/skybot/api/conesearch.php"
VIZIER_URL = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
HALVES_FROM = 8     # frames needed to stack and check each half of the night
ROCHESTER = ("https://www.rochesterastronomy.org/sn{year}/novae.html",
             "https://www.rochesterastronomy.org/sn{year}/index.html")
ASTEROID_WITHIN = 30.0    # arcsec: a known asteroid this close at mid-session is the candidate
VARIABLE_WITHIN = 5.0     # arcsec, for VSX
REPORTED_WITHIN = 5.0     # arcsec, for a listed nova or supernova
GAIA_WITHIN = 2.0         # arcsec: a Gaia star this close is the candidate's own star
HALF_SCORE = 3.0          # each half must show it at least this strongly
DESIGNATION = re.compile(r"J(\d{2})(\d{2})(\d{2})(\d{2})([+-])(\d{2})(\d{2})(\d{2})(\d)")


# --- what others know ------------------------------------------------------------

def separation(ra1, dec1, ra2, dec2):
    """Arcseconds between points on the sky (degrees)."""
    # The haversine form: the cosine form loses its precision at the
    # arcseconds that matter here.
    ra1, dec1, ra2, dec2 = map(np.radians, (ra1, dec1, ra2, dec2))
    h = np.sin((dec2 - dec1) / 2) ** 2 + np.cos(dec1) * np.cos(dec2) * np.sin((ra2 - ra1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))) * 3600


def asteroids(ra, dec, radius_deg, jd):
    """Known asteroids and comets in a circle at a moment, from SkyBoT: rows
    of (name, ra, dec, V, motion in arcsec an hour)."""
    reply = requests.get(SKYBOT_URL, timeout=120, params={
        "-ep": f"{jd:.5f}", "-ra": f"{ra:.5f}", "-dec": f"{dec:.5f}", "-rd": f"{radius_deg:.3f}",
        "-mime": "text", "-output": "basic", "-loc": "500", "-filter": "120", "-objFilter": "111"})
    reply.raise_for_status()
    return read_skybot(reply.text)


def read_skybot(text):
    out = []
    for line in text.splitlines():
        if line.startswith("#") or "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        try:
            h, m, s = (float(v) for v in cells[2].split())
            sign = -1 if cells[3].startswith("-") else 1
            d, dm, ds = (abs(float(v)) for v in cells[3].split())
            out.append({"name": cells[1], "ra": 15 * (h + m / 60 + s / 3600),
                        "dec": sign * (d + dm / 60 + ds / 3600),
                        "v": float(cells[5]) if cells[5] not in ("", "-") else None,
                        "motion": round(math.hypot(float(cells[8]), float(cells[9])), 1)})
        except (ValueError, IndexError):
            continue
    return out


def variables(ra, dec, radius_deg):
    """Known variable stars in a circle, from VSX: (name, ra, dec, type)."""
    reply = requests.get(VIZIER_URL, timeout=120, params={
        "-source": "B/vsx/vsx", "-c": f"{ra:.5f} {dec:+.5f}", "-c.rd": f"{radius_deg:.3f}",
        "-out": "Name,RAJ2000,DEJ2000,Type", "-out.max": "50000"})
    reply.raise_for_status()
    out = []
    lines = [l for l in reply.text.splitlines() if l.strip() and not l.startswith("#")]
    for line in lines[3:]:
        cells = line.split("\t")
        try:
            out.append({"name": cells[0].strip(), "ra": float(cells[1]), "dec": float(cells[2]),
                        "type": cells[3].strip()})
        except (ValueError, IndexError):
            continue
    return out


def reported(years):
    """Novae and supernovae listed by the Rochester pages, from the positions
    built into their designations (PNV J00425223+4101447 and the like)."""
    out = {}
    for year in years:
        for url in ROCHESTER:
            try:
                reply = requests.get(url.format(year=year), timeout=60)
            except requests.RequestException:
                continue
            if reply.ok:
                for name, ra, dec in read_designations(reply.text):
                    out[name] = (ra, dec)
    return [{"name": n, "ra": ra, "dec": dec} for n, (ra, dec) in out.items()]


def read_designations(text):
    found = []
    for m in DESIGNATION.finditer(text):
        h, mi, s, cs, sign, d, dm, ds, dds = m.groups()
        ra = 15 * (int(h) + int(mi) / 60 + (int(s) + int(cs) / 100) / 3600)
        dec = (1 if sign == "+" else -1) * (int(d) + int(dm) / 60 + (int(ds) + int(dds) / 10) / 3600)
        found.append((m.group(0), ra, dec))
    return found


def nearest(c, rows, within):
    """The closest row to a candidate within `within` arcsec, with its distance."""
    if not rows:
        return None
    d = separation(c["ra"], c["dec"], np.array([r["ra"] for r in rows]), np.array([r["dec"] for r in rows]))
    i = int(np.argmin(d))
    return dict(rows[i], arcsec=round(float(d[i]), 1)) if d[i] <= within else None


# --- what the frames show -----------------------------------------------------------

def halves(paths, say=print):
    """Two stacks, of the first and second half of the frames, lined up on
    the first frame so they share pixels."""
    middle = len(paths) // 2
    return stacked([paths[:middle], paths[middle:]], lambda part: say(f"  a half of {len(part)} frames stacked"))


def stacked(groups, done=lambda part: None):
    """A brightness stack of each group of frames, all lined up on the first
    frame of the first group so they share pixels."""
    mosaic, header = stacking.load_light(groups[0][0])
    calibration = stacking.Calibration(float(header.get("EXPTIME", 0)), int(float(header.get("GAIN", 0))))
    rgb = stacking.prepare(mosaic, calibration)
    lum = rgb.sum(axis=2)
    reference = {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}
    out = []
    for part in groups:
        stack = stacking.Stack(rgb.shape)
        for path in part:
            frame = stacking.prepare(stacking.load_light(path)[0], calibration)
            frame, _ = stacking.register(frame, frame.sum(axis=2), stacking.find_stars(frame.sum(axis=2)),
                                         reference)
            stack.add(frame)
        out.append(stack.result().sum(axis=2))
        done(part)
    return out


def each_half(record, ref, ref_wcs, paths, name, say=print):
    """The score at each candidate in each half of the night, subtracted on
    its own."""
    stacks = halves(paths, say)
    scores = []
    for image in stacks:
        image = np.where(image == 0, np.nan, image)
        wcs = depth.plate(np.nan_to_num(image), name)
        _, significance = difference.subtract(image, ref, wcs, ref_wcs)
        scores.append(significance)
    out = []
    for c in record["candidates"]:
        x, y = c["x"], c["y"]
        out.append([round(float(np.nanmax(s[max(y - 2, 0):y + 3, max(x - 2, 0):x + 3])), 1) for s in scores])
    return out


def in_reference(ref, c, radius, zeropoint):
    """The light already at the place in the reference, as a magnitude, or
    None if there is none to speak of."""
    flat = ref - difference.glow(ref)
    flux = depth.photometry(flat, np.array([[c["x"], c["y"]]], float), radius)[0]
    noise = difference.sky_noise(flat) * math.sqrt(math.pi) * radius
    return round(zeropoint - 2.5 * math.log10(flux), 2) if zeropoint and flux > 3 * noise else None


# --- the verdict ----------------------------------------------------------------------

ONE_HALF = "in one half of the night only"
UNEXPLAINED = "unexplained: worth a person's eyes"


def verdict(e):
    """One line on what a candidate most likely is, from its evidence. Only a
    match to something catalogued as moving, varying or already reported
    explains it. A Gaia star close by or light already in the reference are
    clues, listed with it, not explanations: a transient can sit beside a
    catalogued star, and in a crowded field 2 arcseconds is not nothing.
    Being in one half of the night only is said as it is; whether that rules
    it out is the programme's choice (patrol.py: both_halves)."""
    if e.get("asteroid"):
        return f"known asteroid {e['asteroid']['name']}"
    if e.get("reported"):
        return f"already reported: {e['reported']['name']}"
    if e.get("variable"):
        return f"known variable {e['variable']['name']} ({e['variable']['type']})"
    halves_seen = e.get("halves")
    if halves_seen is not None and min(halves_seen) < HALF_SCORE:
        return ONE_HALF
    return UNEXPLAINED


def clues(e):
    """What does not explain a candidate but bears on it."""
    out = []
    if e.get("gaia"):
        out.append(f"Gaia star G {e['gaia']['g']:.1f} {e['gaia']['arcsec']}\" away: a star brightening, "
                   "or a transient beside it")
    if e.get("in_reference") is not None:
        out.append(f"light already there in the reference (G {e['in_reference']}): a brightening?")
    if e.get("halves") is None:
        out.append("the halves of the night were not checked")
    return out


def vet(record, checks, half_scores=None, ref=None, zeropoint=None, radius=4.0):
    """The evidence and verdict for every candidate. `checks` holds what was
    fetched: asteroids, variables, reported, gaia (lists of rows)."""
    out = []
    for n, c in enumerate(record["candidates"]):
        e = {"x": c["x"], "y": c["y"], "ra": c.get("ra"), "dec": c.get("dec"), "score": c["score"],
             "as_strong_fading": c.get("as_strong_fading"), "mag": c.get("mag")}
        kinds = {"score": "measured", "mag": "measured"}
        if c.get("ra") is not None:
            for key, rows, within in (("asteroid", checks.get("asteroids"), ASTEROID_WITHIN),
                                      ("variable", checks.get("variables"), VARIABLE_WITHIN),
                                      ("reported", checks.get("reported"), REPORTED_WITHIN),
                                      ("gaia", checks.get("gaia"), GAIA_WITHIN)):
                if rows is None:
                    kinds[key] = "not known"
                    continue
                e[key] = nearest(c, rows, within)
                kinds[key] = "reported"
        if half_scores is not None:
            e["halves"] = half_scores[n]
            kinds["halves"] = "measured"
        if ref is not None:
            e["in_reference"] = in_reference(ref, c, radius, zeropoint)
            kinds["in_reference"] = "measured"
        e["kinds"] = kinds
        e["verdict"] = verdict(e)
        e["clues"] = clues(e)
        out.append(e)
    return out


def run(args, say=print):
    if config.DEMO:
        raise interface.Refusal("DEMO_UNSUPPORTED", "Vetting needs real candidates.")
    import restack
    session = restack.find_session(args.session)
    found = session / "candidates.json"
    if not found.exists():
        raise interface.Refusal("NO_SESSION", f"No candidates in {session}: run difference.py on it first.")
    record = json.loads(found.read_text(encoding="utf-8"))
    name = record.get("object") or session.parent.name
    ref_path = Path(record["reference"])
    ref = depth.brightness(fits.getdata(ref_path))
    ref = np.where(ref == 0, np.median(ref[ref != 0]), ref).astype(np.float32)
    ref_wcs = WCS(fits.getheader(session / "difference.fits"))
    kept_ref = depth.record_path(ref_path)
    zeropoint = json.loads(kept_ref.read_text(encoding="utf-8"))["zeropoint"] if kept_ref.exists() else None
    say(f"{len(record['candidates'])} candidates in {session}")
    checks = {}
    if record["candidates"] and not args.offline:
        ra = np.array([c["ra"] for c in record["candidates"]])
        dec = np.array([c["dec"] for c in record["candidates"]])
        centre_ra, centre_dec = float(np.median(ra)), float(np.median(dec))
        reach = float(separation(centre_ra, centre_dec, ra, dec).max()) / 3600 + 0.02
        stamps = [stacking.load_light(p)[1].get("DATE-OBS") for p in sorted(session.glob("light-*.fits"))[::50]]
        stamps = [s for s in stamps if s]
        jd = float(np.mean([Time(s).jd for s in stamps])) if stamps else Time.now().jd
        year = Time(jd, format="jd").datetime.year
        for key, fetch in (("asteroids", lambda: asteroids(centre_ra, centre_dec, reach, jd)),
                           ("variables", lambda: variables(centre_ra, centre_dec, reach)),
                           ("reported", lambda: reported((year - 1, year))),
                           ("gaia", lambda: [{"ra": a, "dec": d, "g": g}
                                             for a, d, g, *_ in depth.gaia(centre_ra, centre_dec, reach)])):
            try:
                checks[key] = fetch()
                say(f"  {key}: {len(checks[key])} in the field")
            except requests.RequestException as error:
                say(f"  {key}: not asked ({error.__class__.__name__})")
    half_scores = None
    if record["candidates"] and not args.no_halves:
        paths = restack_frames(session)
        if len(paths) >= HALVES_FROM:
            say(f"stacking each half of {len(paths)} frames")
            half_scores = each_half(record, ref, ref_wcs, paths, name, say)
    evidence = vet(record, checks, half_scores, ref, zeropoint, radius=max(record.get("fwhm_px", 4.0), 2.0))
    left = [e for e in evidence if e["verdict"] == UNEXPLAINED]
    summary = {"session": str(session), "candidates": evidence, "unexplained": len(left),
               "asked": sorted(checks), "halves_checked": half_scores is not None,
               "band": record.get("band")}
    records.write(session / "vetted.json", summary, schema="vet", stamp=True)
    counts = {}
    for e in evidence:
        key = e["verdict"].split(":")[0].split(" (")[0]
        counts[key] = counts.get(key, 0) + 1
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        say(f"  {n:4d}  {key}")
    for e in left:
        say(f"  UNEXPLAINED {e['score']:5.1f} sigma  RA {e['ra']:.5f} Dec {e['dec']:+.5f}"
            + (f"  G~{e['mag']:.1f}" if e.get("mag") else "") + f"  halves {e.get('halves')}"
            + "".join(f"\n      clue: {c}" for c in e["clues"]))
    say(f"kept as {session / 'vetted.json'}")
    return summary


def restack_frames(session):
    """The frames the quality pass kept, in the order they were taken."""
    log = session / "restack.json"
    if log.exists():
        kept = json.loads(log.read_text(encoding="utf-8")).get("kept", [])
        return [session / n for n in sorted(Path(k).name for k in kept) if (session / n).exists()]
    return sorted(session.glob("light-*.fits"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", help="the session difference.py was run on: an object or a session folder")
    ap.add_argument("--offline", action="store_true", help="ask no catalogue on the internet")
    ap.add_argument("--no-halves", action="store_true", help="do not stack and check each half of the night")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("vet", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
