#!/usr/bin/env python3
"""Live cloud picture from the Meteosat weather satellite.

    ./clouds.py        the sky's evidence now, the same look the run and the
                       watches use: the satellite's newest picture (its time,
                       and 30 min before), the airports' reports, what they
                       say together; the picture saved for the web page
    ./clouds.py --history [HOURS]   the looks kept, with what the camera
                       measured at each: for checking the satellite's verdicts
    ./clouds.py --at 2026-11-05T04:30   the picture at that time (UT), saved
                       beside it as clouds-YYYYMMDD-HHMM.jpg: was it cloud?
    ./clouds.py --airports   only the airports' cloud reports (METARs) near
                       the site; a plain run prints them under the satellite's

Source: EUMETSAT's public image service (view.eumetsat.int), 10.5 µm
infrared, a new image every 10 minutes. Infrared works at night: clouds are
cold and show bright, clear ground and sea are warm and show dark.

The airports' reports come from aviationweather.gov: each airport's
ceilometer looks straight up and gives the cloud's cover and base, every 30
minutes while it is open. It sees only cloud below about 12,000 ft, so
"CAVOK" or "NCD" says nothing about high thin cloud, which the satellite
shows better. Each report gives the wind, so the airport upwind (most
often to the west, not always) is the one that sees cloud before it gets
here. An airport's air at its dew point means fog or dew there: a hint for
here, not proof of dew on the mirrors.

The satellite's verdict is a rough measure: the site's brightness against
the darkest tenth of the map, not calibrated against the telescope's own
frames, so it is evidence beside the camera, not proof either way.
`evidence()` puts the two together, with the picture's age, shared through
a file for 5 minutes by everything that reports dimmed or missing stars.
"""
import io
import math
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

import config

ROOT = Path(__file__).parent
PICTURE = config.DATA / "web" / "clouds.jpg"
WMS = "https://view.eumetsat.int/geoserver/wms"
WIDTH, HEIGHT = 1110, 510
# Degrees of latitude and longitude shown either side of the site.
SPAN_LAT, SPAN_LON = 1.7, 3.7


def _layer(name, box, transparent=False, when=None, timeout=60):
    extra = {"time": when.strftime("%Y-%m-%dT%H:%M:00Z")} if when else {}
    r = requests.get(WMS, timeout=timeout, params={**extra,
        "service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": name,
        "styles": "", "crs": "EPSG:4326", "bbox": ",".join(f"{v:.3f}" for v in box),
        "width": WIDTH, "height": HEIGHT, "format": "image/png",
        "transparent": str(transparent).lower()})
    r.raise_for_status()
    try:
        return Image.open(io.BytesIO(r.content))
    except OSError as error:
        # The service sometimes answers with an error page instead of a
        # picture (2 November 2026): said plainly, not as a traceback.
        raise RuntimeError(f"the satellite service sent no picture of {name} just now "
                           f"({r.headers.get('content-type', 'unknown')})") from error


def coastline(box):
    """Yellow coastline overlay for the map; fetched once and kept, since the
    service that draws it fails now and then. None if it has never worked."""
    kept = config.DATA / "cache" / "coastline_{:.2f}_{:.2f}.png".format(*box[:2])
    if not kept.exists():
        try:
            lines = np.array(_layer("backgrounds:ne_10m_coastline", box, True).convert("RGBA"))
        except requests.RequestException:
            return None
        lines[lines[..., 3] > 0] = (255, 220, 0, 255)
        kept.parent.mkdir(exist_ok=True)
        Image.fromarray(lines).save(kept)
    return Image.open(kept)


def picture_time(timeout=8):
    """When the newest infrared picture was taken (UTC): the time dimension's
    default in the service's own capabilities, read as XML, or None if it
    would not say. evidence() then asks for the picture at exactly that time,
    so the picture and its time are the same one."""
    import datetime as dt
    import xml.etree.ElementTree as ET
    try:
        r = requests.get("https://view.eumetsat.int/geoserver/mtg_fd/ir105_hrfi/ows", timeout=timeout,
                         params={"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"})
        r.raise_for_status()
        for node in ET.fromstring(r.content).iter():
            if node.tag.rsplit("}", 1)[-1] == "Dimension" and node.get("name") == "time" and node.get("default"):
                return dt.datetime.fromisoformat(node.get("default").replace("Z", "+00:00"))
    except (requests.RequestException, ValueError, ET.ParseError):
        pass
    return None


