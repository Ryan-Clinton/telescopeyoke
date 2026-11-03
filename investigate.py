#!/usr/bin/env python3
"""Look into a lead from the searches, by one fixed procedure, and say what
it is: explained, an artefact, or unexplained, and how strongly.

    ./investigate.py                  the top lead nobody has looked into yet
    ./investigate.py KIC 7988797      a Kepler star
    ./investigate.py TIC 185336364    a TESS star
    ./investigate.py --json

The leads are what the searches flag and nobody has looked into: the
Kepler and TESS screens' stars with a dip left after archive.py's checks
(Tabby-like first, then by score), and seti.py sweep's candidates. Each
one goes through the same steps, in order, each answer kept with where it
came from and when it was asked:

  a. Already explained? SIMBAD's type for the star and how many papers
     cite it; VSX's variable type; Villanova's Kepler eclipsing-binary
     catalogue; Gaia DR3's variability class and RUWE (above 1.4, the
     star's motion is pulled about by a companion it cannot resolve).
  b. Seen elsewhere? The same star in the other mission (TESS for a
     Kepler star) and in ZTF's light curve (2018 on): is it still doing it?
  c. Could it be something else? The dip in both of Kepler's fluxes;
     other stars' light in the aperture (Kepler's CROWDSAP) and a Gaia
     neighbour within 8" bright enough to make the dip itself if it went
     out; periodic dips (archive.py's own checks).
  d. The verdict: "explained" (a catalogue or class accounts for it),
     "artefact" (a check fails), "unexplained, weak" or "unexplained,
     strong", with the reasons; and whether it is known to science
     already (cited in KNOWN_PAPERS papers or more in SIMBAD).
  e. This telescope: whether the star is within variables.py's range and
     its dips deeper than twice a night's precision here, and how many
     dark hours it is up on the first night of each of the coming months.

The report is docs/research/LEAD.md, every answer with its link and the
date asked, and the record cache/research/LEAD.json; the next run takes
the next lead. A SETI candidate is checked against the bands satellites
use and for a drift of zero (a transmitter fixed to the ground). An
"unexplained" verdict is the end of these checks, not a discovery: it is
for a person to read the report, and for catalogue-researcher to look
further, before anything is called new. Nothing here moves the mount or
uses the camera.
"""
import argparse
import csv
import io
import math
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import requests

import config
import interface
import records

ROOT = Path(__file__).parent
REPORTS = ROOT / "docs" / "research"
TIMEOUT = 90
HEADERS = {"User-Agent": "telescopeyoke/0.1 (personal research: looking into a light curve's dips)"}

SIMBAD = ("https://simbad.cds.unistra.fr/simbad/sim-tap/sync", "https://simbad.harvard.edu/simbad/sim-tap/sync")
VIZIER = ("https://vizier.cds.unistra.fr/viz-bin/asu-tsv", "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv")
GAIA = "https://gea.esac.esa.int/tap-server/tap/sync"
ZTF = "https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves"
VILLANOVA = "https://keplerebs.villanova.edu/overview/?k={kic}"

MATCH_ARCSEC = 3.0       # the star itself, in a catalogue
NEIGHBOUR_ARCSEC = 8.0   # a Gaia star this close shares Kepler's 4" pixels and aperture
RUWE_COMPANION = 1.4     # Gaia's RUWE above this: an unresolved companion pulls the star about
CROWDED = 0.95           # Kepler's CROWDSAP below this: over 5% of the aperture's light is other stars'
KNOWN_PAPERS = 20        # cited this often in SIMBAD: known to science already
# A red giant: Gaia colour and absolute magnitude (from a parallax at least
# GIANT_PARALLAX times its error). Kepler's red giants vary irregularly by a
# few percent over days to weeks as they pulsate (Bányai et al. 2013,
# arXiv 1309.1012), so dips under GIANT_DIP on one are explained by that.
GIANT_COLOUR = 1.0       # BP-RP at least this red
GIANT_ABS = 2.5          # absolute G at most this (brighter): above the main sequence at that colour
GIANT_PARALLAX = 5.0     # parallax over its error at least this, for the absolute magnitude to be trusted
GIANT_DIP = 10.0         # percent: dips shallower than this are a giant's own
STRONG_DEPTH = 5.0       # percent: a dip this deep...
STRONG_DIPS = 2          # ...this many times, in both fluxes, on a quiet star, unexplained: "strong"
PRECISION_PERCENT = 2.0  # a night's level here, now (docs/discovery.md: two nights of Tabby 0.22 mag apart)
MONTHS = 6               # months ahead looked at for when the star is up
GAIA_CLASSES = {         # Gaia DR3's variability classes that account for dips
    "ECL": "an eclipsing binary", "RS": "an RS CVn star (spots on an active binary)",
    "SOLAR_LIKE": "a spotted, rotating star", "YSO": "a young star, dimmed by its own disc",
    "RR": "an RR Lyrae pulsator", "CEP": "a Cepheid", "LPV": "a long-period variable",
    "DSCT|GDOR|SXPHE": "a pulsating star", "BE|GCAS|SDOR|WR": "an eruptive hot star",
    "ELL": "an ellipsoidal binary", "S": "short-timescale variable"}
