#!/usr/bin/env python3
"""Known exoplanets crossing their stars, seen from here: which transits
the telescope can catch tonight, and what a night's frames measured.

    ./transits.py                       tonight's transits worth taking, deepest first
    ./transits.py --deeper 1.5 --json
    ./transits.py measure frames/HAT-P-32/20261020-210000 --planet "HAT-P-32 b"

A hot Jupiter dims its star by 1 to 3% for two or three hours, once every
few days: within reach of a 150 mm telescope and a stack of short frames.
Amateurs time them for the ExoClock project (exoclock.space), which keeps
the ephemerides of the planets ESA's Ariel mission will study; a transit
that comes early or late is a sign of something more in the system.

The planets are NASA's Exoplanet Archive's (its composite table), kept for
a week under cache/. Tonight's list keeps the transits whose whole length,
with BASELINE minutes either side to measure the star out of transit, is
in the dark and above the horizon limits and the measured skyline, around
a star between BRIGHTEST and FAINTEST in V, and at least --deeper percent
deep. Each listed star is kept by name (cache/transients.json) so that
./mount.py goto NAME and ./shoot.py NAME know it.

`measure` makes the star's light curve from the night's frames as
variables.py does (batches of --bin frames, put on Gaia's scale by every
other star in the picture), then fits a transit of the known length: the
depth, and when its middle came against the prediction. Nothing here moves
the mount or uses the camera; submitting a timing to ExoClock is a
person's decision, through its own site.
"""
import argparse
import csv
import io
import json
import math
import time
from pathlib import Path

import numpy as np
import requests
from astropy.time import Time

import config
import interface

ARCHIVE = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
QUERY = ("select pl_name,hostname,ra,dec,sy_vmag,pl_orbper,pl_tranmid,pl_trandur,pl_trandep "
         "from pscomppars where pl_trandep>0.3 and sy_vmag<{faintest} and dec>-20 and pl_tranmid is not null "
         "and pl_orbper is not null and pl_trandur is not null")
FRESH_DAYS = 7       # the planet list is fetched again after this long
BASELINE = 30        # minutes either side of the transit, to measure the star out of it
BRIGHTEST = 10.5     # V: brighter fills the camera's wells in a 16 s frame (variables.BRIGHTEST)
FAINTEST = 13.0      # V: fainter is too noisy for a 1% dip
DEEPER = 1.0         # percent: the shallowest transit listed by default
SEARCH = 60          # minutes either side of the predicted middle the fit looks
BIN = 10


# --- the planets ---------------------------------------------------------------

def store():
    return config.DATA / "cache" / "transiting.csv"


def planets(get=requests.get, now=None):
    """The transiting planets round stars bright enough, from the archive or
    the copy kept this week."""
    path = store()
    now = now or time.time()
    if not path.exists() or now - path.stat().st_mtime > FRESH_DAYS * 86400:
        reply = get(ARCHIVE, timeout=120, params={"query": QUERY.format(faintest=FAINTEST), "format": "csv"})
        reply.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(reply.text, encoding="utf-8")
    rows = []
    for r in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        try:
            rows.append({"planet": r["pl_name"], "star": r["hostname"], "ra": float(r["ra"]), "dec": float(r["dec"]),
                         "v": float(r["sy_vmag"]) if r["sy_vmag"] else None, "period": float(r["pl_orbper"]),
                         "epoch": float(r["pl_tranmid"]), "hours": float(r["pl_trandur"]),
                         "depth": float(r["pl_trandep"])})
        except (KeyError, ValueError):
            continue
    return rows


def transits_between(p, start_jd, end_jd):
    """The middles (JD) of a planet's transits between two times."""
    first = math.ceil((start_jd - p["epoch"]) / p["period"])
    last = math.floor((end_jd - p["epoch"]) / p["period"])
    return [p["epoch"] + n * p["period"] for n in range(first, last + 1)]


# --- tonight -----------------------------------------------------------------