def update(site, when=None, timeout=60, save="auto"):
    """Fetch, annotate and save the image. Returns (brightness over the site,
    brightness of the darkest tenth of the map), both 0-255; the second is a
    stand-in for clear sky. `when` (UTC) is a past picture, saved under its
    own name so the page's live one is left alone: 5 November 2026, dimmed
    stars were put down to dew without a look at the satellite."""
    lat, lon = site["latitude"], site["longitude"]
    box = (lat - SPAN_LAT, lon - SPAN_LON, lat + SPAN_LAT, lon + SPAN_LON)
    infrared = _layer("mtg_fd:ir105_hrfi", box, when=when, timeout=timeout).convert("RGB")
    levels = np.asarray(infrared.convert("L"), dtype=float)
    x, y = WIDTH // 2, HEIGHT // 2
    here = float(levels[y - 4:y + 5, x - 4:x + 5].mean())
    clear = float(np.percentile(levels, 10))

    coast = coastline(box)
    if coast:
        infrared.paste(coast, (0, 0), coast)
    draw = ImageDraw.Draw(infrared)
    # A circle for where the telescope is, and no name: the picture is on the
    # page, and the place is nobody else's business (20 October 2026).
    draw.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(255, 40, 40), width=3)
    # Stretch vertically so distances look right at this latitude.
    true_height = round(WIDTH * SPAN_LAT / (SPAN_LON * np.cos(np.radians(lat))))
    # save: "auto" (the page's picture now, a dated one for a past time),
    # "page" (the page's, for a time asked for as the newest), None (not kept).
    out = None
    if save:
        out = PICTURE.with_name(f"clouds-{when:%Y%m%d-%H%M}.jpg") if when and save == "auto" else PICTURE
        out.parent.mkdir(exist_ok=True)
        infrared.resize((WIDTH, true_height)).save(out, quality=88)
    return here, clear, out


def verdict(here, clear):
    """The satellite's word on the site: "cloud", "thin or broken cloud" or "probably clear"."""
    return "cloud" if here - clear > 20 else "probably clear" if here - clear < 10 else "thin or broken cloud"


AVIATION = "https://aviationweather.gov/api/data"
COVER = {"FEW": "few (1-2/8)", "SCT": "scattered (3-4/8)", "BKN": "broken (5-7/8)",
         "OVC": "overcast", "VV": "sky hidden (fog)"}
SAYS = {"CAVOK": "no cloud below 5000 ft", "NCD": "no cloud detected below 12,000 ft",
        "NSC": "no significant cloud", "SKC": "clear", "CLR": "clear below 12,000 ft"}


def _compass(degrees):
    return "N NE E SE S SW W NW".split()[round((degrees % 360) / 45) % 8]


