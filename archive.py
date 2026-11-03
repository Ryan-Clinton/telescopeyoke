#!/usr/bin/env python3
"""Dips in a star's Kepler light curve, from the public archive: the search
for stars that behave like Tabby's star, done on four years of a space
telescope's measurements instead of our own nights.

    ./archive.py dips KIC 8462852        Tabby's star: its dips, each with depth, length and shape
    ./archive.py dips Tabby --json
    ./archive.py search stars.txt        each KIC number in the file (one a line), most Tabby-like first
    ./archive.py search 8462852,7106205
    ./archive.py screen --batch 500      the next 500 Kepler stars not yet screened, brightest first

`screen` works through every star Kepler watched (about 200,000, NASA's
Exoplanet Archive's list, brightest first), keeping each one's answer in
cache/kepler/screened.json as it goes, so each run carries on where the
last stopped; big batches belong on the desktop:
    ssh desktop 'cd ~/telescopeyoke-laptop && ./archive.py screen --batch 5000'

Kepler watched about 150,000 stars in Cygnus and Lyra every 30 minutes
from 2009 to 2013. Its light curves are public at MAST (the Mikulski
Archive for Space Telescopes); this reads each star's long-cadence files
straight from MAST's file tree and keeps them under cache/kepler/. Each
quarter's PDCSAP flux (the mission's own cleaned light curve), points with
no quality flag only, is divided by its median, so the star's level is 1.

A dip follows variables.py's rules for our own light curves, scaled to
Kepler: at least DIP_RUN points in a row (an hour and a half), each below
the star's level by DIP_SIGMA times its usual scatter (a robust one, from
the median absolute deviation) and by DIP_DEPTH at least. Each dip is
widened to where the light comes back near the level (within BACK of
DIP_DEPTH, or one scatter if that is more),
and given its middle (the faintest point), depth, length, and shape: how
long the fall took against the recovery (asymmetry -1 to 1: positive when
the recovery is the slower, negative when the fall is; a planet's transit
is 0, a comet's tail dims slowly after a sharp start).

Before anything is called a dip it is checked against what is not the star:
  - edge: its faintest point is at the start or end of a quarter, or at a
    gap in the data, where the mission's cleaning bends the light curve;
  - spacecraft: a dip of less than a day with a quality flag (attitude
    tweak, safe mode, coarse or Earth point, momentum dump, manual
    exclusion) within FLAG_HOURS of its faintest point;
  - periodic: three or more dips of like depth at whole multiples of one
    interval: an eclipsing binary or a planet, not a dipper;
  - variability: dips cover more than VARIABLE of the good points: the
    star's own spots or pulsation, not occasional dips.
What is left is a "dip". A star is Tabby-like when it has a dip at least
DEEP deep and its light is otherwise steady (scatter at most QUIET);
stars are ranked Tabby-like first, then by the dips left, deep and
lopsided first.

Each dip is also measured in the SAP flux (the light in the aperture
before the mission's cleaning) and said to be in both, or in PDCSAP
only; dips in SAP that PDCSAP does not have are listed apart. The
cleaning takes out what it judges the spacecraft's: pointing drift, focus
and thermal changes, and sudden drops in a pixel's sensitivity (Kepler
Archive Manual, section 2.3.1.2). Each quarter being put on its own level
also takes out any slow change, so the long-term trend is measured
separately, with the quarters joined at their edges (Tabby's star faded
about 3% over Kepler's four years: Montet & Simon 2016).
An odd light curve here is a reason to look, not a discovery: each still
needs its catalogue checks (VSX, SIMBAD) and the papers on it.
Nothing here moves the mount or uses the camera.
"""
import argparse
import re
from pathlib import Path

import numpy as np
import requests

import config
import interface

MAST = "https://archive.stsci.edu/missions/kepler/lightcurves/{group}/{kic}/"
BKJD = 2454833.0     # Kepler's times are BJD minus this
TABBY = 8462852
TIMEOUT = 120
FETCHING = 8         # a star's quarters fetched at once
TARGETS = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
TARGET_QUERY = "select distinct kepid, kepmag from keplerstellar where kepmag is not null order by kepmag"

