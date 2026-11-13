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
    ./clouds.py --approach   the nearest clear sky, which way and how fast the
                       cloud moves (the last hour's pictures), and when
                       clear sky upwind gets here, with a range; each of the
                       three nearest gaps followed by the cloud round it
                       (reaches here when, or misses by how much); an
                       unsure or still movement said as that; every
                       movement put to the cloud layer whose wind it
                       matches (Open-Meteo's winds at 850, 700 and 300 hPa
                       and its low, mid and high cloud), and the clear sky
                       carried by the wind of the layer that has the cloud
                       when the satellite's own reading is another layer's,
                       still or unsure; run by
                       .claude/hooks/sky.py whenever the person talks about
                       the sky
    ./clouds.py --view close|medium|wide   the picture in that view, saved as
                       web/clouds-VIEW.jpg (close is the run's own,
                       web/clouds.jpg); with --approach, the approach in it
    ./clouds.py --scores [DAYS]   each clear-sky and rain prediction kept
                       (cache/sky_predictions.jsonl) against the first sight
                       of it after (cache/sky_seen.jsonl: skywatch's star
                       counts, the radar over the site): how early or late

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
# The map's three views: degrees of longitude west and east of the site,
# of latitude either side, and pixels to the close view's one (2 is half
# the detail). Close is the map the run's verdicts have always used; 13
# November 2026, a gap the person could see coming over the Atlantic was
# off it (it reached 236 km west), so --approach looks at the medium view
# (about 630 km west, where most weather comes from, at the same detail),
# and the wide one shows the Atlantic out to 20 degrees W.
VIEWS = {"close": (3.7, 3.7, 1.7, 1), "medium": (9.9, 3.7, 1.7, 1), "wide": (20.0, 6.0, 6.0, 2)}
APPROACH_VIEW = "medium"


class View:
    """One view's box, size in pixels, the site's pixel and km a pixel."""

    def __init__(self, site, name="close"):
        west, east, span, scale = VIEWS[name]
        lat, lon = site["latitude"], site["longitude"]
        self.name = name
        self.width = round(1110 * (west + east) / 7.4 / scale)
        self.height = round(510 * 2 * span / 3.4 / scale)
        self.x, self.y = round(self.width * west / (west + east)), self.height // 2
        self.box = (lat - span, lon - west, lat + span, lon + east)
        self.kx = 111.32 * math.cos(math.radians(lat)) * (west + east) / self.width     # km a pixel, east-west
        self.ky = 111.32 * 2 * span / self.height                                       # km a pixel, north-south
        # The site's own neighbourhood, the close view's width: the clear-sky
        # reference (the darkest tenth) and the whole cloud's movement are
        # measured over it in every view, so the wider ocean (warm, dark)
        # does not change what counts as clear.
        half = 555 // scale
        self.near = slice(max(self.x - half, 0), min(self.x + half, self.width))
        self.km = (west * 111 * math.cos(math.radians(lat)), east * 111 * math.cos(math.radians(lat)), span * 111)


def _layer(name, box, size, transparent=False, when=None, timeout=60):
    extra = {"time": when.strftime("%Y-%m-%dT%H:%M:00Z")} if when else {}
    r = requests.get(WMS, timeout=timeout, params={**extra,
        "service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": name,
        "styles": "", "crs": "EPSG:4326", "bbox": ",".join(f"{v:.3f}" for v in box),
        "width": size[0], "height": size[1], "format": "image/png",
        "transparent": str(transparent).lower()})
    r.raise_for_status()
    try:
        return Image.open(io.BytesIO(r.content))
    except OSError as error:
        # The service sometimes answers with an error page instead of a
        # picture (2 November 2026): said plainly, not as a traceback.
        raise RuntimeError(f"the satellite service sent no picture of {name} just now "
                           f"({r.headers.get('content-type', 'unknown')})") from error


def coastline(box, size):
    """Yellow coastline overlay for the map; fetched once and kept, since the
    service that draws it fails now and then. None if it has never worked."""
    kept = config.DATA / "cache" / "coastline_{:.2f}_{:.2f}.png".format(*box[:2])
    if not kept.exists():
        try:
            lines = np.array(_layer("backgrounds:ne_10m_coastline", box, size, True).convert("RGBA"))
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


def update(site, when=None, timeout=60, save="auto", view="close"):
    """Fetch, annotate and save the image. Returns (brightness over the site,
    brightness of the darkest tenth of the map), both 0-255; the second is a
    stand-in for clear sky. `when` (UTC) is a past picture, saved under its
    own name so the page's live one is left alone: 5 November 2026, dimmed
    stars were put down to dew without a look at the satellite."""
    lat = site["latitude"]
    v = View(site, view)
    infrared = _layer("mtg_fd:ir105_hrfi", v.box, (v.width, v.height), when=when, timeout=timeout).convert("RGB")
    levels = np.asarray(infrared.convert("L"), dtype=float)
    x, y = v.x, v.y
    here = float(levels[y - 4:y + 5, x - 4:x + 5].mean())
    clear = float(np.percentile(levels[:, v.near], 10))

    coast = coastline(v.box, (v.width, v.height))
    if coast:
        infrared.paste(coast, (0, 0), coast)
    draw = ImageDraw.Draw(infrared)
    # A circle for where the telescope is, and no name: the picture is on the
    # page, and the place is nobody else's business (20 October 2026).
    draw.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(255, 40, 40), width=3)
    # Stretch vertically so distances look right at this latitude.
    west, east, span, _ = VIEWS[view]
    true_height = round(v.width * 2 * span / ((west + east) * np.cos(np.radians(lat))))
    # save: "auto" (the page's picture now, a dated one for a past time),
    # "page" (the page's, for a time asked for as the newest), None (not kept).
    out = None
    if save:
        page = PICTURE if view == "close" else PICTURE.with_name(f"clouds-{view}.jpg")
        out = page.with_name(f"{page.stem}-{when:%Y%m%d-%H%M}.jpg") if when and save == "auto" else page
        out.parent.mkdir(exist_ok=True)
        infrared.resize((v.width, true_height)).save(out, quality=88)
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


