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

import config
import interface
import records

ARCHIVE = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
QUERY = ("select pl_name,hostname,ra,dec,sy_vmag,pl_orbper,pl_tranmid,pl_trandur,pl_trandep "
         "from pscomppars where pl_trandep>0.3 and sy_vmag<{faintest} and dec>-20 and pl_tranmid is not null "
         "and pl_orbper is not null and pl_trandur is not null")
FRESH_DAYS = 7       # the planet list is fetched again after this long
BASELINE = 30        # minutes either side of the transit, to measure the star out of it
BRIGHTEST = 10.5     # V: brighter fills the camera's wells in a 16 s frame (variables.BRIGHTEST)
FAINTEST = 13.0      # V: fainter is too noisy for a 1% dip
DEEPER = 1.0         # percent: the shallowest transit listed by default
FULL_WELL = 12.7     # V: brighter fills the camera's wells in a 16 s frame on a sharp night: take 4 s frames
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
                                    altitude=round(float(alt[k][i]), 1),
                                    exposure=4 if p["v"] < FULL_WELL else 16))
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
    records.write(path, kept)


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
    half = hours / 48
    # The middle is only timed with the star's light seen both before the
    # transit and after it: with one side only, an earlier middle and a
    # deeper dip fit the same points (20 October 2026: egress lost to cloud).
    timed = bool(np.any(jd < middle - half) and np.any(jd > middle + half))
    return {"depth": round(to_percent(drop), 2), "depth_error": round(100 * 0.921 * error, 2),
            "middle": round(middle + shift, 5), "early_late_min": round(shift * 1440, 1), "timed": timed,
            "scatter_mmag": round(1000 * spread, 1), "in_transit_points": int(inside.sum()),
            "out_of_transit_points": int((~inside).sum())}


def draw(answer, path, size=(900, 420)):
    """The light curve as a picture: the star's brightness against the
    baseline before the transit (in percent, brighter up), with the
    predicted transit shaded and the fitted dip drawn over the points;
    times in UTC."""
    from PIL import Image, ImageDraw
    jd = np.array(answer["jd"], float)
    mag = np.array([np.nan if m is None else m for m in answer["mag"]], float)
    ok = np.isfinite(mag)
    image = Image.new("RGB", size, "white")
    pen = ImageDraw.Draw(image)
    if ok.sum() < 2:
        image.save(path)
        return str(path)
    jd, mag = jd[ok], mag[ok]
    middle, half = answer.get("predicted_middle"), answer["hours"] / 48
    outside = (np.abs(jd - middle) > half) if middle else np.ones_like(jd, bool)
    base = float(np.median(mag[outside] if outside.any() else mag))
    flux = 100 * (10 ** (-0.4 * (mag - base)) - 1)                 # percent against the baseline
    left, right, top, bottom = 70, size[0] - 20, 40, size[1] - 50
    t0, t1 = float(jd.min()), float(jd.max())
    if middle:
        t0, t1 = min(t0, middle - half), max(t1, middle + half)
    lo, hi = min(float(np.percentile(flux, 1)), -1.5 * answer["expected_depth"]), max(float(np.percentile(flux, 99)), 1.0)

    def x(t):
        return left + (t - t0) / (t1 - t0) * (right - left)

    def y(f):
        return top + (hi - f) / (hi - lo) * (bottom - top)
    if middle:
        pen.rectangle([x(middle - half), top, x(middle + half), bottom], fill=(236, 240, 248))
        pen.text((x(middle - half) + 4, top + 4), "predicted transit", fill="grey")
    pen.line([left, y(0), right, y(0)], fill="grey")
    for t, f in zip(jd, flux):
        pen.ellipse([x(t) - 3, y(f) - 3, x(t) + 3, y(f) + 3], fill="black")
    fitted = answer.get("fit")
    if fitted:
        m, d = fitted["middle"], -fitted["depth"]
        pen.line([(left, y(0)), (x(m - half), y(0)), (x(m - half), y(d)), (x(m + half), y(d)),
                  (x(m + half), y(0)), (right, y(0))], fill=(200, 40, 40), width=2)
    for f in (0, -answer["expected_depth"]):
        pen.text((4, y(f) - 6), f"{f:+.1f}%", fill="grey")
    hours = np.arange(math.ceil(t0 * 24), math.floor(t1 * 24) + 1) / 24
    for h in hours:
        label = time.strftime("%H:%M", time.gmtime((h - 2440587.5) * 86400))
        pen.line([x(h), bottom, x(h), bottom + 5], fill="grey")
        pen.text((x(h) - 14, bottom + 8), label, fill="grey")
    title = f"{answer['planet']} on {answer['session'][:8]}, UTC: the star's light against the baseline"
    if fitted:
        title += f"; fitted dip {fitted['depth']:.2f} ± {fitted['depth_error']:.2f}% (expected {answer['expected_depth']:.2f}%)"
    pen.text((left, 12), title, fill="black")
    image.save(path)
    return str(path)