DIP_RUN = 3          # points in a row (variables.DIP_RUN), 30 minutes apart
DIP_SIGMA = 3.0      # times the usual scatter below the level (variables.DIP_SIGMA)
DIP_DEPTH = 0.01     # and at least this far below it: 1%, about variables.DIP_DEPTH's 0.02 mag halved for Kepler's precision
EDGE_DAYS = 0.5      # this close to a quarter's end or a gap is an edge
GAP_DAYS = 0.5       # a break this long in the good points is a gap
FLAG_HOURS = 2.0     # a quality flag this close to a short dip's faintest point puts it on the spacecraft
                     # (6 at first: with a dump every three days that took a third of KIC 8129189's eclipses)
SHORT_HOURS = 24.0   # only a dip shorter than this can be a spacecraft event: a momentum dump or a
                     # tweak upsets a few hours; Kepler had a dump every three days, so a dip of days
                     # always has one near it
BACK = 0.25          # a dip is widened to where the light is back within this share of DIP_DEPTH
SUSPECT = 1 | 2 | 4 | 8 | 32 | 128    # attitude tweak, safe mode, coarse point, Earth point, momentum dump, manual exclude
PERIOD_TOLERANCE = 0.02   # an interval within this share of a whole multiple
LIKE_DEPTH = 0.3          # depths within this share of their mean are alike
PAIR_DEPTH = 0.1          # two dips this alike in depth...
PAIR_HOURS = 0.2          # ...and in length...
PAIR_SYMMETRIC = 0.3      # ...each this symmetric, are one eclipse seen twice
VARIABLE = 0.05           # dips over this share of the good points: the star's own variability
DEEP = 0.05               # a dip this deep makes a star Tabby-like...
QUIET = 0.01              # ...when its light is otherwise this steady (scatter): Tabby's is 0.03%. KIC
                          # 7988797's 12.6% dip on 4.2% scatter (3 November 2026) is a restless star's


def kic_number(words):
    """The KIC number in 'KIC 8462852', 'KIC8462852', '8462852' or 'Tabby'."""
    text = " ".join(words) if isinstance(words, (list, tuple)) else str(words)
    if text.strip().lower() in ("tabby", "tabby's star", "boyajian's star"):
        return TABBY
    found = re.search(r"(\d{5,9})", text)
    if not found:
        raise interface.Refusal("INVALID_REQUEST", f"No KIC number in {text!r}: give it as KIC 8462852.")
    return int(found.group(1))


def store(kic):
    return config.DATA / "cache" / "kepler" / f"{kic:09d}"


def files(kic, get=requests.get):
    """The URLs of a star's long-cadence light curves at MAST."""
    padded = f"{kic:09d}"
    url = MAST.format(group=padded[:4], kic=padded)
    reply = get(url, timeout=TIMEOUT)
    if getattr(reply, "status_code", 200) == 404:
        raise interface.Refusal("INVALID_REQUEST", f"Kepler has no light curves of KIC {kic}.")
    reply.raise_for_status()
    names = sorted(set(re.findall(rf"kplr{padded}-\d+_llc\.fits", reply.text)))
    return [url + name for name in names]


def fetch(kic, get=requests.get, say=print):
    """The star's light-curve files, from the copy kept or from MAST."""
    folder = store(kic)
    kept = sorted(folder.glob("*_llc.fits"))
    if kept:
        return kept
    urls = files(kic, get)
    if not urls:
        raise interface.Refusal("INVALID_REQUEST", f"Kepler has no long-cadence light curves of KIC {kic}.")
    folder.mkdir(parents=True, exist_ok=True)
    say(f"fetching {len(urls)} quarters of KIC {kic} from MAST")

    def one(url):
        reply = get(url, timeout=TIMEOUT)
        reply.raise_for_status()
        part = folder / (url.rsplit("/", 1)[1] + ".part")
        part.write_bytes(reply.content)
        part.rename(folder / url.rsplit("/", 1)[1])
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(FETCHING) as pool:
        list(pool.map(one, urls))
    return sorted(folder.glob("*_llc.fits"))


