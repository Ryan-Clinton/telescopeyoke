#!/usr/bin/env python3
"""Dips in a star's Kepler light curve, from the public archive: the search
for stars that behave like Tabby's star, done on four years of a space
telescope's measurements instead of our own nights.

    ./archive.py dips KIC 8462852        Tabby's star: its dips, each with depth, length and shape
    ./archive.py dips Tabby --json
    ./archive.py search stars.txt        each KIC number in the file (one a line), most Tabby-like first
    ./archive.py search 8462852,7106205

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
DEEP deep; stars are ranked by the dips left, deep and lopsided first.
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

DIP_RUN = 3          # points in a row (variables.DIP_RUN), 30 minutes apart
DIP_SIGMA = 3.0      # times the usual scatter below the level (variables.DIP_SIGMA)
DIP_DEPTH = 0.01     # and at least this far below it: 1%, about variables.DIP_DEPTH's 0.02 mag halved for Kepler's precision
EDGE_DAYS = 0.5      # this close to a quarter's end or a gap is an edge
GAP_DAYS = 0.5       # a break this long in the good points is a gap
FLAG_HOURS = 6.0     # a quality flag this close to a short dip's faintest point puts it on the spacecraft
SHORT_HOURS = 24.0   # only a dip shorter than this can be a spacecraft event: a momentum dump or a
                     # tweak upsets a few hours; Kepler had a dump every three days, so a dip of days
                     # always has one near it
BACK = 0.25          # a dip is widened to where the light is back within this share of DIP_DEPTH
SUSPECT = 1 | 2 | 4 | 8 | 32 | 128    # attitude tweak, safe mode, coarse point, Earth point, momentum dump, manual exclude
PERIOD_TOLERANCE = 0.02   # an interval within this share of a whole multiple
LIKE_DEPTH = 0.3          # depths within this share of their mean are alike
VARIABLE = 0.05           # dips over this share of the good points: the star's own variability
DEEP = 0.05               # a dip this deep makes a star Tabby-like


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
    for url in urls:
        reply = get(url, timeout=TIMEOUT)
        reply.raise_for_status()
        part = folder / (url.rsplit("/", 1)[1] + ".part")
        part.write_bytes(reply.content)
        part.rename(folder / url.rsplit("/", 1)[1])
    return sorted(folder.glob("*_llc.fits"))


def read(paths):
    """One light curve from the quarters' files: time (BKJD), flux divided by
    each quarter's median (NaN where not usable), quality flags, quarter."""
    from astropy.io import fits
    t, f, q, quarter = [], [], [], []
    for path in paths:
        with fits.open(path, memmap=False) as hdul:
            data = hdul[1].data
            number = hdul[0].header.get("QUARTER", -1)
            time = np.array(data["TIME"], float)
            flux = np.array(data["PDCSAP_FLUX"], float)
            flags = np.array(data["SAP_QUALITY"], int)
        good = np.isfinite(time) & np.isfinite(flux) & (flags == 0)
        if not good.any():
            continue
        flux = np.where(good, flux / np.median(flux[good]), np.nan)
        keep = np.isfinite(time)
        t.append(time[keep])
        f.append(flux[keep])
        q.append(flags[keep])
        quarter.append(np.full(keep.sum(), number))
    if not t:
        return {"t": np.array([]), "f": np.array([]), "q": np.array([], int), "quarter": np.array([], int)}
    return {"t": np.concatenate(t), "f": np.concatenate(f), "q": np.concatenate(q),
            "quarter": np.concatenate(quarter)}


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


def _periodic(dips):
    """Mark three or more like dips at whole multiples of one interval."""
    clean = [d for d in dips if d["verdict"] in ("dip", "edge")]
    if len(clean) < 3:
        return
    middles = np.array(sorted(d["middle"] for d in clean))
    depths = np.array([d["depth_percent"] for d in clean])
    gaps = np.diff(middles)
    period = gaps[gaps > 0.1].min() if (gaps > 0.1).any() else None
    if not period:
        return
    multiples = gaps / period
    whole = np.abs(multiples - np.round(multiples)) < PERIOD_TOLERANCE * np.maximum(np.round(multiples), 1)
    alike = depths.std() <= LIKE_DEPTH * depths.mean()
    if whole.all() and alike:
        for d in clean:
            d["verdict"] = "periodic"
            d["period_days"] = round(float(period), 4)


def score(dips):
    """How Tabby-like the dips left make a star: deep and lopsided count most."""
    real = [d for d in dips if d["verdict"] == "dip"]
    return round(sum(d["depth_percent"] * (1 + abs(d["asymmetry"])) for d in real), 2)


def analyse(kic, get=requests.get, say=print):
    """One star's answer."""
    curve = read(fetch(kic, get, say))
    dips, scatter = find_dips(curve["t"], curve["f"], curve["q"], curve["quarter"])
    real = [d for d in dips if d["verdict"] == "dip"]
    padded = f"{kic:09d}"
    return {"star": f"KIC {kic}", "kic": kic, "quarters": int(len(set(curve["quarter"].tolist()))),
            "points": int(np.isfinite(curve["f"]).sum()),
            "scatter_percent": None if scatter is None else round(100 * scatter, 3),
            "dips": dips, "real_dips": len(real),
            "deepest_percent": max((d["depth_percent"] for d in real), default=0.0),
            "tabby_like": any(d["depth_percent"] >= 100 * DEEP for d in real), "score": score(dips),
            "source": MAST.format(group=padded[:4], kic=padded)}


def say_star(answer, say=print):
    say(f"{answer['star']}: {answer['quarters']} quarters, {answer['points']} points, scatter "
        f"{answer['scatter_percent']}%; {answer['real_dips']} dip(s) left of {len(answer['dips'])} found"
        f"{', Tabby-like' if answer['tabby_like'] else ''}")
    for d in answer["dips"]:
        say(f"  {d['date']} (BKJD {d['middle']:.2f})  {d['depth_percent']:5.2f}% deep, {d['hours']:.1f} h, "
            f"asymmetry {d['asymmetry']:+.2f}  {d['verdict']}"
            f"{' (period ' + str(d['period_days']) + ' d)' if 'period_days' in d else ''}")


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
    found.sort(key=lambda a: -a["score"])
    say(f"{len(found)} stars read, {len(missed)} not had; {sum(a['tabby_like'] for a in found)} Tabby-like")
    for a in found[:20]:
        say(f"  {a['star']:<14} score {a['score']:6.2f}  {a['real_dips']} dip(s), deepest {a['deepest_percent']:.2f}%"
            f"{'  Tabby-like' if a['tabby_like'] else ''}")
    for m in missed:
        say(f"  KIC {m['kic']}: {m['why']}")
    return {"stars": found, "missed": missed, "kind": "measured"}


def run(args, say=print):
    if args.action == "dips":
        answer = dict(analyse(kic_number(args.star), say=say), kind="measured")
        say_star(answer, say)
        return answer
    if not args.star:
        raise interface.Refusal("INVALID_REQUEST", "search needs a file of KIC numbers or a comma list.")
    return search(stars(" ".join(args.star)), say=say)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("dips", "search"))
    ap.add_argument("star", nargs="*", help="dips: the star (KIC 8462852, Tabby); search: a file or a comma list")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("archive", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