SIMBAD_CLASSES = {       # SIMBAD's types that account for dips (its 2023 condensed codes and the older ones)
    "EB*": "an eclipsing binary", "El*": "an ellipsoidal binary", "RS*": "an RS CVn star",
    "BY*": "a BY Draconis star (spots)", "RotV*": "a rotating variable", "YSO": "a young star",
    "Y*O": "a young star", "TT*": "a T Tauri star", "Or*": "an Orion variable (a young star)",
    "Ae*": "a young Herbig Ae/Be star", "RCrB*": "an R Coronae Borealis star (it makes dust)",
    "RR*": "an RR Lyrae pulsator", "Ce*": "a Cepheid", "LP*": "a long-period variable", "Mi*": "a Mira",
    "dS*": "a delta Scuti pulsator", "gD*": "a gamma Doradus pulsator", "CV*": "a cataclysmic variable",
    "Pl": "a star with a known planet"}
VSX_GENERIC = {"", "VAR", "MISC", "*", "UNKNOWN", "NSIN", "S", "VAR:"}
# Bands satellites and the ground transmit in (ITU Radio Regulations,
# Article 5), MHz: a SETI hit inside one is most likely one of them.
SATELLITE_BANDS = [
    (1164.0, 1189.0, "GPS L5 / Galileo E5a"), (1215.0, 1240.0, "GPS L2 / Galileo E6"),
    (1525.0, 1559.0, "Inmarsat and other mobile satellites"), (1559.0, 1610.0, "GPS L1, GLONASS, Galileo, BeiDou"),
    (1610.0, 1626.5, "Iridium and Globalstar"), (1670.0, 1710.0, "weather satellites"),
    (2200.0, 2290.0, "space operation and research downlinks"), (2320.0, 2345.0, "satellite radio (SDARS)"),
    (2400.0, 2483.5, "Wi-Fi and the ISM band"), (2483.5, 2500.0, "Globalstar downlinks")]


def _today():
    return date.today().isoformat()


def _get(get, url, **kw):
    reply = get(url, timeout=TIMEOUT, headers=HEADERS, **kw)
    reply.raise_for_status()
    return reply


def _asked(source, url, answer, error=None):
    """One step's answer, with where and when it was asked."""
    return {"source": source, "link": url, "asked": _today(), "answer": answer, "error": error}


# --- a. already explained? ----------------------------------------------------------

def simbad(ra, dec, get=requests.get):
    """SIMBAD's nearest object within MATCH_ARCSEC: its name, type and how
    many papers cite it; each mirror tried in turn."""
    query = (f"SELECT TOP 1 main_id, otype, nbref, DISTANCE(POINT('ICRS', ra, dec), POINT('ICRS', {ra}, {dec})) AS d "
             f"FROM basic WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {MATCH_ARCSEC / 3600})) = 1 "
             "ORDER BY d")
    last = None
    for url in SIMBAD:
        try:
            body = _get(get, url, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query}).json()
        except (requests.RequestException, ValueError) as problem:
            last = problem
            continue
        rows = body.get("data") or []
        answer = None if not rows else {"name": rows[0][0], "type": rows[0][1], "papers": rows[0][2]}
        return _asked("SIMBAD", url.replace("/sim-tap/sync", f"/sim-coo?Coord={ra}+{dec}&Radius=3&Radius.unit=arcsec"), answer)
    return _asked("SIMBAD", SIMBAD[0], None, error=f"not answered ({type(last).__name__})")