def _distance(lat1, lon1, lat2, lon2):
    """Kilometres and compass bearing from the first point to the second."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    km = 6371 * math.acos(min(1, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)))
    deg = math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                  math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)))
    return km, deg % 360


def airports(site, radius_km=150, timeout=30):
    """The newest cloud report of every airport within radius_km of the site,
    nearest first: dicts with the airport, its distance and direction from
    the site, the report's age in minutes, its cloud layers, what it says,
    the air and dew point (°C) and the raw METAR."""
    lat, lon = site["latitude"], site["longitude"]
    span_lat, span_lon = radius_km / 111, radius_km / (111 * math.cos(math.radians(lat)))
    box = f"{lat - span_lat:.2f},{lon - span_lon:.2f},{lat + span_lat:.2f},{lon + span_lon:.2f}"
    r = requests.get(f"{AVIATION}/metar", params={"bbox": box, "format": "json", "hours": 3}, timeout=timeout)
    r.raise_for_status()
    newest = {}
    for m in r.json() if r.text.strip() else []:
        if m["icaoId"] not in newest or m["obsTime"] > newest[m["icaoId"]]["obsTime"]:
            newest[m["icaoId"]] = m
    out = []
    for m in newest.values():
        km, bearing = _distance(lat, lon, m["lat"], m["lon"])
        if km > radius_km:
            continue
        layers = [f"{COVER.get(c['cover'], c['cover'])} at {c['base']} ft" if c.get("base") is not None
                  else COVER.get(c["cover"], c["cover"]) for c in m.get("clouds") or []]
        wind = None
        if m.get("wspd") is not None:
            wind = ("calm" if not m["wspd"] else f"{m['wspd']} kt from "
                    + (_compass(m["wdir"]) if isinstance(m.get("wdir"), (int, float)) else "varying directions"))
        out.append({"id": m["icaoId"], "name": m["name"].split(",")[0], "km": round(km),
                    "from": _compass(bearing), "bearing": round(bearing),
                    "wind_from": m["wdir"] if isinstance(m.get("wdir"), (int, float)) else None,
                    "wind_kt": m.get("wspd"),
                    "covers": [c["cover"] for c in m.get("clouds") or []], "wind": wind,
                    "age_min": round((time.time() - m["obsTime"]) / 60), "layers": layers,
                    "says": "; ".join(layers) or SAYS.get(m.get("cover"), m.get("cover") or "no cloud given"),
                    "temp_c": m.get("temp"), "dew_c": m.get("dewp"), "raw": m["rawOb"]})
    return sorted(out, key=lambda a: a["km"])


def airport_lines(site, found=None):
    """The airports' reports (`found`, or fetched now) as lines to print, or
    one line saying none came."""
    try:
        found = airports(site) if found is None else found
    except (requests.RequestException, ValueError) as problem:
        return [f"No airport reports: {problem}"]
    if not found:
        return ["No airport reports within 150 km in the last 3 hours."]
    lines = []
    for a in found:
        damp = ""
        if a["temp_c"] is not None and a["dew_c"] is not None and a["temp_c"] - a["dew_c"] <= 1:
            damp = f", air {a['temp_c']} °C at its dew point {a['dew_c']} °C: fog or dew there"
        old = f" ({a['age_min']} min ago, closed now?)" if a["age_min"] > 75 else f" ({a['age_min']} min ago)"
        wind = f", wind {a['wind']}" if a["wind"] else ""
        lines.append(f"{a['name']} {a['id']}, {a['km']} km {a['from']}: {a['says']}{damp}{wind}{old}")
    return lines


EVIDENCE = config.DATA / "cache" / "cloud_evidence.json"
HISTORY = config.DATA / "cache" / "cloud_evidence.jsonl"
FRESH_S = 300          # one look at the sky's evidence serves every script for 5 minutes
RETRY_S = 60           # a look with a source missing is tried again after a minute
BUDGET_S = 25          # the whole look, both services at once, never takes longer
SATELLITE_STALE_MIN = 40
TREND_MIN = 30         # the satellite's picture this long before, for which way it is going
UPWIND_DEG = 60        # an airport within this of the wind's direction is upwind
NEAR_KM = 30           # an airport this close shares the site's sky


def _satellite(site):
    """The satellite's verdict now and TREND_MIN before, with the picture's
    time; the page's picture is the newest one. Unknown time: no verdict."""
    import datetime as dt
    taken = picture_time()
    if taken is None:
        return {"satellite": None, "satellite_time": None, "satellite_was": None,
                "satellite_why": "the service would not say when its newest picture was taken"}
    age = (time.time() - taken.timestamp()) / 60
    if age > SATELLITE_STALE_MIN:
        return {"satellite": None, "satellite_time": taken.isoformat(), "satellite_was": None,
                "satellite_why": f"its newest picture is {age:.0f} min old: stale"}
    out = {"satellite_time": taken.isoformat(), "satellite_why": None}
    try:
        here, clear, _ = update(site, taken, timeout=15, save="page")
        out.update(satellite=verdict(here, clear), satellite_here=round(here, 1), satellite_clear=round(clear, 1),
                   satellite_margin=round(here - clear, 1))
    except (RuntimeError, requests.RequestException, OSError) as problem:
        return {**out, "satellite": None, "satellite_was": None, "satellite_why": f"no picture: {problem}"}
    try:
        here, clear, _ = update(site, taken - dt.timedelta(minutes=TREND_MIN), timeout=15, save=None)
        out.update(satellite_was=verdict(here, clear), satellite_was_margin=round(here - clear, 1))
    except (RuntimeError, requests.RequestException, OSError):
        out["satellite_was"] = None
    return out


_LEFT = []   # this process's requests that outran the budget, still ending


def _gather(site):
    """Both services at once, the whole look bounded by BUDGET_S. A request
    still going at the budget is left to end on its own timeout (38 s at
    most), and no new look starts in this process until it has, so slow
    services never pile requests up."""
    from concurrent.futures import ThreadPoolExecutor, wait
    _LEFT[:] = [f for f in _LEFT if not f.done()]
    if _LEFT:
        return {"satellite": None, "satellite_time": None, "satellite_was": None, "airports": None,
                "satellite_why": "the last look's requests are still ending"}
    pool = ThreadPoolExecutor(max_workers=2)
    sat, near = pool.submit(_satellite, site), pool.submit(airports, site, timeout=8)
    wait([sat, near], timeout=BUDGET_S)
    _LEFT.extend(f for f in (sat, near) if not f.done())
    pool.shutdown(wait=False, cancel_futures=True)
    found = {"satellite": None, "satellite_time": None, "satellite_was": None,
             "satellite_why": f"no answer within {BUDGET_S} s"}
    if sat.done() and not sat.exception():
        found = sat.result()
    found["airports"] = None
    if near.done() and not near.exception():
        found["airports"] = [a for a in near.result() if a["age_min"] <= 75]
    return found