APPROACH = config.DATA / "cache" / "cloud_approach.json"     # the medium view's; the others' beside it
STEP_MIN = 10              # the satellite's pictures come every 10 minutes
PICTURES = 7               # the last hour's: the cloud's movement is measured between pairs of them
APPROACH_MAX_PX = 60       # the most a picture's cloud may move between two of them (about 25-45 km)
APPROACH_HOURS = 6         # how far ahead an arrival is looked for
LASTS_HOURS = 4            # and how far past an arrival its end is (13 November 2026: a gap due at 00:05
                           # read "its end not on the map" only because the six hours ran out at 01:00)
CLEAR_MARGIN, BROKEN_MARGIN = 10, 20   # as verdict(): brightness over the clear tenth
GAPS = 3                   # the nearest clear areas each followed on its own
GAP_MIN_KM2 = 1000         # a clear area smaller than this (about 30 x 30 km) is a speck, not a gap
GAP_WINDOW = (120, 200)    # px (rows, columns), about 90 x 85 km: a gap's own movement is measured in this
GAP_HIT_KM = 3             # a gap's edge this near the site counts as over it
SLOW_KMH = 3               # under this the cloud is standing still, as near as the pictures tell
MATCH_KMH = 12             # a movement within this of a layer's wind (or 40 % of the wind) is that layer's
COVER_MIN = 30             # % : a model layer with less cloud than this is not the cloud over the site


SAT_KEPT = config.DATA / "cache" / "satellite"     # past pictures, one file each: they never change
SAT_KEEP_HOURS = 6


def _maybe_levels(site, when, view):
    """_levels, or None when that picture will not come: the check goes on
    with the ones that did."""
    try:
        return _levels(site, when, view)
    except (RuntimeError, requests.RequestException, OSError):
        return None


def _levels(site, when, view, timeout=30, tries=3):
    """One past picture as grey levels: from the pictures kept, or fetched
    (tried again after a pause when the service is slow) and kept. A past
    picture never changes, so each is fetched once: 12 November 2026,
    23:07-23:20, view.eumetsat.int gave 504s and timeouts on timed pictures
    while the newest came in 7 s, and fetching the whole hour again for
    every check left the cloud's movement unknown for a quarter of an hour."""
    box = view.box
    kept = SAT_KEPT / f"ir105-{when:%Y%m%d%H%M}-{box[0]:.2f}_{box[1]:.2f}.png"
    if kept.exists():
        try:
            return np.asarray(Image.open(kept).convert("L"), float)
        except OSError:
            kept.unlink(missing_ok=True)
    for attempt in range(tries):
        try:
            picture = _layer("mtg_fd:ir105_hrfi", box, (view.width, view.height), when=when,
                             timeout=timeout).convert("L")
            break
        except (RuntimeError, requests.RequestException, OSError):
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    SAT_KEPT.mkdir(parents=True, exist_ok=True)
    picture.save(kept)
    for old in SAT_KEPT.glob("ir105-*.png"):       # a few hours' worth is all any check needs
        if time.time() - old.stat().st_mtime > SAT_KEEP_HOURS * 3600:
            old.unlink(missing_ok=True)
    return np.asarray(picture, float)