def read(paths):
    """One light curve from the quarters' files: time (BKJD), the PDCSAP
    flux and the SAP flux each divided by its quarter's median (NaN where
    not usable), both as they came (sap_raw, pdc_raw, for the long-term
    trend), the quality flags and the quarter."""
    from astropy.io import fits
    names = ("t", "f", "sap", "pdc_raw", "sap_raw", "q", "quarter")
    parts = {n: [] for n in names}
    for path in paths:
        with fits.open(path, memmap=False) as hdul:
            data = hdul[1].data
            number = hdul[0].header.get("QUARTER", -1)
            time = np.array(data["TIME"], float)
            pdc = np.array(data["PDCSAP_FLUX"], float)
            sap = np.array(data["SAP_FLUX"], float) if "SAP_FLUX" in data.columns.names else np.full(len(time), np.nan)
            flags = np.array(data["SAP_QUALITY"], int)
        keep = np.isfinite(time)
        good = keep & np.isfinite(pdc) & (flags == 0)
        if not good.any():
            continue
        pdc = np.where(good, pdc, np.nan)
        sap = np.where(keep & np.isfinite(sap) & (flags == 0), sap, np.nan)
        sap_level = np.nanmedian(sap) if np.isfinite(sap).any() else np.nan
        for name, value in (("t", time), ("f", pdc / np.nanmedian(pdc)), ("sap", sap / sap_level),
                            ("pdc_raw", pdc), ("sap_raw", sap), ("q", flags), ("quarter", np.full(len(time), number))):
            parts[name].append(value[keep])
    if not parts["t"]:
        return {n: np.array([], int if n in ("q", "quarter") else float) for n in names}
    return {n: np.concatenate(v) for n, v in parts.items()}


STITCH_DAYS = 1.0    # each quarter is put on the last's level by the medians of the day either side of the break


def trend(t, raw, quarter):
    """The star's slow change across the quarters, without putting each on
    its own level: each quarter is scaled so the median of its first
    STITCH_DAYS meets the median of the last STITCH_DAYS of the one before
    (the star sits on another CCD after each quarterly roll, so a scale
    per quarter is needed; fitted on the edges, it keeps whatever the star
    did within and across quarters). Answers the straight-line change in
    percent a year and the change from the first 30 days to the last 30,
    or None with too little."""
    good = np.isfinite(raw)
    if good.sum() < 100:
        return None
    t, raw, quarter = t[good], raw[good], quarter[good]
    order = sorted(set(quarter.tolist()), key=lambda n: t[quarter == n].min())
    stitched = np.empty_like(raw)
    tail = None
    for n in order:
        inside = quarter == n
        tq, fq = t[inside], raw[inside]
        head = np.median(fq[tq <= tq.min() + STITCH_DAYS])
        scale = 1.0 if tail is None else tail / head
        stitched[inside] = fq * scale
        tail = np.median(stitched[inside][tq >= tq.max() - STITCH_DAYS])
    stitched = stitched / np.median(stitched[t <= t.min() + 30])
    years = (t - t.min()) / 365.25
    slope, start = np.polyfit(years, stitched, 1)
    late = np.median(stitched[t >= t.max() - 30])
    return {"percent_per_year": round(float(100 * slope / start), 2),
            "change_percent": round(float(100 * (late - 1)), 2), "years": round(float(years.max()), 2)}