def vsx(ra, dec, get=requests.get):
    """VSX's variable stars within MATCH_ARCSEC (through VizieR), the nearest's name and type."""
    params = {"-source": "B/vsx/vsx", "-c": f"{ra:.5f} {dec:+.5f}", "-c.rs": f"{MATCH_ARCSEC:g}",
              "-out": "Name,Type,Period", "-sort": "_r"}
    last = None
    for url in VIZIER:
        try:
            text = _get(get, url, params=params).text
        except requests.RequestException as problem:
            last = problem
            continue
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        dashes = next((k for k, ln in enumerate(lines) if ln.startswith("-")), None)   # the rows come after it
        rows = [ln.split("\t") for ln in lines[dashes + 1:]] if dashes is not None else []
        answer = None if not rows else {"name": rows[0][0].strip(), "type": rows[0][1].strip(),
                                        "period": rows[0][2].strip() if len(rows[0]) > 2 else ""}
        return _asked("VSX (via VizieR)", f"https://www.aavso.org/vsx/index.php?view=results.get&coords={ra}+{dec}"
                      f"&format=d&size=3&unit=3", answer)
    return _asked("VSX (via VizieR)", VIZIER[0], None, error=f"not answered ({type(last).__name__})")


_EB_ROW = re.compile(r"<td>(True|False)(?:</a>)?</td>\s*<td>([\d.]+)</td>\s*<td>([\d.]+)</td>\s*<td>([\d.]+)</td>"
                     r"\s*<td>([\d.]+)</td>\s*<td>([\d.]+)</td>\s*<td>([\d.]+)</td>")


def villanova(kic, get=requests.get):
    """The star in Villanova's Kepler eclipsing-binary catalogue: its period
    and primary eclipse depth, or None when it is not in it."""
    url = VILLANOVA.format(kic=kic)
    try:
        text = _get(get, url).text
    except requests.RequestException as problem:
        return _asked("Villanova Kepler EB catalogue", url, None, error=f"not answered ({type(problem).__name__})")
    row = _EB_ROW.search(text)
    if "not currently in the EB Catalog" in text or not row:
        return _asked("Villanova Kepler EB catalogue", url, None)
    return _asked("Villanova Kepler EB catalogue", url, {"period_days": float(row.group(2)),
                                                         "primary_depth": float(row.group(6))})


def gaia(ra, dec, get=requests.get):
    """Gaia DR3 round the place: the star (nearest), its RUWE and
    variability class, and every star within NEIGHBOUR_ARCSEC."""
    query = (f"SELECT source_id, ra, dec, phot_g_mean_mag, ruwe, bp_rp, parallax, parallax_over_error, "
             f"DISTANCE(POINT(ra, dec), POINT({ra}, {dec})) * 3600 AS sep "
             f"FROM gaiadr3.gaia_source WHERE 1 = CONTAINS(POINT(ra, dec), CIRCLE({ra}, {dec}, {NEIGHBOUR_ARCSEC / 3600})) "
             "ORDER BY sep")
    try:
        rows = list(csv.DictReader(io.StringIO(_get(get, GAIA, params={"REQUEST": "doQuery", "LANG": "ADQL",
                                                                         "FORMAT": "csv", "QUERY": query}).text)))
    except requests.RequestException as problem:
        return _asked("Gaia DR3", GAIA, None, error=f"not answered ({type(problem).__name__})")
    num = lambda v: float(v) if v not in ("", None) else None       # noqa: E731
    stars = [{"source_id": r["source_id"], "g": num(r["phot_g_mean_mag"]), "ruwe": num(r["ruwe"]),
              "bp_rp": num(r.get("bp_rp")), "parallax_mas": num(r.get("parallax")),
              "parallax_over_error": num(r.get("parallax_over_error")),
              "separation_arcsec": round(num(r["sep"]), 2)} for r in rows]
    for st in stars:
        # Its absolute G from the parallax, where the parallax is good enough
        plx, good = st["parallax_mas"], st["parallax_over_error"]
        st["abs_g"] = (round(st["g"] + 5 + 5 * math.log10(plx / 1000), 2)
                       if st["g"] is not None and plx and plx > 0 and good and good >= GIANT_PARALLAX else None)
    star = next((s for s in stars if s["separation_arcsec"] <= MATCH_ARCSEC and s["g"] is not None), None)
    klass = None
    if star:
        try:
            got = list(csv.DictReader(io.StringIO(_get(get, GAIA, params={
                "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
                "QUERY": "SELECT best_class_name, best_class_score FROM gaiadr3.vari_classifier_result "
                         f"WHERE source_id = {star['source_id']}"}).text)))
            klass = {"name": got[0]["best_class_name"], "score": num(got[0]["best_class_score"])} if got else None
        except requests.RequestException:
            klass = None
    link = f"https://gea.esac.esa.int/archive/ (DR3 cone {ra:.5f} {dec:+.5f}, {NEIGHBOUR_ARCSEC:g}\")"
    return _asked("Gaia DR3", link, {"star": star, "class": klass,
                                     "neighbours": [s for s in stars if s is not star]})