def _shift(before, after):
    """(dx, dy) pixels the picture moved from `before` to `after`, by phase
    correlation over the whole map, or None when no clear peak."""
    window = np.outer(np.hanning(before.shape[0]), np.hanning(before.shape[1]))
    a = np.fft.fft2((before - before.mean()) * window)
    b = np.fft.fft2((after - after.mean()) * window)
    cross = np.conj(a) * b
    surface = np.fft.ifft2(cross / np.maximum(np.abs(cross), 1e-9)).real
    h, w = surface.shape
    dy, dx = np.meshgrid(np.fft.fftfreq(h, 1 / h), np.fft.fftfreq(w, 1 / w), indexing="ij")
    surface[(np.abs(dx) > APPROACH_MAX_PX) | (np.abs(dy) > APPROACH_MAX_PX)] = -np.inf
    # What does not move (the land warmer than the sea, the map's edges)
    # matches itself at no shift and would hide the cloud's movement: the
    # cloud's own peak is looked for away from it. 12 November 2026: the
    # first try read 0 km/h with the gap visibly moving.
    surface[(np.abs(dx) <= 2) & (np.abs(dy) <= 2)] = -np.inf
    noise = float(np.std(surface[np.isfinite(surface)]))
    peak = np.unravel_index(int(np.argmax(surface)), surface.shape)
    if surface[peak] < 4 * noise:
        return None
    # A peak on the edge of the search is the edge, not the cloud: 13
    # November 2026, five of twelve pairs read exactly 60 px east, the
    # limit, while the cloud was barely moving.
    if abs(dx[peak]) >= APPROACH_MAX_PX or abs(dy[peak]) >= APPROACH_MAX_PX:
        return None
    return float(dx[peak]), float(dy[peak])


def _movement(pictures, rows=slice(None), cols=slice(None)):
    """The cloud's movement in one part of the map over the last hour's
    pictures: (vx, vy pixels a minute, pairs agreeing, pairs measured), or
    None when fewer than three pairs gave a clear peak."""
    moves = []
    for a in range(len(pictures)):
        for b in range(a + 1, len(pictures)):
            minutes = (b - a) * STEP_MIN
            if 20 <= minutes <= 40 and pictures[a] is not None and pictures[b] is not None:
                s = _shift(pictures[a][rows, cols], pictures[b][rows, cols])
                if s:
                    moves.append((s[0] / minutes, s[1] / minutes))
    if len(moves) < 3:
        return None
    vx, vy = float(np.median([m[0] for m in moves])), float(np.median([m[1] for m in moves]))
    agree = [m for m in moves if math.hypot(m[0] - vx, m[1] - vy) <= 0.5 * max(math.hypot(vx, vy), 0.2)]
    return vx, vy, agree, len(moves)