def seen_in_sap(dips, curve, sap_dips):
    """Each PDCSAP dip's depth in SAP over the same span, and whether SAP
    shows it (at least half as deep); and the SAP dips no PDCSAP dip
    covers. PDC takes out what it judges the spacecraft's: pointing drift,
    focus changes, thermal changes, and sudden drops in a pixel's
    sensitivity (Kepler Archive Manual, section 2.3.1.2), so a dip in one
    and not the other is the pipeline's doing until shown otherwise."""
    t, sap, quarter = curve["t"], curve["sap"], curve["quarter"]
    for d in dips:
        span = (t >= d["start"]) & (t <= d["end"]) & np.isfinite(sap)
        if not span.any():
            d["sap_depth_percent"], d["seen_in"] = None, "PDCSAP only"
            continue
        level = np.nanmedian(sap[quarter == quarter[span][0]])
        depth = 100 * (level - np.nanmin(sap[span]))
        d["sap_depth_percent"] = round(float(depth), 2)
        d["seen_in"] = "both" if depth >= 0.5 * d["depth_percent"] else "PDCSAP only"
    covered = [(d["start"], d["end"]) for d in dips]
    alone = [dict(s, seen_in="SAP only") for s in sap_dips
             if not any(a <= s["middle"] <= b for a, b in covered)]
    return alone


def calendar(bkjd):
    from astropy.time import Time
    return Time(bkjd + BKJD, format="jd").datetime.strftime("%Y-%m-%d")


def _runs(mask):
    """(first, last) index of each run of True."""
    edges = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1))


def find_dips(t, f, q, quarter):
    """The dips in one light curve, each with its verdict (see the module's
    words), and the curve's scatter."""
    good = np.isfinite(f) & (q == 0)
    tg, fg, quarter_g = t[good], f[good], quarter[good]
    if len(fg) < DIP_RUN:
        return [], None
    level = np.median(fg)
    scatter = 1.4826 * np.median(np.abs(fg - level))
    below = fg < level - max(DIP_SIGMA * scatter, DIP_DEPTH)
    # A run may not jump a gap or a quarter's change.
    breaks = np.flatnonzero((np.diff(tg) > GAP_DAYS) | (np.diff(quarter_g) != 0))
    dips = []
    for first, last in _runs(below):
        inside = [b for b in breaks if first <= b < last]
        pieces = [(first, last)] if not inside else \
            [(a, b) for a, b in zip([first] + [i + 1 for i in inside], inside + [last])]
        for a, b in pieces:
            if b - a + 1 < DIP_RUN:
                continue
            # Widen to where the light comes back near the level.
            back = level - max(scatter, BACK * DIP_DEPTH)
            while a > 0 and fg[a - 1] < back and a - 1 not in breaks:
                a -= 1
            while b < len(fg) - 1 and fg[b + 1] < back and b not in breaks:
                b += 1
            dips.append((a, b))
    dips = sorted(set(dips))
    out = []
    for a, b in dips:
        low = a + int(np.argmin(fg[a:b + 1]))
        start, middle, end = tg[a], tg[low], tg[b]
        fall, rise = middle - start, end - middle
        total = fall + rise
        # Where the good points stop: a quarter's ends and the gaps.
        same_quarter = quarter_g == quarter_g[low]
        ends = [tg[same_quarter].min(), tg[same_quarter].max()]
        ends += [tg[i] for i in breaks] + [tg[i + 1] for i in breaks]
        edge = min(abs(middle - e) for e in ends) < EDGE_DAYS
        near = np.abs(t - middle) * 24 <= FLAG_HOURS
        flags = int(np.bitwise_or.reduce(q[near] & SUSPECT)) if near.any() else 0
        spacecraft = bool(flags) and total * 24 < SHORT_HOURS
        verdict = "edge" if edge else "spacecraft" if spacecraft else "dip"
        out.append({"start": round(float(start), 3), "middle": round(float(middle), 3), "end": round(float(end), 3),
                    "date": calendar(float(middle)),
                    "depth_percent": round(float(100 * (level - fg[low])), 2),
                    "hours": round(float(total * 24), 1),
                    "asymmetry": round(float((rise - fall) / total), 2) if total > 0 else 0.0,
                    "points": int(b - a + 1), "flags": flags, "verdict": verdict})
    _periodic(out)
    in_dips = sum(d["points"] for d in out)
    if out and in_dips > VARIABLE * len(fg):
        for d in out:
            if d["verdict"] == "dip":
                d["verdict"] = "variability"
    return out, float(scatter)