# --- b. seen elsewhere? -----------------------------------------------------------

def ztf(ra, dec, get=requests.get):
    """ZTF's light curve at the place (IRSA): points, years, and in each
    filter the spread and the faintest it went below its usual level."""
    params = {"POS": f"CIRCLE {ra:.5f} {dec:+.5f} {MATCH_ARCSEC / 3600:.5f}", "FORMAT": "csv"}
    try:
        text = _get(get, ZTF, params=params).text
    except requests.RequestException as problem:
        return _asked("ZTF (IRSA)", ZTF, None, error=f"not answered ({type(problem).__name__})")
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r.get("catflags") in ("0", 0)]
    link = f"{ZTF}?POS=CIRCLE%20{ra:.5f}%20{dec:+.5f}%200.00083&FORMAT=html"
    if not rows:
        return _asked("ZTF (IRSA)", link, {"points": 0, "note": "no clean ZTF points (too bright, under 12.5, or not covered)"})
    out = {"points": len(rows)}
    mjd = [float(r["mjd"]) for r in rows]
    out["from"], out["to"] = _day(min(mjd)), _day(max(mjd))
    for band in sorted({r["filtercode"] for r in rows}):
        mags = np.array([float(r["mag"]) for r in rows if r["filtercode"] == band])
        middle = float(np.median(mags))
        spread = float(1.4826 * np.median(np.abs(mags - middle)))
        out[band] = {"points": int(len(mags)), "median_mag": round(middle, 3), "scatter_mag": round(spread, 3),
                     "faintest_below_mag": round(float(mags.max() - middle), 3)}
    return _asked("ZTF (IRSA)", link, out)


def _day(mjd):
    return datetime.fromtimestamp((mjd - 40587.0) * 86400, timezone.utc).strftime("%Y-%m-%d")


def other_mission(lead, say=print):
    """The same star in the other mission: TESS for a Kepler star (TIC by the
    TIC's own cross-match), through archive.py."""
    import archive
    if lead["kind"] != "kepler":
        return _asked("Kepler", "https://archive.stsci.edu/kepler/", None,
                      error="a TESS star is looked for in Kepler's field by its KIC, which the TIC does not give here")
    try:
        tic = archive.tic_number(f"KIC {lead['kic']}")
        a = archive.analyse_tess(tic, say=lambda *_: None)
    except interface.Refusal as refusal:     # MAST answered: it has no light curve of the star
        return _asked("TESS (MAST)", "https://mast.stsci.edu/", {"tic": None, "dips": None,
                                                                 "none": refusal.as_error()["message"]})
    except Exception as problem:    # astroquery raises its own errors; any is "not had"
        return _asked("TESS (MAST)", "https://mast.stsci.edu/", None,
                      error=f"not had ({type(problem).__name__}: {str(problem)[:120]})")
    real = [d for d in a["dips"] if d["verdict"] == "dip"]
    return _asked("TESS (MAST)", a["source"], {"tic": tic, "sectors": a["quarters"], "scatter_percent": a["scatter_percent"],
                                                "dips": len(real), "deepest_percent": a["deepest_percent"]})


# --- the star itself ------------------------------------------------------------------