def tonight(cfg, rows, deeper=DEEPER, now=None, say=print):
    """The transits that can be taken whole tonight, deepest first."""
    import sky
    night = sky.Night(cfg, now=now)
    jd = night.times.jd
    usable = [p for p in rows if p["depth"] >= deeper and p["v"] is not None and BRIGHTEST <= p["v"] <= FAINTEST]
    out = []
    if usable:
        alt, az = night.altaz_fixed([p["ra"] for p in usable], [p["dec"] for p in usable])
        for k, p in enumerate(usable):
            ok = night.dark & night.future & (alt[k] >= night.horizon(az[k], night.min_alt))
            for middle in transits_between(p, jd[0], jd[-1]):
                half = p["hours"] / 48 + BASELINE / 1440
                inside = (jd >= middle - half) & (jd <= middle + half)
                if inside.sum() and ok[inside].all() and jd[0] <= middle - half and middle + half <= jd[-1]:
                    i = int(np.argmin(np.abs(jd - middle)))
                    out.append(dict(p, middle=round(middle, 5),
                                    start=night.local(int(np.argmax(inside))).strftime("%H:%M"),
                                    mid=night.local(i).strftime("%H:%M"),
                                    end=night.local(len(jd) - 1 - int(np.argmax(inside[::-1]))).strftime("%H:%M"),
                                    altitude=round(float(alt[k][i]), 1)))
    out.sort(key=lambda t: -t["depth"])
    return {"night": str(night.date), "deeper": deeper, "planets": len(rows), "bright_and_deep": len(usable),
            "transits": out, "kind": "inferred"}


def keep(transits):
    """Each listed star by name, for mount.py and shoot.py."""
    path = config.DATA / "cache" / "transients.json"
    kept = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for t in transits:
        kept[t["star"]] = {"ra": round(t["ra"], 6), "dec": round(t["dec"], 6), "kept_by": "transits.py",
                           "planet": t["planet"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept, indent=1), encoding="utf-8")


# --- after the night -----------------------------------------------------------

def box(jd, middle, hours):
    """1 inside a transit of this length and middle, 0 outside."""
    return (np.abs(np.asarray(jd) - middle) <= hours / 48).astype(float)


def fit(jd, mag, middle, hours, search=SEARCH):
    """The transit's depth (percent) and middle (JD) that fit the light
    curve best, the middle sought within `search` minutes of the
    prediction; with the depth's error from the scatter out of transit."""
    jd, mag = np.asarray(jd, float), np.asarray(mag, float)
    ok = np.isfinite(mag)
    jd, mag = jd[ok], mag[ok]
    best = None
    for shift in np.arange(-search, search + 1, 2) / 1440:
        inside = box(jd, middle + shift, hours) > 0
        if inside.sum() < 2 or (~inside).sum() < 2:
            continue
        drop = float(np.mean(mag[inside]) - np.mean(mag[~inside]))
        model = np.where(inside, drop, 0.0) + np.mean(mag[~inside])
        chi = float(np.sum((mag - model) ** 2))
        if best is None or chi < best[0]:
            best = (chi, shift, drop, inside)
    if best is None:
        return None
    _, shift, drop, inside = best
    spread = float(np.std(mag[~inside], ddof=1)) if (~inside).sum() > 2 else float("nan")
    error = spread * math.sqrt(1 / inside.sum() + 1 / (~inside).sum())
    to_percent = lambda m: 100 * (1 - 10 ** (-0.4 * m))
    return {"depth": round(to_percent(drop), 2), "depth_error": round(100 * 0.921 * error, 2),
            "middle": round(middle + shift, 5), "early_late_min": round(shift * 1440, 1),
            "scatter_mmag": round(1000 * spread, 1), "in_transit_points": int(inside.sum()),
            "out_of_transit_points": int((~inside).sum())}