CHECK_BINS = (1, 2, 4, 8)    # points averaged, for how the scatter falls


def falls(mag, bins=CHECK_BINS):
    """The scatter (mmag) of points averaged in runs of each of `bins`, and
    beta: the scatter at the most points against what random noise alone
    would leave. Near 1, the points' noise is random; well above it, a
    slow systematic drift is mixed in and a fit's error is too small."""
    mag = np.asarray(mag, float)
    mag = mag[np.isfinite(mag)]
    out = {}
    for n in bins:
        m = len(mag) // n
        if m >= 4:
            means = mag[:m * n].reshape(m, n).mean(axis=1)
            out[n] = round(1000 * float(np.std(means, ddof=1)), 2)
    if 1 not in out or len(out) < 2:
        return out, None
    ratios = [out[n] / (out[1] / math.sqrt(n)) for n in out if n > 1]
    return out, round(float(np.median(ratios)), 2)


def checks(session, jd, mag, middle, hours, site=None):
    """What a reader of the result needs to weigh it: the calibration the
    frames had, how the scatter falls with averaging, and how the times
    were made (BJD_TDB where the site is known). 20 October 2026: a review
    of the first transit asked for all three."""
    import stacking
    frames = sorted(Path(session).glob("light-*.fits"))
    out = {"calibration": [], "timing": {}}
    if frames:
        head = stacking.load_light(frames[0])[1]
        exposure, gain = float(head.get("EXPTIME", 0)), int(float(head.get("GAIN", 0)))
        if not stacking.master_path("dark", exposure, gain).exists():
            darks = sorted(stacking.CALIBRATION.glob(f"dark-*-g{gain}.fits"))
            out["calibration"].append(f"no dark matched to the {exposure:g} s frames at gain {gain}"
                                      + (f" (only {', '.join(d.stem for d in darks)})" if darks else "")
                                      + ": the bias alone was taken off")
        if not stacking.master_path("flat").exists():
            out["calibration"].append("no flat field: each star's light changes as it drifts over the sensor")
        out["timing"]["frame_time"] = "DATE-OBS, the start of each exposure, plus half the exposure"
        try:
            log = [json.loads(line) for line in (Path(session) / "frames.jsonl").read_text().splitlines()[:20]]
            from astropy.time import Time
            starts = {int(f.stem.split("-")[1]): Time(stacking.load_light(f)[1]["DATE-OBS"]).unix
                      for f in frames[:20]}
            lag = [r["taken"] - starts[r["index"]] for r in log if r.get("taken") and r.get("index") in starts]
            if lag:
                out["timing"]["frame_kept_after_start_s"] = round(float(np.median(lag)), 2)
        except (OSError, ValueError, KeyError):
            pass
    try:
        clock = json.loads((Path(session) / "session.json").read_text(encoding="utf-8")).get("clock")
    except (OSError, ValueError):
        clock = None
    out["timing"]["clock"] = clock or "not recorded for this session (shoot.py records it since 20 October 2026)"
    before = np.asarray(jd) < (middle - hours / 48) if middle else np.ones(len(jd), bool)
    out["scatter_by_points"], out["beta"] = falls(np.asarray(mag, float)[before])
    if site is not None and len(jd):
        from astropy.coordinates import EarthLocation
        import astropy.units as u
        where = EarthLocation(lat=site["latitude"] * u.deg, lon=site["longitude"] * u.deg,
                              height=site.get("elevation_m", 0) * u.m)
        out["timing"]["bjd_tdb"] = "each point's time as BJD_TDB is in bjd_tdb"
        out["_where"] = where
    return out


def bjd_tdb(jd, ra, dec, where):
    """Julian dates (UTC) as barycentric dates in TDB, for the star at ra, dec."""
    from astropy.coordinates import SkyCoord
    from astropy.time import Time
    import astropy.units as u
    t = Time(np.asarray(jd, float), format="jd", scale="utc", location=where)
    return (t.tdb + t.light_travel_time(SkyCoord(ra * u.deg, dec * u.deg))).jd


FULL = 4095          # the camera's highest reading (12 bits)
LINEAR = 0.7         # share of FULL a star's peak may reach and stay linear