def kepler_star(kic, say=print):
    """archive.py's answer for a Kepler star, with its place, magnitude and
    CROWDSAP (the share of the aperture's light that is the star's) from
    its files' headers."""
    import archive
    from astropy.io import fits
    answer = archive.analyse(kic, say=lambda *_: None)
    paths = sorted(archive.store(kic).glob("*_llc.fits"))
    head, crowd = {}, []
    for path in paths:
        with fits.open(path, memmap=False) as hdul:
            head = head or dict(hdul[0].header)
            if hdul[1].header.get("CROWDSAP") is not None:
                crowd.append(float(hdul[1].header["CROWDSAP"]))
    return dict(answer, ra=head.get("RA_OBJ"), dec=head.get("DEC_OBJ"), mag=head.get("KEPMAG"), mag_band="Kepler",
                crowdsap=round(float(np.median(crowd)), 4) if crowd else None)


def tess_star(tic, say=print):
    import archive
    from astropy.io import fits
    answer = archive.analyse_tess(tic, say=lambda *_: None)
    paths = sorted(archive.tess_store(tic).glob("*_lc.fits"))
    head, crowd = {}, []
    for path in paths:
        with fits.open(path, memmap=False) as hdul:
            head = head or dict(hdul[0].header)
            if hdul[1].header.get("CROWDSAP") is not None:
                crowd.append(float(hdul[1].header["CROWDSAP"]))
    return dict(answer, ra=head.get("RA_OBJ"), dec=head.get("DEC_OBJ"), mag=head.get("TESSMAG"), mag_band="TESS",
                crowdsap=round(float(np.median(crowd)), 4) if crowd else None)


# --- d. the verdict ----------------------------------------------------------------

def neighbour_could(neighbours, star_g, depth_percent):
    """Gaia neighbours bright enough to make a dip this deep by going out
    altogether: a neighbour with flux r times the star's dims the sum by
    r / (1 + r) at most."""
    out = []
    for n in neighbours:
        if n["g"] is None or star_g is None:
            continue
        r = 10 ** (-0.4 * (n["g"] - star_g))
        if r / (1 + r) * 100 >= depth_percent:
            out.append(dict(n, could_make_percent=round(100 * r / (1 + r), 1)))
    return out


def giant(star):
    """Whether Gaia's colour and absolute magnitude put the star among the red giants."""
    return bool(star and star.get("bp_rp") is not None and star.get("abs_g") is not None
                and star["bp_rp"] >= GIANT_COLOUR and star["abs_g"] <= GIANT_ABS)