def _period(middles):
    """The interval three or more dips repeat at, or None: the smallest gap,
    or a half or third of it (eclipses lost in gaps), of which every gap
    is a whole multiple."""
    gaps = np.diff(np.sort(middles))
    gaps = gaps[gaps > 0.1]
    if len(gaps) < 2:
        return None
    for parts in (1, 2, 3):
        period = gaps.min() / parts
        multiples = gaps / period
        if (np.abs(multiples - np.round(multiples)) < PERIOD_TOLERANCE * np.maximum(np.round(multiples), 1)).all():
            return float(period)
    return None


def _periodic(dips):
    """Mark the dips that repeat: each group of three or more of like depth
    (an eclipsing binary's primary eclipses, and apart from them its
    shallower secondaries, which an eccentric orbit puts off the half
    period) at whole multiples of one interval. 3 November 2026: KIC
    8129189, the Villanova catalogue's 53.6-day binary (eclipses 21.6% and
    2.1% deep), was first ranked above Tabby's star when all its dips had
    to be alike at once."""
    clean = [d for d in dips if d["verdict"] in ("dip", "edge", "spacecraft")]   # what repeats is the star's
    for seed in sorted(clean, key=lambda d: -d["depth_percent"]):
        if seed["verdict"] == "periodic":
            continue
        group = [d for d in clean if d["verdict"] != "periodic"
                 and abs(d["depth_percent"] - seed["depth_percent"]) <= LIKE_DEPTH * seed["depth_percent"]]
        if len(group) < 3:
            continue
        period = _period(np.array([d["middle"] for d in group]))
        if period:
            for d in group:
                d["verdict"] = "periodic"
                d["period_days"] = round(period, 4)
    # Two dips the same in depth and length, both symmetric, are one eclipse
    # seen twice (the rest of its eclipses just under the floor): KIC
    # 9221398, a 13.79-day binary with 1.19% eclipses, showed two 1.32%
    # dips 827 days apart, 60 of its periods. The gap is the period at most.
    left = [d for d in clean if d["verdict"] != "periodic" and abs(d["asymmetry"]) <= PAIR_SYMMETRIC]
    for i, a in enumerate(left):
        for b in left[i + 1:]:
            if b["verdict"] == "periodic" or a["verdict"] == "periodic":
                continue
            if abs(a["depth_percent"] - b["depth_percent"]) <= PAIR_DEPTH * a["depth_percent"] \
                    and abs(a["hours"] - b["hours"]) <= PAIR_HOURS * max(a["hours"], b["hours"]):
                for d in (a, b):
                    d["verdict"] = "periodic"
                    d["period_days"] = round(abs(b["middle"] - a["middle"]), 4)


def score(dips):
    """How Tabby-like the dips left make a star: deep and lopsided count most."""
    real = [d for d in dips if d["verdict"] == "dip"]
    return round(sum(d["depth_percent"] * (1 + abs(d["asymmetry"])) for d in real), 2)