def measure(session, planet, size=BIN, say=print, rows=None, night=None):
    """The planet's star in a night's frames: its light curve and the fitted
    transit beside the predicted one."""
    import variables
    import vet
    session = Path(session)
    rows = rows if rows is not None else planets()
    p = next((r for r in rows if r["planet"].replace(" ", "").lower() == planet.replace(" ", "").lower()), None)
    if p is None:
        raise interface.Refusal("TARGET_UNKNOWN", f"'{planet}' is not among the transiting planets kept.")
    n = night or variables.night(session, session.parent.name, size, say)
    stars = np.asarray(n["stars"])
    if not len(stars):
        raise interface.Refusal("NO_SESSION", f"No star measured in {session.name}.")
    near = vet.separation(p["ra"], p["dec"], stars[:, 0], stars[:, 1])
    j = int(np.argmin(near))
    if near[j] > 5:
        raise interface.Refusal("NO_SESSION", f"{p['star']} is not among the stars measured in {session.name} "
                                              f"(the nearest is {near[j]:.0f}\" away): outside the picture, or too "
                                              f"bright or too crowded to measure.")
    jd = np.array(n["jd"], float)
    mag = np.asarray(n["mags"])[:, j]
    middles = transits_between(p, jd.min() - 0.5, jd.max() + 0.5)
    predicted = min(middles, key=lambda m: abs(m - jd.mean())) if middles else None
    result = fit(jd, mag, predicted, p["hours"]) if predicted is not None else None
    answer = {"planet": p["planet"], "star": p["star"], "session": session.name,
              "predicted_middle": predicted, "expected_depth": p["depth"], "hours": p["hours"],
              "fit": result, "jd": [round(t, 5) for t in jd], "mag": [None if not np.isfinite(m) else round(float(m), 4)
                                                                     for m in mag], "kind": "measured"}
    (session / f"transit-{p['planet'].replace(' ', '')}.json").write_text(json.dumps(answer, indent=1),
                                                                         encoding="utf-8")
    if result:
        say(f"{p['planet']}: {result['depth']:.2f} ± {result['depth_error']:.2f}% deep (expected {p['depth']:.2f}%), "
            f"middle {result['early_late_min']:+.1f} min against the prediction; "
            f"{result['scatter_mmag']} mmag scatter out of transit")
    else:
        say(f"{p['planet']}: the night's frames do not cover a transit and time either side of it")
    return answer


def run(args, say=print):
    if args.action == "measure":
        if not args.session or not args.planet:
            raise interface.Refusal("INVALID_REQUEST", "measure needs a session and --planet.")
        return measure(args.session, args.planet, args.bin, say)
    cfg = config.example() if args.demo else config.load()
    answer = tonight(cfg, planets(), args.deeper)
    if not args.demo:
        keep(answer["transits"])
    say(f"{answer['bright_and_deep']} of {answer['planets']} transiting planets round stars of V {BRIGHTEST:g} to "
        f"{FAINTEST:g} are {args.deeper:g}% deep or more; {len(answer['transits'])} transit whole in the dark here tonight")
    for t in answer["transits"]:
        say(f"  {t['planet']:<14} {t['depth']:.2f}% deep, V {t['v']:.1f}, {t['start']} to {t['end']} "
            f"(middle {t['mid']}, {t['altitude']:.0f}° high): ./mount.py goto {t['star'].replace(' ', '')}")
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", choices=("tonight", "measure"), default="tonight")
    ap.add_argument("session", nargs="?", help="measure: the night's session folder")
    ap.add_argument("--planet", help="measure: the planet, as the archive names it (\"HAT-P-32 b\")")
    ap.add_argument("--deeper", type=float, default=DEEPER, help=f"percent: the shallowest listed (default {DEEPER:g})")
    ap.add_argument("--bin", type=int, default=BIN, help=f"measure: frames in each point (default {BIN})")
    ap.add_argument("--demo", action="store_true", help="the example site instead of config.toml")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("transits", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