def judge(star, checks):
    """The verdict on a star from its dips and the checks' answers."""
    explained, artefact, notes = [], [], []
    real = [d for d in star["dips"] if d["verdict"] == "dip"]
    deepest = max((d["depth_percent"] for d in real), default=0.0)
    s, v, eb, g = (checks[k]["answer"] for k in ("simbad", "vsx", "villanova", "gaia"))
    if eb:
        explained.append(f"Villanova's Kepler EB catalogue: an eclipsing binary, period {eb['period_days']:g} days")
    if v and v["type"].upper().rstrip(":") not in VSX_GENERIC:
        explained.append(f"VSX: {v['name']}, type {v['type']}" + (f", period {v['period']} d" if v["period"] else ""))
    if s and s["type"] in SIMBAD_CLASSES:
        explained.append(f"SIMBAD: {s['name']} is {SIMBAD_CLASSES[s['type']]} ({s['type']})")
    if g and g["class"] and g["class"]["name"] in GAIA_CLASSES and (g["class"]["score"] or 0) >= 0.5:
        explained.append(f"Gaia DR3 classes it {GAIA_CLASSES[g['class']['name']]} ({g['class']['name']}, "
                         f"score {g['class']['score']:.2f})")
    if not real:
        artefact.append("no dip survives archive.py's checks (edges, spacecraft events, periodic, the star's own scatter)")
    one_flux = [d for d in real if d.get("seen_in") not in (None, "both")]
    if real and len(one_flux) == len(real):
        artefact.append("every dip is in the cleaned flux only (PDCSAP), not the raw (SAP): the pipeline's, "
                        "until shown otherwise (Kepler Archive Manual 2.3.1.2)")
    crowd = star.get("crowdsap")
    if crowd is not None and crowd < CROWDED and (1 - crowd) * 100 >= deepest:
        artefact.append(f"{100 * (1 - crowd):.0f}% of the aperture's light is other stars' (CROWDSAP {crowd:g}): "
                        f"enough to make the {deepest:.1f}% dip")
    star_g = g["star"]["g"] if g and g["star"] else None
    could = neighbour_could(g["neighbours"], star_g, deepest) if g else []
    if could:
        artefact.append("a Gaia neighbour within 8\" could make the dip itself: " + ", ".join(
            f"G {n['g']:.1f} at {n['separation_arcsec']:g}\" (up to {n['could_make_percent']:g}%)" for n in could))
    if g and g["star"] and (g["star"]["ruwe"] or 0) > RUWE_COMPANION:
        notes.append(f"Gaia RUWE {g['star']['ruwe']:.2f}: an unresolved companion is likely")
    known = bool(s and (s["papers"] or 0) >= KNOWN_PAPERS)
    if known:
        notes.append(f"known to science: SIMBAD lists {s['papers']} papers on {s['name']}")
    unasked = [checks[k]["source"] for k in ("simbad", "vsx", "villanova", "gaia") if checks[k]["error"]]
    gstar = (g or {}).get("star") or {}
    if real and giant(gstar) and deepest < GIANT_DIP:
        explained.append(f"a red giant (Gaia DR3 BP-RP {gstar['bp_rp']:.2f}, absolute G {gstar['abs_g']:+.1f}): "
                         f"giants this red vary by a few percent over days to weeks as they pulsate, which dips "
                         f"under {GIANT_DIP:g}% fit (Bányai et al. 2013, https://arxiv.org/abs/1309.1012)")
    if explained:
        verdict = "explained"
    elif artefact:
        verdict = "artefact"
    else:
        both = len(real) - len(one_flux)
        strong = (len([d for d in real if d["depth_percent"] >= STRONG_DEPTH]) >= STRONG_DIPS and both >= STRONG_DIPS
                  and star.get("tabby_like") and not unasked)
        verdict = "unexplained, strong" if strong else "unexplained, weak"
        if not strong:
            why = []
            if len([d for d in real if d["depth_percent"] >= STRONG_DEPTH]) < STRONG_DIPS:
                why.append(f"fewer than {STRONG_DIPS} dips of {STRONG_DEPTH:g}% or more")
            if not star.get("tabby_like"):
                why.append("its light is not steady between dips")
            if unasked:
                why.append("not every catalogue answered (" + ", ".join(unasked) + ")")
            notes.append("weak because " + "; ".join(why))
    if unasked:
        notes.append("not answered: " + ", ".join(unasked) + " (asked again next run)")
    return {"verdict": verdict, "explained_by": explained, "artefact_because": artefact, "notes": notes,
            "known_to_science": known, "deepest_percent": deepest, "dips": len(real)}


# --- e. this telescope ----------------------------------------------------------------

def follow_up(star, deepest, cfg=None, months=MONTHS, today=None):
    """Whether this telescope could watch the star, and when it is up."""
    import sky
    import variables
    cfg = cfg or (config.load() if config.FILE.exists() else config.example())
    mag = star.get("mag")
    in_range = mag is not None and variables.BRIGHTEST <= mag <= variables.FAINTEST
    seen = deepest >= 2 * PRECISION_PERCENT
    today = today or date.today()
    up = []
    if star.get("ra") is not None:
        for k in range(months):
            month = (today.month - 1 + k) % 12 + 1
            year = today.year + (today.month - 1 + k) // 12
            # Tonight for this month, the 15th for the rest: a night already
            # gone (the 1st, once past) has no hours left to be up in.
            night = sky.Night(cfg, today if k == 0 else date(year, month, 15))
            n = len(night.unix)
            alt, az = night.altaz_fixed([star["ra"]], [star["dec"]])
            r = night.assess({"id": star["star"], "kind": "star"}, np.full(n, star["ra"]), np.full(n, star["dec"]),
                             alt[0], az[0])
            up.append({"month": f"{year}-{month:02d}", "dark_hours_up": r["hours"] if r else 0.0,
                       "best": r["best"].strftime("%H:%M") if r else None})
    can = in_range and seen and any(u["dark_hours_up"] >= 1 for u in up)
    reasons = [f"magnitude {mag} ({star.get('mag_band')}) {'within' if in_range else 'outside'} this camera's range "
               f"({variables.BRIGHTEST:g} to {variables.FAINTEST:g})" if mag is not None else "magnitude not known",
               f"deepest dip {deepest:.1f}% {'over' if seen else 'under'} twice a night's precision here "
               f"(about {PRECISION_PERCENT:g}%)"]
    return {"can_watch": can, "reasons": reasons, "up": up}


# --- leads --------------------------------------------------------------------------