def analyse(kic, get=requests.get, say=print):
    """One star's answer."""
    curve = read(fetch(kic, get, say))
    dips, scatter = find_dips(curve["t"], curve["f"], curve["q"], curve["quarter"])
    sap_dips, _ = find_dips(curve["t"], curve["sap"], curve["q"], curve["quarter"])
    sap_only = seen_in_sap(dips, curve, sap_dips)
    real = [d for d in dips if d["verdict"] == "dip"]
    padded = f"{kic:09d}"
    return {"star": f"KIC {kic}", "kic": kic, "quarters": int(len(set(curve["quarter"].tolist()))),
            "points": int(np.isfinite(curve["f"]).sum()),
            "scatter_percent": None if scatter is None else round(100 * scatter, 3),
            "dips": dips, "real_dips": len(real), "sap_only": sap_only,
            "trend": {"sap": trend(curve["t"], curve["sap_raw"], curve["quarter"]),
                      "pdcsap": trend(curve["t"], curve["pdc_raw"], curve["quarter"])},
            "deepest_percent": max((d["depth_percent"] for d in real), default=0.0),
            "tabby_like": scatter is not None and scatter <= QUIET
                          and any(d["depth_percent"] >= 100 * DEEP for d in real),
            "score": score(dips),
            "source": MAST.format(group=padded[:4], kic=padded)}


def say_star(answer, say=print):
    say(f"{answer['star']}: {answer['quarters']} quarters, {answer['points']} points, scatter "
        f"{answer['scatter_percent']}%; {answer['real_dips']} dip(s) left of {len(answer['dips'])} found"
        f"{', Tabby-like' if answer['tabby_like'] else ''}")
    for d in answer["dips"]:
        sap = "" if d.get("sap_depth_percent") is None else f", SAP {d['sap_depth_percent']:.2f}%"
        say(f"  {d['date']} (BKJD {d['middle']:.2f})  {d['depth_percent']:5.2f}% deep{sap}, {d['hours']:.1f} h, "
            f"asymmetry {d['asymmetry']:+.2f}  {d['verdict']}, {d.get('seen_in', 'PDCSAP')}"
            f"{' (period ' + str(d['period_days']) + ' d)' if 'period_days' in d else ''}")
    real_sap = [d for d in answer.get("sap_only", []) if d["verdict"] == "dip"]
    if real_sap:
        say(f"  {len(real_sap)} dip(s) in SAP only (PDC took them out: the spacecraft's, until shown otherwise): "
            + ", ".join(f"BKJD {d['middle']:.1f} {d['depth_percent']:.1f}%" for d in real_sap[:6]))
    for name, tr in (answer.get("trend") or {}).items():
        if tr:
            say(f"  long-term ({name.upper()}, quarters joined at their edges): {tr['percent_per_year']:+.2f}% a "
                f"year, {tr['change_percent']:+.2f}% over {tr['years']:.1f} years")


def stars(text):
    """KIC numbers from a file (one a line, # comments) or a comma list."""
    path = Path(text)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else text.split(",")
    out = []
    for line in lines:
        line = line.split("#")[0].strip()
        if line:
            out.append(kic_number(line))
    return out


def search(numbers, get=requests.get, say=print):
    """Each star's answer, the most Tabby-like first; a star that cannot be
    had is listed with why."""
    found, missed = [], []
    for kic in numbers:
        try:
            answer = analyse(kic, get, say=lambda *_: None)
        except (requests.RequestException, OSError, ValueError, KeyError, interface.Refusal) as problem:
            missed.append({"kic": kic, "why": str(getattr(problem, "message", problem))[:200]})
            continue
        answer = {k: v for k, v in answer.items() if k != "dips"} | {
            "dips": [d for d in answer["dips"] if d["verdict"] == "dip"]}
        found.append(answer)
    found.sort(key=lambda a: (not a["tabby_like"], -a["score"]))
    say(f"{len(found)} stars read, {len(missed)} not had; {sum(a['tabby_like'] for a in found)} Tabby-like")
    for a in found[:20]:
        say(f"  {a['star']:<14} score {a['score']:6.2f}  {a['real_dips']} dip(s), deepest {a['deepest_percent']:.2f}%"
            f"{'  Tabby-like' if a['tabby_like'] else ''}")
    for m in missed:
        say(f"  KIC {m['kic']}: {m['why']}")
    return {"stars": found, "missed": missed, "kind": "measured"}