def _kept(max_age_s):
    """The shared look, if it is young enough: max_age_s, or RETRY_S when a
    source was missing from it."""
    import json
    try:
        kept = json.loads(EVIDENCE.read_text())
        if time.time() - kept["at"] < (RETRY_S if kept.get("partial") else max_age_s):
            return kept
    except (OSError, ValueError, KeyError):
        pass
    return None


def _refresh(max_age_s):
    """A new look, taken by one script at a time: another that wants it
    waits (BUDGET_S at most) for the first's look instead of fetching too.
    (_gather says what happens to a request that outruns the budget.)"""
    import fcntl
    import json
    import os
    EVIDENCE.parent.mkdir(exist_ok=True)
    with open(EVIDENCE.with_suffix(".lock"), "w") as lock:
        give_up = time.monotonic() + BUDGET_S + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > give_up:
                    return _kept(10 ** 9) or {"satellite": None, "airports": None, "partial": True,
                                              "satellite_why": "another script's look is still running",
                                              "together": together(None, None)}
                time.sleep(0.5)
        fresh = _kept(max_age_s) if max_age_s else None   # taken while this one waited
        if fresh:
            return fresh
        found = _gather(config.load()["site"])
        found["at"] = time.time()
        found["partial"] = found["satellite"] is None or found["airports"] is None
        found["together"] = together(found["satellite"], found["airports"], found.get("satellite_was"))
        try:
            spare = EVIDENCE.with_suffix(f".{os.getpid()}.tmp")
            spare.write_text(json.dumps(found))
            os.replace(spare, EVIDENCE)   # whole or not at all
        except OSError:
            pass
        return found


def evidence(max_age_s=FRESH_S, context=None):
    """One look at the sky's evidence, shared by clouds.py, shoot.py,
    runwatch.py and skywatch.py through a file: the satellite's verdict over
    the site with its picture's own time (unknown or over 40 minutes old is
    no verdict) and 30 minutes before; the airports' reports of the last 75
    minutes, each with its own age and wind; and what they say together.
    Kept 5 minutes, or 1 when a source was missing; the whole look takes at
    most 25 s. Every call is added to cloud_evidence.jsonl, with `context`
    (what the camera measured then) when given, so the satellite's
    thresholds can be checked against the telescope's own frames."""
    import json
    found = _kept(max_age_s) or _refresh(max_age_s)
    try:
        with HISTORY.open("a") as log:
            log.write(json.dumps({"t": time.time(), "satellite": found["satellite"],
                                  "satellite_was": found.get("satellite_was"),
                                  **{k: found.get(k) for k in ("satellite_here", "satellite_clear",
                                                               "satellite_margin", "satellite_was_margin")},
                                  "satellite_time": found.get("satellite_time"),
                                  "airports": [{k: a.get(k) for k in ("id", "km", "bearing", "covers", "layers",
                                                                      "wind_from", "wind_kt", "age_min")}
                                               for a in found["airports"] or []],
                                  "together": found["together"], "context": context}) + "\n")
    except OSError:
        pass
    return found


def _upwind(a):
    """Whether the airport lies the way its own wind comes from. Surface wind
    says where low cloud is coming from; high cloud can move differently."""
    if a.get("wind_from") is None or (a.get("wind_kt") or 0) < 5:
        return False
    return abs((a["bearing"] - a["wind_from"] + 180) % 360 - 180) <= UPWIND_DEG