def lead_id(lead):
    if lead["kind"] == "kepler":
        return f"KIC-{lead['kic']}"
    if lead["kind"] == "tess":
        return f"TIC-{lead['tic']}"
    return f"SETI-{lead['target']}-{lead['frequency_mhz']:.6f}"


def records_dir():
    return config.DATA / "cache" / "research"


def done():
    """Every lead looked into, by its id: its kept record."""
    out = {}
    for path in sorted(records_dir().glob("*.json")):
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


def leads():
    """Every lead the searches have flagged, best first: Kepler's and TESS's
    stars with a dip left (Tabby-like first, then by score), then SETI
    candidates (strongest first)."""
    out = []
    for kind, path, key in (("kepler", config.DATA / "cache" / "kepler" / "screened.json", "kic"),
                            ("tess", config.DATA / "cache" / "tess" / "screened.json", "tic")):
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        rows = [dict(v, **{key: int(k), "kind": kind}) for k, v in record.items()
                if isinstance(v, dict) and v.get("real_dips")]
        out += sorted(rows, key=lambda r: (not r.get("tabby_like"), -(r.get("score") or 0)))
    seti = []
    for path in sorted((config.DATA / "cache" / "seti").glob("*.json")):
        kept = json.loads(path.read_text(encoding="utf-8"))
        target, session = path.stem.rsplit("-", 1) if "-" in path.stem else (path.stem, "")
        for block in kept.get("done", {}).values():
            for e in block.get("events", []):
                seti.append({"kind": "seti", "target": target, "session": session, **e})
    out += sorted(seti, key=lambda e: -e.get("snr", 0))
    return out


def next_lead():
    taken = done()
    return next((lead for lead in leads() if lead_id(lead) not in taken), None)


def parse_lead(words):
    text = " ".join(words).strip()
    if not text:
        return None
    if text.upper().startswith("TIC"):
        return {"kind": "tess", "tic": int(re.sub(r"\D", "", text))}
    import archive
    return {"kind": "kepler", "kic": archive.kic_number(text)}


# --- the procedure -----------------------------------------------------------------

def investigate_star(lead, get=requests.get, say=print, star=None, other=None, cfg=None):
    """Steps a to e on one star; the record and the report's text."""
    star = star or (kepler_star(lead["kic"]) if lead["kind"] == "kepler" else tess_star(lead["tic"]))
    ra, dec = float(star["ra"]), float(star["dec"])
    say(f"{star['star']}: {star['real_dips']} dip(s) left, deepest {star['deepest_percent']:.1f}%; asking the catalogues")
    checks = {"simbad": simbad(ra, dec, get), "vsx": vsx(ra, dec, get),
              "villanova": villanova(lead["kic"], get) if lead["kind"] == "kepler" else
              _asked("Villanova Kepler EB catalogue", VILLANOVA.format(kic=""), None, error="a TESS star: not in it"),
              "gaia": gaia(ra, dec, get), "ztf": ztf(ra, dec, get),
              "other_mission": other if other is not None else other_mission(lead, say)}
    verdict = judge(star, checks)
    watch = follow_up(star, verdict["deepest_percent"], cfg)
    return {"lead": lead_id(lead), "kind": lead["kind"], "star": star["star"], "ra": ra, "dec": dec,
            "mag": star.get("mag"), "mag_band": star.get("mag_band"), "crowdsap": star.get("crowdsap"),
            "light_curve": {"source": star.get("source"), "scatter_percent": star.get("scatter_percent"),
                            "trend": star.get("trend"),
                            "dips": [d for d in star["dips"] if d["verdict"] == "dip"][:20]},
            "checks": checks, **verdict, "follow_up": watch,
            "investigated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind_of_answer": "measured"}