def target_list(get=requests.get):
    """Every star Kepler watched, brightest first (NASA's Exoplanet Archive,
    its Kepler stellar table), as KIC numbers; kept once fetched."""
    import csv
    import io
    path = config.DATA / "cache" / "kepler" / "targets.csv"
    if not path.exists():
        reply = get(TARGETS, params={"query": TARGET_QUERY, "format": "csv"}, timeout=300)
        reply.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(reply.text, encoding="utf-8")
    seen, out = set(), []
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        kic = int(row["kepid"])
        if kic not in seen:                  # a star in several deliveries: its first (brightest) row
            seen.add(kic)
            out.append(kic)
    return out


def screened_file():
    return config.DATA / "cache" / "kepler" / "screened.json"


def screened():
    import json
    path = screened_file()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def ranking(record, most=20):
    """Every star screened so far, Tabby-like first, then by score."""
    rows = [dict(v, kic=int(k)) for k, v in record.items() if "score" in v]
    return sorted(rows, key=lambda r: (not r["tabby_like"], -r["score"]))[:most]


def screen(batch, get=requests.get, say=print, keep=False, analyse_star=None):
    """The next `batch` Kepler stars not screened yet, brightest first, each
    screened and its summary kept (cache/kepler/screened.json) as it is
    done, so a run stopped part way, or the next run, goes on from there.
    A star's light curves are deleted once screened unless it is
    Tabby-like or `keep` (200,000 stars at 7 MB each would not fit)."""
    import shutil
    import records
    analyse_star = analyse_star or analyse
    record = screened()
    todo = [k for k in target_list(get) if str(k) not in record][:batch]
    say(f"{len(record)} screened before; screening {len(todo)} more, brightest first")
    for n, kic in enumerate(todo, 1):
        try:
            a = analyse_star(kic, get, say=lambda *_: None)
            record[str(kic)] = {"score": a["score"], "tabby_like": a["tabby_like"], "real_dips": a["real_dips"],
                                "deepest_percent": a["deepest_percent"], "scatter_percent": a["scatter_percent"],
                                "sap_only": sum(d["verdict"] == "dip" for d in a.get("sap_only", []))}
            if a["tabby_like"]:
                say(f"  KIC {kic}: Tabby-like, {a['real_dips']} dip(s), deepest {a['deepest_percent']:.1f}%")
            elif not keep:
                shutil.rmtree(store(kic), ignore_errors=True)
        except (requests.RequestException, OSError, ValueError, KeyError, interface.Refusal) as problem:
            record[str(kic)] = {"missed": str(getattr(problem, "message", problem))[:200]}
        if n % 10 == 0 or n == len(todo):
            records.write(screened_file(), record, indent=None)
    top = ranking(record)
    say(f"{len(record)} screened in all; {sum(1 for v in record.values() if v.get('tabby_like'))} Tabby-like")
    for r in top[:10]:
        say(f"  KIC {r['kic']:<10} score {r['score']:6.2f}  {r['real_dips']} dip(s), deepest {r['deepest_percent']:.2f}%,"
            f" scatter {r['scatter_percent']}%{'  Tabby-like' if r['tabby_like'] else ''}")
    return {"screened": len(record), "this_run": len(todo), "order": "brightest first (Kepler magnitude)",
            "top": top, "kind": "measured"}


def run(args, say=print):
    if args.action == "screen":
        return screen(args.batch, say=say, keep=args.keep)
    if args.action == "dips":
        answer = dict(analyse(kic_number(args.star), say=say), kind="measured")
        say_star(answer, say)
        return answer
    if not args.star:
        raise interface.Refusal("INVALID_REQUEST", "search needs a file of KIC numbers or a comma list.")
    return search(stars(" ".join(args.star)), say=say)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("dips", "search", "screen"))
    ap.add_argument("--batch", type=int, default=100, help="screen: stars this run (default 100)")
    ap.add_argument("--keep", action="store_true", help="screen: keep every star's light curves")
    ap.add_argument("star", nargs="*", help="dips: the star (KIC 8462852, Tabby); search: a file or a comma list")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("archive", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
