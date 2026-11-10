#!/usr/bin/env python3
"""Live cloud picture from the Meteosat weather satellite.

    ./clouds.py        fetch the newest infrared image, mark the site on it,
                       save it for the web page and print how cloudy it looks
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
    """When the newest infrared picture was taken (UTC), from the service's
    own list, or None if it would not say."""
    import datetime as dt
    import re
    try:
        r = requests.get("https://view.eumetsat.int/geoserver/mtg_fd/ir105_hrfi/ows", timeout=timeout,
                         params={"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"})
        found = re.search(r'<Dimension name="time" default="([^"]+)"', r.text)
        return dt.datetime.fromisoformat(found.group(1).replace("Z", "+00:00")) if found else None
    except (requests.RequestException, ValueError):
        return None


def update(site, when=None, timeout=60):
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
    out = PICTURE.with_name(f"clouds-{when:%Y%m%d-%H%M}.jpg") if when else PICTURE
    out.parent.mkdir(exist_ok=True)
    infrared.resize((WIDTH, true_height)).save(out, quality=88)
    return here, clear, out


def verdict(here, clear):
    """The satellite's word on the site: "cloud", "thin or broken cloud" or "probably clear"."""
    return "cloud" if here - clear > 20 else "probably clear" if here - clear < 10 else "thin or broken cloud"


def over_site():
    """The satellite's verdict on the site now (the page's picture updated
    too), or None if no picture came."""
    try:
        here, clear, _ = update(config.load()["site"])
    except (RuntimeError, requests.RequestException, OSError):
        return None
    return verdict(here, clear)


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
    return km, _compass(deg)


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
        km, way = _distance(lat, lon, m["lat"], m["lon"])
        if km > radius_km:
            continue
        layers = [f"{COVER.get(c['cover'], c['cover'])} at {c['base']} ft" if c.get("base") is not None
                  else COVER.get(c["cover"], c["cover"]) for c in m.get("clouds") or []]
        wind = None
        if m.get("wspd") is not None:
            wind = ("calm" if not m["wspd"] else f"{m['wspd']} kt from "
                    + (_compass(m["wdir"]) if isinstance(m.get("wdir"), (int, float)) else "varying directions"))
        out.append({"id": m["icaoId"], "name": m["name"].split(",")[0], "km": round(km), "from": way,
                    "covers": [c["cover"] for c in m.get("clouds") or []], "wind": wind,
                    "age_min": round((time.time() - m["obsTime"]) / 60), "layers": layers,
                    "says": "; ".join(layers) or SAYS.get(m.get("cover"), m.get("cover") or "no cloud given"),
                    "temp_c": m.get("temp"), "dew_c": m.get("dewp"), "raw": m["rawOb"]})
    return sorted(out, key=lambda a: a["km"])


def airport_lines(site):
    """The airports' reports as lines to print, or one line saying none came."""
    try:
        found = airports(site)
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
FRESH_S = 300          # one look at the sky's evidence serves every script for 5 minutes
SATELLITE_STALE_MIN = 40


def evidence(max_age_s=FRESH_S):
    """One look at the sky's evidence, shared by shoot.py, runwatch.py and
    skywatch.py through a file kept for 5 minutes, fetched with short
    timeouts so a slow service holds nothing up for long: the satellite's
    verdict over the site and its picture's age, the airports' fresh
    reports (75 minutes or less) and what the two together say."""
    import json
    try:
        kept = json.loads(EVIDENCE.read_text())
        if time.time() - kept["at"] < max_age_s:
            return kept
    except (OSError, ValueError, KeyError):
        pass
    site = config.load()["site"]
    taken = picture_time()
    age = None if taken is None else round((time.time() - taken.timestamp()) / 60)
    try:
        here, clear, _ = update(site, timeout=15)
        seen = verdict(here, clear)
    except (RuntimeError, requests.RequestException, OSError):
        seen = None
    stale = seen is not None and age is not None and age > SATELLITE_STALE_MIN
    try:
        near = [a for a in airports(site, timeout=8) if a["age_min"] <= 75]
    except (requests.RequestException, ValueError):
        near = None
    out = {"at": time.time(), "satellite": None if stale else seen, "satellite_age_min": age,
           "satellite_stale": stale, "airports": near, "together": together(None if stale else seen, near)}
    try:
        EVIDENCE.parent.mkdir(exist_ok=True)
        EVIDENCE.write_text(json.dumps(out))
    except OSError:
        pass
    return out


def together(seen, near):
    """What the satellite and the airports within 80 km say between them.
    Unknown is never clear; and clear on both still leaves thin high cloud,
    which neither sees well, as well as dew or a fault."""
    close = [a for a in near or [] if a["km"] <= 80]
    low = [a for a in close if set(a["covers"]) & {"BKN", "OVC", "VV"}]
    if seen is None and not close:
        return "no satellite picture and no airport near: the sky is unknown, not clear"
    if seen is None:
        return "no satellite picture; " + ("the airports near have low cloud" if low else
                                           "the airports near have no low cloud, which says nothing of high cloud")
    cloudy = seen in ("cloud", "thin or broken cloud")
    if cloudy and low:
        return "the satellite and the airports agree: cloud"
    if cloudy:
        return ("the satellite sees cloud and the airports near have none low: high cloud, "
                "which their ceilometers don't reach" if close else "the satellite sees cloud; no airport near to check it")
    if low:
        return "they disagree: low cloud at the airports near, none on the satellite here: look up"
    return ("neither sees cloud here: thin high cloud is still possible, or dew, or a fault; look up"
            if close else "the satellite sees no cloud; no airport near to check it; thin cloud is still possible")


def evidence_words(found=None):
    """The evidence as one line for a message about dimmed or missing stars."""
    found = found or evidence()
    sat = found["satellite"] or ("only a stale picture" if found.get("satellite_stale") else "no picture")
    if found["satellite"] and found.get("satellite_age_min") is not None:
        sat += f" ({found['satellite_age_min']} min old)"
    near = "; ".join(f"{a['name'].split('/')[0]} {a['km']} km {a['from']} {a['says']}"
                     + (f", wind {a['wind']}" if a["wind"] else "") for a in found["airports"] or [])
    return f"satellite: {sat} over the site" + (f"; airports: {near}" if near else "") + f". {found['together']}"


if __name__ == "__main__":
    import argparse
    import datetime as dt
    ap = argparse.ArgumentParser(description="Live (or past) cloud picture from Meteosat.")
    ap.add_argument("--at", metavar="YYYY-MM-DDTHH:MM", help="a past time, UT")
    ap.add_argument("--airports", action="store_true", help="only the airports' cloud reports")
    args = ap.parse_args()
    if args.airports:
        print("\n".join(airport_lines(config.load()["site"])))
        raise SystemExit
    when = dt.datetime.fromisoformat(args.at).replace(tzinfo=dt.timezone.utc) if args.at else None
    try:
        here, clear, saved = update(config.load()["site"], when)
    except (RuntimeError, requests.RequestException) as problem:
        raise SystemExit(f"No satellite picture: {problem}. Try again in a few minutes.")
    print(f"over the site: {here:.0f}, clear areas: {clear:.0f} -> {verdict(here, clear)}")
    print(f"saved {saved}")
    if not when:
        print("\n".join(airport_lines(config.load()["site"])))