def investigate_seti(lead):
    """A SETI candidate: the bands satellites use, and a drift of zero."""
    f = lead["frequency_mhz"]
    band = next((b for b in SATELLITE_BANDS if b[0] <= f <= b[1]), None)
    artefact = []
    if band:
        artefact.append(f"{f:.6f} MHz is in {band[2]} ({band[0]:g} to {band[1]:g} MHz, ITU Radio Regulations Article 5)")
    if abs(lead.get("drift_hz_s", 0.0)) < 1e-3:
        artefact.append("a drift of zero: fixed to the ground, as the telescope is")
    verdict = "artefact" if artefact else "unexplained, weak"
    notes = [] if artefact else ["weak: one cadence only; the next step is the same star at another time "
                                 "(Breakthrough Listen's other sessions, ./seti.py find)"]
    return {"lead": lead_id(lead), "kind": "seti", "star": lead["target"], "frequency_mhz": f,
            "drift_hz_s": lead.get("drift_hz_s"), "snr": lead.get("snr"), "session": lead.get("session"),
            "checks": {"bands": _asked("ITU Radio Regulations, Article 5", "https://www.itu.int/pub/R-REG-RR",
                                       band and band[2])},
            "verdict": verdict, "explained_by": [], "artefact_because": artefact, "notes": notes,
            "known_to_science": False, "follow_up": {"can_watch": False,
                                                     "reasons": ["a radio signal: not for this optical telescope"]},
            "investigated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind_of_answer": "measured"}


def report(r):
    """The record as Markdown: every answer with its link and the date asked."""
    lines = [f"# {r['star']}: {r['verdict']}", "",
             f"Looked into by `investigate.py` on {r['investigated'][:10]} ({r['kind']} lead `{r['lead']}`). "
             "An \"unexplained\" verdict is the end of these checks, not a discovery.", ""]
    if r["kind"] != "seti":
        lc = r["light_curve"]
        lines += ["## The light curve", "",
                  f"- Source: {lc['source']}",
                  f"- Magnitude {r['mag']} ({r['mag_band']}); scatter between dips {lc['scatter_percent']}%; "
                  f"CROWDSAP {r['crowdsap']}",
                  f"- Dips left after archive.py's checks: {r['dips']}, deepest {r['deepest_percent']:.2f}%"]
        for d in lc["dips"][:10]:
            lines.append(f"  - {d.get('date', '')}: {d['depth_percent']:.2f}% deep, {d.get('hours', 0):.1f} h, "
                         f"asymmetry {d.get('asymmetry', 0):+.2f}, seen in {d.get('seen_in', '?')}")
        if lc.get("trend") and lc["trend"].get("sap"):
            lines.append(f"- Long-term (SAP): {lc['trend']['sap']}")
    lines += ["", "## The checks", ""]
    for name, c in r["checks"].items():
        answer = c["error"] or (json.dumps(c["answer"], default=str) if c["answer"] not in (None, {}) else "nothing found")
        lines.append(f"- **{c['source']}** (asked {c['asked']}, {c['link']}): {answer}")
    lines += ["", "## The verdict", "", f"**{r['verdict']}**", ""]
    for why in r["explained_by"]:
        lines.append(f"- explained: {why}")
    for why in r["artefact_because"]:
        lines.append(f"- artefact: {why}")
    for note in r["notes"]:
        lines.append(f"- {note}")
    lines += ["", "## This telescope", ""]
    fu = r["follow_up"]
    lines.append(f"- {'Can' if fu['can_watch'] else 'Cannot'} watch it: " + "; ".join(fu["reasons"]))
    for u in fu.get("up", []):
        lines.append(f"  - {u['month']}: {u['dark_hours_up']:g} dark hours up" + (f", best {u['best']}" if u["best"] else ""))
    return "\n".join(lines) + "\n"


def keep(r, reports=REPORTS):
    path = records_dir() / f"{r['lead']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    records.write(path, r)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{r['lead']}.md").write_text(report(r), encoding="utf-8")
    return reports / f"{r['lead']}.md"


def investigate(words=(), get=requests.get, say=print):
    lead = parse_lead(words) or next_lead()
    if lead is None:
        raise interface.Refusal("INVALID_REQUEST", "No lead is waiting: the screens have flagged nothing not yet "
                                                   "looked into. ./archive.py screen --batch 200 finds more.")
    r = investigate_seti(lead) if lead["kind"] == "seti" else investigate_star(lead, get, say)
    path = keep(r)
    say(f"{r['star']}: {r['verdict']}")
    for why in r["explained_by"] + r["artefact_because"] + r["notes"]:
        say(f"  {why}")
    say(f"  this telescope: {'can' if r['follow_up']['can_watch'] else 'cannot'} watch it")
    say(f"  report: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    r["report"] = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("lead", nargs="*", help="KIC N or TIC N; none: the top lead nobody has looked into")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("investigate", lambda: investigate(args.lead), args.json)


if __name__ == "__main__":
    main()