def together(seen, near, was=None):
    """What the satellite and the airports say between them. An airport
    within 30 km shares the site's sky; one upwind says what is coming;
    any other only says there is cloud in the region, which supports a
    cloudy verdict loosely. Unknown is never clear; and clear on both still
    leaves thin high cloud, which neither sees well, as well as dew or a
    fault."""
    near = near or []
    low = [a for a in near if set(a["covers"]) & {"BKN", "OVC", "VV"}]
    here = [a for a in low if a["km"] <= NEAR_KM]
    coming = [a for a in low if a["km"] > NEAR_KM and _upwind(a)]
    region = [a for a in low if a not in here and a not in coming]
    named = lambda found: ", ".join(f"{a['name'].split('/')[0]} {a['km']} km {a['from']}" for a in found)  # noqa: E731
    cloudy = seen in ("cloud", "thin or broken cloud")
    trend = ""
    if seen and was:
        was_cloudy = was in ("cloud", "thin or broken cloud")
        trend = {(True, False): f" (its verdict {TREND_MIN} min ago was {was})",
                 (False, True): f" (its verdict {TREND_MIN} min ago was {was})",
                 (True, True): f" (the same {TREND_MIN} min ago)"}.get((cloudy, was_cloudy), "")
    if seen is None and not near:
        return "no satellite verdict and no airport report: the sky is unknown, not clear"
    words = []
    if seen is None:
        words.append("no satellite verdict")
    elif cloudy:
        words.append(f"the satellite puts {seen} over the site{trend}")
    else:
        words.append(f"the satellite sees no cloud over the site{trend}")
    if here:
        words.append(f"low cloud at {named(here)}, close enough to share this sky")
    if coming:
        words.append(f"low cloud upwind at {named(coming)} by its surface wind: it may be heading here")
    if region:
        words.append(f"low cloud elsewhere in the region at {named(region)}, not upwind: "
                     "only loose support")
    if not low and near:
        words.append("no low cloud at the airports" + (": high cloud, which their ceilometers don't reach"
                                                       if cloudy else ""))
    if not cloudy and not here:
        words.append("thin high cloud is still possible, or dew, or a fault: look up")
    elif seen is not None and not cloudy and here:
        words.append("they disagree: look up")
    return "; ".join(words)


def evidence_words(found=None):
    """The evidence as one line for a message about dimmed or missing stars."""
    found = found or evidence()
    if found["satellite"]:
        sat = f"{found['satellite']} over the site"
    else:
        sat = f"no verdict ({found.get('satellite_why') or 'no picture'})"
    near = "; ".join(f"{a['name'].split('/')[0]} {a['km']} km {a['from']} {a['says']}"
                     + (f", wind {a['wind']}" if a["wind"] else "") for a in found["airports"] or [])
    return f"satellite: {sat}" + (f"; airports: {near}" if near else "") + f". {found['together']}"


def history_lines(hours=24):
    """The kept looks of the last `hours`, with what the camera measured, one
    line each: the record for checking the satellite against the frames."""
    import datetime as dt
    import json
    out = []
    try:
        rows = [json.loads(line) for line in HISTORY.read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        return ["no looks kept yet"]
    for r in rows:
        if r["t"] < time.time() - hours * 3600:
            continue
        c = r.get("context") or {}
        camera = ", ".join(f"{k} {v}" for k, v in c.items()) or "no camera figures"
        out.append(f"{dt.datetime.fromtimestamp(r['t']):%d %b %H:%M}  satellite {r['satellite'] or '-'}"
                   f" (was {r.get('satellite_was') or '-'})  camera: {camera}")
    return out or [f"no looks in the last {hours} h"]


if __name__ == "__main__":
    import argparse
    import datetime as dt
    ap = argparse.ArgumentParser(description="The sky's evidence: Meteosat and the airports.")
    ap.add_argument("--at", metavar="YYYY-MM-DDTHH:MM", help="a past time, UT: the satellite's picture then")
    ap.add_argument("--airports", action="store_true", help="only the airports' cloud reports")
    ap.add_argument("--history", type=float, metavar="HOURS", nargs="?", const=24,
                    help="the looks kept in the last HOURS (24), with what the camera measured")
    args = ap.parse_args()
    if args.history:
        print("\n".join(history_lines(args.history)))
        raise SystemExit
    if args.airports:
        print("\n".join(airport_lines(config.load()["site"])))
        raise SystemExit
    if args.at:
        when = dt.datetime.fromisoformat(args.at).replace(tzinfo=dt.timezone.utc)
        try:
            here, clear, saved = update(config.load()["site"], when)
        except (RuntimeError, requests.RequestException) as problem:
            raise SystemExit(f"No satellite picture: {problem}. Try again in a few minutes.")
        print(f"over the site: {here:.0f}, clear areas: {clear:.0f} -> {verdict(here, clear)}")
        raise SystemExit(f"saved {saved}")
    # Now: the same shared look the run and the watches use, fetched fresh.
    found = evidence(max_age_s=0)
    if found["satellite"]:
        print(f"satellite: {found['satellite']} over the site, picture taken {found['satellite_time'][11:16]} UT"
              + (f"; {TREND_MIN} min before: {found['satellite_was']}" if found.get("satellite_was") else ""))
        print(f"saved {PICTURE}")
    else:
        print(f"satellite: no verdict ({found.get('satellite_why')})")
    if found["airports"] is None:
        print("airports: no answer")
    else:
        print("\n".join(airport_lines(config.load()["site"], found["airports"])))
    print(found["together"])