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
                       cloud moves (the last hour's three pictures), and when
                       clear sky upwind gets here, with a range; run by
                       .claude/hooks/sky.py whenever the person talks about
                       the sky
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


def _box(site):
    lat, lon = site["latitude"], site["longitude"]
    return (lat - SPAN_LAT, lon - SPAN_LON, lat + SPAN_LAT, lon + SPAN_LON)


def update(site, when=None, timeout=60, save="auto"):
    """Fetch, annotate and save the image. Returns (brightness over the site,
    brightness of the darkest tenth of the map), both 0-255; the second is a
    stand-in for clear sky. `when` (UTC) is a past picture, saved under its
    own name so the page's live one is left alone: 5 November 2026, dimmed
    stars were put down to dew without a look at the satellite."""
    lat = site["latitude"]
    box = _box(site)
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


APPROACH = config.DATA / "cache" / "cloud_approach.json"
STEP_MIN = 10              # the satellite's pictures come every 10 minutes
PICTURES = 7               # the last hour's: the cloud's movement is measured between pairs of them
APPROACH_MAX_PX = 60       # the most a picture's cloud may move between two of them (about 25-45 km)
APPROACH_HOURS = 6         # how far ahead an arrival is looked for
CLEAR_MARGIN, BROKEN_MARGIN = 10, 20   # as verdict(): brightness over the clear tenth


def _levels(site, when, timeout=30, tries=3):
    """One past picture as grey levels, tried again after a pause when the
    service is slow: 12 November 2026, 23:07-23:15, view.eumetsat.int
    answered its front page at once but gave 504s and read timeouts on
    pictures, and one picture asked alone came back in 6 s."""
    for attempt in range(tries):
        try:
            return np.asarray(_layer("mtg_fd:ir105_hrfi", _box(site), when=when, timeout=timeout).convert("L"), float)
        except (RuntimeError, requests.RequestException, OSError):
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))


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
    return float(dx[peak]), float(dy[peak])


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