def _gaps(pictures, now, ref, v, steer=None, main=None):
    """The nearest clear areas, each with its own movement and where it goes:
    reaching the site (when, and for how long) or passing it (how near, and
    when). 13 November 2026: the person saw a big gap coming from the west;
    the whole map's movement read 0 km/h with 4 of 12 pairs agreeing (high
    streaks and lower cloud moving different ways) and said the clear sky
    was not on the cloud's track, so it could not say whether the gap would
    reach us. A gap is followed by the cloud round it, not the whole map."""
    from scipy.ndimage import label
    cx, cy, kx, ky = v.x, v.y, v.kx, v.ky
    labels, count = label((now - ref) < CLEAR_MARGIN)
    if not count:
        return []
    here = labels[cy, cx]
    found = []
    for n in range(1, count + 1):
        if n == here:
            continue
        ys, xs = np.nonzero(labels == n)
        if len(xs) * kx * ky < GAP_MIN_KM2:
            continue
        east, north = (xs - cx) * kx, (cy - ys) * ky
        dist = np.hypot(east, north)
        i = int(np.argmin(dist))
        found.append((float(dist[i]), int(xs[i]), int(ys[i]), east, north, len(xs) * kx * ky, n))
    found.sort(key=lambda g: g[0])
    out = []
    for dist, ex, ey, east, north, area, n in found[:GAPS]:
        h, w = GAP_WINDOW
        top = min(max(ey - h // 2, 0), v.height - h)
        left = min(max(ex - w // 2, 0), v.width - w)
        gap = {"km": round(dist), "bearing": _compass(math.degrees(math.atan2((ex - cx) * kx, (cy - ey) * ky)) % 360),
               "area_km2": round(area, -1)}
        m = _movement(pictures, slice(top, top + h), slice(left, left + w))
        own = None
        if m is None:
            gap["movement"] = None
        else:
            vx, vy, agree, total = m
            own = (vx * kx * 60, -vy * ky * 60)
            gap["pairs_agreeing"] = f"{len(agree)} of {total}"
            gap["speed_kmh"] = round(math.hypot(*own))
            gap["moving_from"] = _from(own)
            gap["unsure"] = 2 * len(agree) < total
            if not gap["unsure"] and steer:
                gap["seen_layer"] = _which_layer(own, steer)
        use = _choose(own if m and not gap["unsure"] else None, gap.get("seen_layer"), steer, main)
        if use is None:
            out.append(gap)
            continue
        gap["by"] = use[1]
        ve, vn = use[0][0] / 60, use[0][1] / 60          # km a minute
        step = max(1, len(east) // 2000)
        e, nn = east[::step], north[::step]

        def track(f):
            """(minutes until the gap is over the site or None, minutes it stays, closest km, at minutes).
            Over the site is read from the gap's own pixels, the point that
            will be carried over the site looked up in them; the closest pass
            from a sample of them. 13 November 2026: from the sample alone a
            158,600 km2 gap was "over us about 5 min", the sample's holes
            read as its end."""
            start = stay = None
            closest, at = None, None
            for minutes in range(0, (APPROACH_HOURS + LASTS_HOURS) * 60 + 1, 5):
                if start is None and minutes > APPROACH_HOURS * 60:
                    break
                if start is not None and stay is not None:
                    break
                x = round(cx - ve * f * minutes / kx)
                y = round(cy + vn * f * minutes / ky)
                inside = 0 <= x < v.width and 0 <= y < v.height
                over = inside and labels[y, x] == n
                d = 0.0 if over else float(np.min(np.hypot(e + ve * f * minutes, nn + vn * f * minutes)))
                if closest is None or d < closest:
                    closest, at = d, minutes
                if over and start is None:
                    start = minutes
                elif start is not None and stay is None and inside and not over:
                    stay = minutes - start
                elif start is not None and not inside:
                    break           # its far side is off the map: its end unknown
            return start, stay, closest, at

        start, stay, closest, at = track(1)
        starts = [s for s in (track(0.75)[0], start, track(1.25)[0]) if s is not None]
        gap.update(arrives_min=start, lasts_min=stay, arrives_range_min=[min(starts), max(starts)] if starts else None,
                   closest_km=round(closest), closest_min=at)
        out.append(gap)
    return out


def _from(move):
    """The compass point a movement (east, north) comes from."""
    return _compass((math.degrees(math.atan2(move[0], move[1])) + 180) % 360)


def _steering(site, when):
    """The model's cloud and wind at each layer for the hour nearest `when`:
    {"low": {hpa, cover, speed_kmh, from, move (east, north km/h)}, ...}, or
    None when the model is not to be had. The satellite shows cloud moving
    but not at what height; thin high streaks and low cloud under them move
    differently (high cloud with the fast wind aloft). The model says which
    layers have cloud and how each layer's wind blows, so a movement the
    satellite measures is put to the layer whose wind it matches, as the
    weather services' own cloud-motion winds are put to a height."""
    import feeds
    try:
        w = feeds.winds(site["latitude"], site["longitude"])
    except Exception:      # noqa: BLE001 - the approach goes on from the satellite alone
        return None
    if not w or not w.get("time"):
        return None
    t = when.timestamp()
    i = min(range(len(w["time"])), key=lambda k: abs(w["time"][k] - t))
    if abs(w["time"][i] - t) > 5400:
        return None          # an old copy kept when the service failed: not this hour's
    out = {}
    for layer, hpa in feeds.WIND_LEVELS.items():
        speed, d = w.get(f"wind_speed_{hpa}hPa", [None])[i], w.get(f"wind_direction_{hpa}hPa", [None])[i]
        if speed is None or d is None:
            continue
        r = math.radians(d)
        out[layer] = {"hpa": hpa, "cover": w.get(f"cloud_cover_{layer}", [None])[i] or 0, "speed_kmh": round(speed),
                      "from": _compass(d), "move": (-speed * math.sin(r), -speed * math.cos(r))}
    return out or None


def _main_layer(steer):
    """The layer with the most cloud by the model (the lowest of equals), or None under COVER_MIN everywhere."""
    if not steer:
        return None
    cloudy = [(c["cover"], -n, layer) for n, (layer, c) in enumerate(steer.items()) if c["cover"] >= COVER_MIN]
    return max(cloudy)[2] if cloudy else None


def _which_layer(move, steer):
    """The layer whose wind a movement (east, north km/h) matches, or None."""
    best = None
    for layer, c in steer.items():
        miss = math.hypot(move[0] - c["move"][0], move[1] - c["move"][1])
        if miss <= max(MATCH_KMH, 0.4 * c["speed_kmh"]) and (best is None or miss < best[1]):
            best = (layer, miss)
    return best[0] if best else None


def _choose(seen, seen_layer, steer, main):
    """The movement (east, north km/h) to carry clear sky by, and what it is
    from: the satellite's own when it agrees with the cloud's layer (or the
    model has no cloud layer to say), else that layer's wind; None when
    neither will do. 13 November 2026: close and medium read the low cloud
    as still, the wide view read 76 km/h from the W, the high wind; the
    model's 850 hPa wind, 24 km/h from the WSW, was the low cloud's."""
    if seen is not None and math.hypot(*seen) >= SLOW_KMH and (main is None or seen_layer == main):
        return seen, "satellite"
    if main is not None:
        return steer[main]["move"], main
    return None


def _failed(why, site):
    """An approach answer with no pictures: said as it is, the airports'
    reports in its place (12 November 2026, 23:07: EUMETSAT timed out and
    --approach stopped on a KeyError instead)."""
    lines = [f"satellite: {why}"]
    try:      # the newest picture alone, asked without a time, often still comes when the past ones do not
        here, clear, _ = update(site)
        lines.append(f"newest satellite picture alone: {verdict(here, clear)} over the site (no movement without "
                     "the past pictures)")
    except Exception as problem:      # noqa: BLE001
        lines.append(f"newest satellite picture: none either ({problem.__class__.__name__})")
    try:
        lines += airport_lines(site)
    except Exception as problem:      # noqa: BLE001 - the answer goes out without them
        lines.append(f"airports: none ({problem.__class__.__name__})")
    return {"t": time.time(), "error": why, "lines": lines}


def _approach_file(view):
    return APPROACH if view == APPROACH_VIEW else APPROACH.with_name(f"cloud_approach-{view}.json")


def approach(site=None, fresh_s=0, view=APPROACH_VIEW):
    """Where the nearest clear sky is and when it gets here, from the
    satellite's last hour of pictures (every pair 20-40 min apart, the median): the cloud's
    movement measured between them, then the clear sky upstream of the site
    carried along it. Also the nearest clear area now, wherever it is.

    12 November 2026: told of a big gap coming from Scotland, I reported the
    camera's star count; working out by eye from two pictures that the
    gap's edge was 45 km east and creeping west took a second request. This
    gives that at once. Clouds also grow and melt as they move, so it is a
    guide with a range, not a promise."""
    import concurrent.futures
    import datetime as dt
    import json
    from scipy.ndimage import uniform_filter
    if fresh_s:
        try:
            kept = json.loads(_approach_file(view).read_text(encoding="utf-8"))
            if time.time() - kept["t"] < fresh_s:
                return kept
        except (OSError, ValueError, KeyError):
            pass
    site = site or config.load()["site"]
    v = View(site, view)
    taken = picture_time()
    if taken is None:
        return _failed("the satellite service would not say when its newest picture was taken", site)
    times = [taken - dt.timedelta(minutes=STEP_MIN * k) for k in range(PICTURES - 1, -1, -1)]
    try:
        with concurrent.futures.ThreadPoolExecutor(2) as pool:      # gently: the service struggles with more
            pictures = list(pool.map(lambda when: _maybe_levels(site, when, v), times))
    except (RuntimeError, requests.RequestException, OSError) as problem:
        return _failed(f"no satellite pictures: {problem}", site)
    if pictures[-1] is None:
        return _failed("the newest satellite picture did not come", site)
    missing = sum(p is None for p in pictures)
    kx, ky = v.kx, v.ky
    now = uniform_filter(pictures[-1], 9)
    ref = float(np.percentile(pictures[-1][:, v.near], 10))
    cx, cy = v.x, v.y
    answer = {"t": time.time(), "picture": taken.isoformat(), "here": verdict(float(now[cy, cx]), ref),
              "view": view, "map_km": [round(k) for k in v.km]}
    if missing:
        answer["pictures_missing"] = f"{missing} of {PICTURES}"

    # The nearest clear area now, any direction.
    clear = (now - ref) < CLEAR_MARGIN
    ys, xs = np.nonzero(clear)
    if len(xs):
        east, north = (xs - cx) * kx, (cy - ys) * ky
        dist = np.hypot(east, north)
        i = int(np.argmin(dist))
        answer["nearest_clear_km"] = round(float(dist[i]))
        answer["nearest_clear_bearing"] = _compass(math.degrees(math.atan2(east[i], north[i])) % 360)

    # The model's layers: which has the cloud, and how each one's wind blows.
    steer = _steering(site, taken)
    main = _main_layer(steer)
    if steer:
        answer["layers"] = {k: {x: c[x] for x in ("hpa", "cover", "speed_kmh", "from")} for k, c in steer.items()}
        answer["main_layer"] = main

    # The nearest gaps, each followed by the cloud round it.
    answer["gaps"] = _gaps(pictures, now, ref, v, steer, main)

    # The movement: every pair of pictures 20 to 40 minutes apart, and the
    # median of them. 12 November 2026: one hour-long pair read 51 px east
    # while seven others read about 1 px a minute south; resting on that one
    # moved the arrival by three hours.
    m = _movement(pictures, cols=v.near)
    seen = None
    if m is None:
        answer["movement"] = None
    else:
        vx, vy, agree, total = m
        seen = (vx * kx * 60, -vy * ky * 60)
        answer["pairs_agreeing"] = f"{len(agree)} of {total}"
        answer["speed_kmh"] = round(float(math.hypot(*seen)))
        answer["moving_from"] = _from(seen)
        # Fewer than half the pairs agreeing is no movement to forecast from
        # (13 November 2026: 4 of 12 read as "from the N at about 0 km/h").
        if 2 * len(agree) < total:
            answer["movement_unsure"] = True
            seen = None
        elif steer:
            answer["seen_layer"] = _which_layer(seen, steer)
    use = _choose(seen, answer.get("seen_layer"), steer, main)
    if use is None:
        answer["lines"] = _approach_lines(answer)
        _note_gap(answer)
        return _keep_approach(answer)
    answer["by"] = use[1]
    if use[1] == "satellite":
        # rain.py borrows the movement; only the satellite's own is lent.
        answer["move_kmh"] = [round(float(seen[0]), 1), round(float(seen[1]), 1)]   # east, north
        moves = [(vx, vy)] + agree
    else:
        moves = [(use[0][0] / 60 / kx, -use[0][1] / 60 / ky)]          # pixels a minute
    from scipy.ndimage import label
    labels, count = label((now - ref) < CLEAR_MARGIN)
    sizes = np.bincount(labels.ravel())
    big = (sizes * kx * ky >= GAP_MIN_KM2)
    big[0] = False
    wide_clear = big[labels]          # a speck of clear sky upwind is not a gap coming (13 November 2026)

    def arrival(m):
        """(minutes until clear sky upstream reaches the site, minutes it lasts), None for either unknown."""
        start = None
        for minutes in range(0, (APPROACH_HOURS + LASTS_HOURS) * 60 + 1, 5):
            if start is None and minutes > APPROACH_HOURS * 60:
                break
            x, y = round(cx - m[0] * minutes), round(cy - m[1] * minutes)
            if not (0 <= x < v.width and 0 <= y < v.height):
                return start, None          # upstream runs off the map
            is_clear = bool(wide_clear[y, x])
            if start is None and is_clear:
                start = minutes
            elif start is not None and not is_clear:
                return start, minutes - start
        return start, None

    tries = [arrival(m) for m in moves] + [arrival((moves[0][0] * f, moves[0][1] * f)) for f in (0.75, 1.25)]
    starts = [s for s, _ in tries if s is not None]
    best, lasts = arrival(moves[0])
    answer["arrives_min"] = best
    answer["arrives_range_min"] = [min(starts), max(starts)] if starts else None
    answer["lasts_min"] = lasts
    answer["lines"] = _approach_lines(answer)
    if best is not None:
        speed, source = math.hypot(*use[0]), use[1]
        note_prediction("clear", answer["picture"], best, answer["arrives_range_min"], lasts,
                        speed_kmh=round(speed), moving_from=_from(use[0]), view=answer["view"], by=source)
    else:
        _note_gap(answer)
    return _keep_approach(answer)


def _note_gap(answer):
    """The first gap that reaches the site, kept as this picture's clear-sky
    prediction when the whole map's movement gave none."""
    for g in answer.get("gaps", []):
        if g.get("arrives_min") is not None:
            note_prediction("clear", answer["picture"], g["arrives_min"], g["arrives_range_min"], g["lasts_min"],
                            speed_kmh=g["speed_kmh"], moving_from=g["moving_from"], gap_km=g["km"],
                            gap_bearing=g["bearing"], view=answer.get("view"), by=g.get("by"))
            return


# Every prediction and every sight of the sky, kept so the predictions can
# be scored against what happened (--scores). 12 November 2026, the
# person: record the cloud predictions against reality for calibration.
PREDICTIONS = config.DATA / "cache" / "sky_predictions.jsonl"
SEEN = config.DATA / "cache" / "sky_seen.jsonl"
CLEAR_STARS = 20       # stars in a sky-check frame counted as clear here (skywatch's own mark is ENOUGH_STARS)


def _append(path, row):
    import json
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row) + "\n")
    except OSError:
        pass


def _at(picture, minutes):
    """The local clock time `minutes` after a picture taken at `picture` (ISO, with zone)."""
    import datetime as dt
    when = dt.datetime.fromisoformat(picture).astimezone() + dt.timedelta(minutes=minutes)
    return when


def note_prediction(kind, picture, minutes, span, lasts, **extra):
    """One prediction ("clear" or "rain") from one picture, kept once."""
    import json
    try:
        for line in PREDICTIONS.read_text(encoding="utf-8").splitlines()[-50:]:
            row = json.loads(line)
            if row.get("kind") == kind and row.get("picture") == picture and row.get("view") == extra.get("view"):
                return                       # this picture's prediction is already kept
    except (OSError, ValueError):
        pass
    _append(PREDICTIONS, {"t": time.time(), "kind": kind, "picture": picture,
                          "arrives": _at(picture, minutes).isoformat() if minutes is not None else None,
                          "range": [_at(picture, m).isoformat() for m in span] if span else None,
                          "lasts_min": lasts, **extra})


def note_seen(source, kind, yes, detail=""):
    """What was seen at the site: kind "clear" (stars) or "rain", yes or no."""
    _append(SEEN, {"t": time.time(), "source": source, "kind": kind, "yes": bool(yes), "detail": detail})


def score_lines(days=14):
    """Each prediction against the first sight of what it predicted, after the
    picture it came from: how early or late it was, and inside its range or not."""
    import datetime as dt
    import json

    def rows(path):
        try:
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError):
            return []
    since = time.time() - days * 86400
    seen = sorted((r for r in rows(SEEN) if r["t"] >= since), key=lambda r: r["t"])
    out, errors = [], []
    for p in (r for r in rows(PREDICTIONS) if r["t"] >= since):
        made = dt.datetime.fromisoformat(p["picture"]).timestamp()
        looks = [s for s in seen if s["kind"] == p["kind"] and made <= s["t"] <= made + APPROACH_HOURS * 3600]
        first = next((s for s in looks if s["yes"]), None)
        said = dt.datetime.fromisoformat(p["arrives"]).strftime("%H:%M") if p.get("arrives") else "none due"
        head = (f"{dt.datetime.fromisoformat(p['picture']).astimezone():%d %b %H:%M} {p['kind']}: "
                f"predicted {said}")
        if first is None:
            out.append(head + (f"; not seen in {len(looks)} looks" if looks else "; nothing watching"))
            continue
        got = dt.datetime.fromtimestamp(first["t"])
        if not p.get("arrives"):
            out.append(head + f"; seen {got:%H:%M} ({first['source']})")
            continue
        late = (first["t"] - dt.datetime.fromisoformat(p["arrives"]).timestamp()) / 60
        lo, hi = (dt.datetime.fromisoformat(v).timestamp() for v in p["range"])
        errors.append(late)
        out.append(head + f"; seen {got:%H:%M} ({first['source']}): {abs(late):.0f} min "
                   + ("late" if late > 0 else "early") + ("; inside its range" if lo <= first["t"] <= hi
                                                          else "; outside its range"))
    if errors:
        out.append(f"{len(errors)} scored: median error {float(np.median(errors)):+.0f} min "
                   f"(+ means it came later than predicted), median size {float(np.median(np.abs(errors))):.0f} min")
    return out or ["no predictions kept yet"]


def _keep_approach(answer):
    import json
    try:
        out = _approach_file(answer.get("view", APPROACH_VIEW))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(answer), encoding="utf-8")
    except OSError:
        pass
    return answer


def _layer_words(a, layer):
    c = a["layers"][layer]
    return f"the {layer} cloud's wind ({c['hpa']} hPa, from the {c['from']} at {c['speed_kmh']} km/h)"


def _seen_words(x, what):
    """What the satellite's own reading of `what` was, when it was not used."""
    if x.get("movement", True) is None:
        return f"{what} could not be measured"
    if x.get("unsure") or x.get("movement_unsure"):
        return f"{what} unsure ({x.get('pairs_agreeing')} pairs agreeing)"
    reading = f"{what} read from the {x['moving_from']} at {x['speed_kmh']} km/h ({x.get('pairs_agreeing')} agreeing)"
    if x.get("seen_layer"):
        return f"{reading}, the {x['seen_layer']} cloud's wind"
    if x["speed_kmh"] < SLOW_KMH:
        return f"{reading}: still, as the land and sea are"
    return f"{reading}, no layer's wind"


def _gap_lines(a, clock):
    """One line for each of the nearest gaps: where it is, how it moves, and
    whether and when it gets here."""
    out = []
    for g in a.get("gaps", []):
        head = f"gap {g['km']} km {g['bearing']} (about {g['area_km2']:.0f} km\u00b2)"
        if g.get("by") is None:
            out.append(f"{head}: {_seen_words(g, 'its movement')}; no wind to carry it by")
            continue
        if g["by"] == "satellite":
            moving = (f"moving from the {g['moving_from']} at about {g['speed_kmh']} km/h ({g['pairs_agreeing']} "
                      "pairs agreeing" + (f", the {g['seen_layer']} cloud's wind" if g.get("seen_layer") else "") + ")")
        else:
            moving = f"carried by {_layer_words(a, g['by'])}; {_seen_words(g, 'the satellite')}"
        if g.get("arrives_min") == 0:
            out.append(f"{head}: {moving}; its edge is at the site now")
        elif g.get("arrives_min") is not None:
            lo, hi = g["arrives_range_min"]
            out.append(f"{head}: {moving}; reaches here about {clock(g['arrives_min'])} (range {clock(lo)}-"
                       f"{clock(hi)})" + (f", over us about {g['lasts_min']} min" if g.get("lasts_min") else ""))
        elif g.get("closest_min"):
            out.append(f"{head}: {moving}; misses us, closest {g['closest_km']} km about {clock(g['closest_min'])}")
        else:
            out.append(f"{head}: {moving}; moving away")
    return out


def _approach_lines(a):
    if a.get("error"):
        return [f"cloud approach: {a['error']}"]
    # From the picture's time, not now: a kept answer read later says the same clock time.
    clock = lambda minutes: _at(a["picture"], minutes).strftime("%H:%M")  # noqa: E731
    reach = f" ({a['view']} view, out to {a['map_km'][0]} km west)" if a.get("map_km") else ""
    out = [f"satellite picture {a['picture'][11:16]} UT{reach}: {a['here']} over the site"]
    if a.get("layers"):
        main = a.get("main_layer")
        out.append("model's cloud: " + ", ".join(f"{k} {c['cover']}%" for k, c in a["layers"].items())
                   + (f"; the {main} cloud is the one to watch, moving with {_layer_words(a, main)}" if main else
                      "; no layer above 30%, so the satellite's own movement is used"))
    else:
        out.append("model's cloud layers: none to be had, so the satellite's movement is not checked")
    if a.get("nearest_clear_km") is not None:
        out.append(f"nearest clear sky: {a['nearest_clear_km']} km {a['nearest_clear_bearing']}")
    else:
        west, east, span = a.get("map_km", (236, 236, 189))
        out.append(f"no clear sky anywhere on the map ({west} km west, {east} km east, {span} km north and south)")
    out += _gap_lines(a, clock)
    missing = f"; {a['pictures_missing']} pictures would not come" if a.get("pictures_missing") else ""
    if a.get("by") is None:
        out.append(f"{_seen_words(a, 'the whole map').capitalize()}{missing}; no wind to carry clear sky by")
        out.append("a guide: clouds grow and melt as they move")
        return out
    if a["by"] == "satellite":
        out.append(f"cloud moving from the {a['moving_from']} at about {a['speed_kmh']} km/h (last hour's pictures, "
                   f"{a.get('pairs_agreeing', '?')} pairs agreeing{missing}"
                   + (f", the {a['seen_layer']} cloud's wind" if a.get("seen_layer") else "") + ")")
    else:
        out.append(f"clear sky upwind carried by {_layer_words(a, a['by'])}: {_seen_words(a, 'the whole map')}"
                   f"{missing}")
    if a.get("arrives_min") == 0:
        out.append("clear sky is over the site now by the satellite"
                   + (f", for about {a['lasts_min']} min more at this speed" if a.get("lasts_min") else ""))
    elif a.get("arrives_min") is not None:
        lo, hi = a["arrives_range_min"]
        out.append(f"clear sky upwind reaches here about {clock(a['arrives_min'])} ({a['arrives_min']} min after the picture; "
                   f"range {clock(lo)}-{clock(hi)})"
                   + (f", lasting about {a['lasts_min']} min" if a.get("lasts_min") else ", its end not on the map"))
    else:
        out.append(f"no clear sky upwind within {APPROACH_HOURS} h at this speed"
                   + (": the clear area is not on the cloud's track" if a.get("nearest_clear_km") is not None else ""))
    out.append("a guide: clouds grow and melt as they move")
    return out


if __name__ == "__main__":
    import argparse
    import datetime as dt
    ap = argparse.ArgumentParser(description="The sky's evidence: Meteosat and the airports.")
    ap.add_argument("--at", metavar="YYYY-MM-DDTHH:MM", help="a past time, UT: the satellite's picture then")
    ap.add_argument("--airports", action="store_true", help="only the airports' cloud reports")
    ap.add_argument("--history", type=float, metavar="HOURS", nargs="?", const=24,
                    help="the looks kept in the last HOURS (24), with what the camera measured")
    ap.add_argument("--approach", action="store_true",
                    help="the nearest clear sky, the cloud's movement, and when clear sky gets here")
    ap.add_argument("--fresh", type=float, default=0, metavar="SECONDS",
                    help="with --approach: reuse an answer this new instead of fetching again")
    ap.add_argument("--scores", type=float, nargs="?", const=14, metavar="DAYS",
                    help="the clear-sky and rain predictions kept in the last DAYS (14), against what was seen")
    ap.add_argument("--view", choices=list(VIEWS), help="close (about 240 km each way, the run's own), medium "
                    "(out to about 630 km west, --approach's) or wide (the Atlantic to 20 degrees W, half the detail); "
                    "with no option the picture is saved as clouds-VIEW.jpg")
    args = ap.parse_args()
    if args.scores:
        print("\n".join(score_lines(args.scores)))
        raise SystemExit
    if args.approach:
        print("\n".join(approach(fresh_s=args.fresh, view=args.view or APPROACH_VIEW)["lines"]))
        raise SystemExit
    if args.history:
        print("\n".join(history_lines(args.history)))
        raise SystemExit
    if args.airports:
        print("\n".join(airport_lines(config.load()["site"])))
        raise SystemExit
    if args.at:
        when = dt.datetime.fromisoformat(args.at).replace(tzinfo=dt.timezone.utc)
        try:
            here, clear, saved = update(config.load()["site"], when, view=args.view or "close")
        except (RuntimeError, requests.RequestException) as problem:
            raise SystemExit(f"No satellite picture: {problem}. Try again in a few minutes.")
        print(f"over the site: {here:.0f}, clear areas: {clear:.0f} -> {verdict(here, clear)}")
        raise SystemExit(f"saved {saved}")
    if args.view and args.view != "close":
        here, clear, saved = update(config.load()["site"], view=args.view)
        print(f"{args.view} view: {verdict(here, clear)} over the site; saved {saved}")
        raise SystemExit
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