def headroom(session, ra, dec, size=BIN, frames=5):
    """How bright the target's peak pixel is in the first raw frames, less
    the sky, and so the longest exposure that keeps it under LINEAR of
    FULL, scaled from this one (in focus; a little defocus spreads the light
    and allows longer). None without the night's star places."""
    import stacking
    session = Path(session)
    try:
        kept = json.loads((session / f"variables-{size}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stars = np.array([[np.nan if v is None else v for v in row[:2]] for row in kept["stars"]], float)
    if not len(stars):
        return None
    j = int(np.argmin(np.hypot((stars[:, 0] - ra) * math.cos(math.radians(dec)), stars[:, 1] - dec)))
    x, y = (2 * v for v in kept["xy"][j])          # the stacks are 2x2 superpixels of the raw frame
    peaks, exposure = [], None
    for path in sorted(session.glob("light-*.fits"))[:frames]:
        raw, head = stacking.load_light(path)
        exposure = float(head.get("EXPTIME", 0)) or exposure
        cut = raw[max(int(y) - 30, 0):int(y) + 31, max(int(x) - 30, 0):int(x) + 31].astype(float)
        if cut.size:
            peaks.append(float(cut.max() - np.median(raw[::16, ::16])))
    if not peaks or not exposure:
        return None
    peak = float(np.median(peaks))
    return {"peak": round(peak), "of": FULL, "exposure": exposure,
            "longest_linear_s": round(exposure * LINEAR * FULL / max(peak, 1.0), 1)}


def verdict(result, expected):
    """The headline: what the night shows, before any fitted number."""
    if not result:
        return "No transit measured: the frames do not cover one with time either side."
    if not result["timed"]:
        return ("Transit-like dimming seen, but not independently measurable: the star was not watched both "
                f"before and after the transit. Exploratory fit: {result['depth']:.2f} ± "
                f"{result['depth_error']:.2f}% (expected {expected:.2f}%); timing unconstrained.")
    return (f"Transit measured: {result['depth']:.2f} ± {result['depth_error']:.2f}% deep (expected "
            f"{expected:.2f}%), middle {result['early_late_min']:+.1f} min against the prediction.")


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
    exposure = None
    try:
        exposure = json.loads((session / "session.json").read_text(encoding="utf-8")).get("exposure")
    except (OSError, ValueError):
        pass
    n = night or variables.night(session, session.parent.name, size, say, brightest=variables.trusted(exposure))
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
    try:
        site = config.load()["site"]
    except (SystemExit, KeyError, OSError):
        site = None
    looked = checks(session, jd, mag, predicted, p["hours"], site)
    looked["headroom"] = headroom(session, p["ra"], p["dec"], size)
    where = looked.pop("_where", None)
    answer = {"planet": p["planet"], "star": p["star"], "session": session.name,
              "predicted_middle": predicted, "expected_depth": p["depth"], "hours": p["hours"],
              "fit": result, "verdict": verdict(result, p["depth"]), "checks": looked,
              "jd": [round(t, 5) for t in jd], "mag": [None if not np.isfinite(m) else round(float(m), 4)
                                                       for m in mag], "kind": "measured"}
    if where is not None:
        answer["bjd_tdb"] = [round(float(t), 6) for t in bjd_tdb(jd, p["ra"], p["dec"], where)]
    records.write(session / f"transit-{p['planet'].replace(' ', '')}.json", answer, schema="transits", stamp=True)
    picture = draw(answer, session / f"transit-{p['planet'].replace(' ', '')}.png")
    say(f"{p['planet']}: {answer['verdict']}")
    if result:
        say(f"  scatter out of transit {result['scatter_mmag']} mmag per point; averaged over "
            + ", ".join(f"{n} points {v}" for n, v in looked["scatter_by_points"].items())
            + (f" (beta {looked['beta']}: 1 for random noise)" if looked["beta"] else ""))
    for line in looked["calibration"]:
        say(f"  calibration: {line}")
    room = looked["headroom"]
    if room:
        say(f"  {p['star']} peaks at {room['peak']} of {room['of']} in {room['exposure']:g} s frames: up to about "
            f"{room['longest_linear_s']:g} s in focus keeps it linear")
    say(f"  the curve: {picture}")
    return answer


def before_the_night(transits, gain=None):
    """What a transit night needs first, from the calibration kept: a flat
    field, and a dark matched to each exposure listed (a review of the first
    transit, 20 October 2026: no flat, and a 1 s dark for 4 s frames)."""
    import stacking
    if not transits:
        return []
    gain = gain if gain is not None else config.hardware()["camera"].get("gain", 1500)
    out = []
    if not stacking.master_path("flat").exists():
        out.append("no flat field: ./calibrate.py flat before imaging (the stars drift over the sensor's dust "
                   "and vignetting without one)")
    for exposure in sorted({t["exposure"] for t in transits}):
        if not stacking.master_path("dark", exposure, gain).exists():
            out.append(f"no dark for {exposure:g} s at gain {gain}: ./calibrate.py dark --exposure {exposure:g} "
                       f"--gain {gain}")
    out.append("image with ./shoot.py STAR --hold 5 (the stars kept on the same pixels, no dithering), from an "
               "hour before the transit to an hour after it")
    return out


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
            f"(middle {t['mid']}, {t['altitude']:.0f}° high), {t['exposure']} s frames: ./mount.py goto "
            f"{t['star'].replace(' ', '')}")
    answer["before"] = before_the_night(answer["transits"])
    for line in answer["before"]:
        say(f"  before: {line}")
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