def approach(site=None, fresh_s=0):
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
            kept = json.loads(APPROACH.read_text(encoding="utf-8"))
            if time.time() - kept["t"] < fresh_s:
                return kept
        except (OSError, ValueError, KeyError):
            pass
    site = site or config.load()["site"]
    taken = picture_time()
    if taken is None:
        return _failed("the satellite service would not say when its newest picture was taken", site)
    times = [taken - dt.timedelta(minutes=STEP_MIN * k) for k in range(PICTURES - 1, -1, -1)]
    try:
        with concurrent.futures.ThreadPoolExecutor(2) as pool:      # gently: the service struggles with more
            pictures = list(pool.map(lambda when: _levels(site, when), times))
    except (RuntimeError, requests.RequestException, OSError) as problem:
        return _failed(f"no satellite pictures: {problem}", site)
    lat = site["latitude"]
    kx = 111.32 * math.cos(math.radians(lat)) * 2 * SPAN_LON / WIDTH     # km a pixel, east-west
    ky = 111.32 * 2 * SPAN_LAT / HEIGHT                                   # km a pixel, north-south
    now = uniform_filter(pictures[-1], 9)
    ref = float(np.percentile(pictures[-1], 10))
    cx, cy = WIDTH // 2, HEIGHT // 2
    answer = {"t": time.time(), "picture": taken.isoformat(), "here": verdict(float(now[cy, cx]), ref)}

    # The nearest clear area now, any direction.
    clear = (now - ref) < CLEAR_MARGIN
    ys, xs = np.nonzero(clear)
    if len(xs):
        east, north = (xs - cx) * kx, (cy - ys) * ky
        dist = np.hypot(east, north)
        i = int(np.argmin(dist))
        answer["nearest_clear_km"] = round(float(dist[i]))
        answer["nearest_clear_bearing"] = _compass(math.degrees(math.atan2(east[i], north[i])) % 360)

    # The movement: every pair of pictures 20 to 40 minutes apart, and the
    # median of them. 12 November 2026: one hour-long pair read 51 px east
    # while seven others read about 1 px a minute south; resting on that one
    # moved the arrival by three hours.
    moves = []
    for a in range(PICTURES):
        for b in range(a + 1, PICTURES):
            minutes = (b - a) * STEP_MIN
            if 20 <= minutes <= 40:
                s = _shift(pictures[a], pictures[b])
                if s:
                    moves.append((s[0] / minutes, s[1] / minutes))       # pixels a minute
    if len(moves) < 3:
        answer["movement"] = None
        answer["lines"] = _approach_lines(answer)
        return _keep_approach(answer)
    vx, vy = float(np.median([m[0] for m in moves])), float(np.median([m[1] for m in moves]))
    agree = [m for m in moves if math.hypot(m[0] - vx, m[1] - vy) <= 0.5 * max(math.hypot(vx, vy), 0.2)]
    answer["pairs_agreeing"] = f"{len(agree)} of {len(moves)}"
    moves = [(vx, vy)] + agree
    east_kmh, north_kmh = vx * kx * 60, -vy * ky * 60
    answer["move_kmh"] = [round(float(east_kmh), 1), round(float(north_kmh), 1)]   # east, north
    answer["speed_kmh"] = round(float(math.hypot(east_kmh, north_kmh)))
    answer["moving_from"] = _compass((math.degrees(math.atan2(east_kmh, north_kmh)) + 180) % 360)

    def arrival(v):
        """(minutes until clear sky upstream reaches the site, minutes it lasts), None for either unknown."""
        start = None
        for minutes in range(0, APPROACH_HOURS * 60 + 1, 5):
            x, y = round(cx - v[0] * minutes), round(cy - v[1] * minutes)
            if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
                return start, None          # upstream runs off the map
            is_clear = (now[y, x] - ref) < CLEAR_MARGIN
            if start is None and is_clear:
                start = minutes
            elif start is not None and not is_clear:
                return start, minutes - start
        return start, None

    tries = [arrival(v) for v in moves] + [arrival((moves[0][0] * f, moves[0][1] * f)) for f in (0.75, 1.25)]
    starts = [s for s, _ in tries if s is not None]
    best, lasts = arrival(moves[0])
    answer["arrives_min"] = best
    answer["arrives_range_min"] = [min(starts), max(starts)] if starts else None
    answer["lasts_min"] = lasts
    answer["lines"] = _approach_lines(answer)
    note_prediction("clear", answer["picture"], best, answer["arrives_range_min"], lasts,
                    speed_kmh=answer["speed_kmh"], moving_from=answer["moving_from"])
    return _keep_approach(answer)


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
            if row.get("kind") == kind and row.get("picture") == picture:
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
        APPROACH.parent.mkdir(parents=True, exist_ok=True)
        APPROACH.write_text(json.dumps(answer), encoding="utf-8")
    except OSError:
        pass
    return answer


def _approach_lines(a):
    if a.get("error"):
        return [f"cloud approach: {a['error']}"]
    # From the picture's time, not now: a kept answer read later says the same clock time.
    clock = lambda minutes: _at(a["picture"], minutes).strftime("%H:%M")  # noqa: E731
    out = [f"satellite picture {a['picture'][11:16]} UT: {a['here']} over the site"]
    if a.get("nearest_clear_km") is not None:
        out.append(f"nearest clear sky: {a['nearest_clear_km']} km {a['nearest_clear_bearing']}")
    else:
        out.append(f"no clear sky anywhere on the map (about {2 * SPAN_LAT * 111:.0f} x "
                   f"{2 * SPAN_LON * 111 * math.cos(math.radians(55)):.0f} km)")
    if a.get("movement", True) is None:
        out.append("the cloud's movement could not be measured from the last hour's pictures")
        return out
    out.append(f"cloud moving from the {a['moving_from']} at about {a['speed_kmh']} km/h (last hour's pictures, "
               f"{a.get('pairs_agreeing', '?')} pairs agreeing)")
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
    args = ap.parse_args()
    if args.scores:
        print("\n".join(score_lines(args.scores)))
        raise SystemExit
    if args.approach:
        print("\n".join(approach(fresh_s=args.fresh)["lines"]))
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