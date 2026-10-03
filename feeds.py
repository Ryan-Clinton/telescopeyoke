"""Network data for tonight.py: weather, seeing, light pollution and comets.

Every fetch returns None on failure, so the report degrades instead of dying
when the laptop is out of Wi-Fi range.
"""
import gzip
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

CACHE = Path(__file__).parent / "cache"
TIMEOUT = 25
HEADERS = {"User-Agent": "telescopeyoke/0.1 (personal observing planner)"}


def _cached(key, max_age_h, fetch):
    """Return fetch()'s JSON-able result, reusing a recent copy from disk."""
    path = CACHE / f"{key}.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_h * 3600:
        return json.loads(path.read_text())
    try:
        value = fetch()
    except (requests.RequestException, ValueError, KeyError, OSError):
        # A stale copy beats nothing.
        return json.loads(path.read_text()) if path.exists() else None
    if value is not None:
        CACHE.mkdir(exist_ok=True)
        path.write_text(json.dumps(value))
    return value


def _get(url, **params):
    r = requests.get(url, params=params, timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    return r


# --- Weather: Open-Meteo (https://open-meteo.com, free, no key) -------------

WEATHER_VARS = (
    "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,"
    "precipitation,precipitation_probability,temperature_2m,dew_point_2m,"
    "relative_humidity_2m,wind_speed_10m,wind_gusts_10m"
)


def weather(lat, lon):
    """Hourly forecast as a dict of lists; 'time' is unix seconds (UTC)."""
    def fetch():
        return _get(
            "https://api.open-meteo.com/v1/forecast",
            latitude=lat, longitude=lon, hourly=WEATHER_VARS,
            forecast_days=3, past_days=1, timeformat="unixtime", timezone="UTC",
        ).json()["hourly"]
    return _cached(f"weather_{lat:.3f}_{lon:.3f}", 0.5, fetch)


# --- Seeing and transparency: 7Timer ASTRO (https://www.7timer.info) --------

SEEING = {1: '<0.5"', 2: '0.5-0.75"', 3: '0.75-1"', 4: '1-1.25"',
          5: '1.25-1.5"', 6: '1.5-2"', 7: '2-2.5"', 8: '>2.5"'}
# Extinction in magnitudes per air mass.
TRANSPARENCY = {1: "<0.3", 2: "0.3-0.4", 3: "0.4-0.5", 4: "0.5-0.6",
                5: "0.6-0.7", 6: "0.7-0.85", 7: "0.85-1", 8: ">1"}


def seeing(lat, lon):
    """3-hourly list of {time (unix), seeing, transparency} with codes 1-8,
    where 1 is best."""
    def fetch():
        d = _get("https://www.7timer.info/bin/astro.php", lon=lon, lat=lat,
                 ac=0, unit="metric", output="json", tzshift=0).json()
        init = datetime.strptime(d["init"], "%Y%m%d%H").replace(tzinfo=timezone.utc)
        return [
            {"time": init.timestamp() + p["timepoint"] * 3600,
             "seeing": p["seeing"], "transparency": p["transparency"]}
            for p in d["dataseries"]
        ]
    return _cached(f"seeing_{lat:.3f}_{lon:.3f}", 3, fetch)


# --- Light pollution: David Lorenz's atlas ----------------------------------
# https://djlorenz.github.io/astronomy/lp/ - modelled from VIIRS satellite
# data. The decoding below mirrors the atlas's own overlay map.

NATURAL_SKY = 22.0  # mag/arcsec², the atlas's unpolluted reference
ATLAS_YEAR = 2025
ZONES = [(0.01, "0"), (0.06, "1a"), (0.11, "1b"), (0.19, "2a"), (0.33, "2b"),
         (0.58, "3a"), (1.00, "3b"), (1.73, "4a"), (3.00, "4b"), (5.20, "5a"),
         (9.00, "5b"), (15.59, "6a"), (27.00, "6b"), (46.77, "7a")]
# Rough Bortle class by zenith brightness; Bortle is a visual scale, so this
# is only an indication.
BORTLE = [(21.99, 1), (21.89, 2), (21.69, 3), (20.49, 4), (19.50, 5),
          (18.94, 6), (18.38, 7)]


def bortle(sqm):
    return next((b for limit, b in BORTLE if sqm >= limit), 8)


def light_pollution(lat, lon):
    """{'ratio': artificial/natural brightness, 'sqm', 'zone', 'bortle'} at
    the zenith on a moonless night, or None."""
    def fetch():
        lon_from_dateline = (lon + 180.0) % 360.0
        lat_from_start = lat + 65.0
        tx = int(lon_from_dateline // 5) + 1
        ty = int(lat_from_start // 5) + 1
        if not 1 <= ty <= 28:
            return None
        raw = gzip.decompress(_get(
            "https://djlorenz.github.io/astronomy/binary_tiles/"
            f"{ATLAS_YEAR}/binary_tile_{tx}_{ty}.dat.gz").content)
        # 600x600 grid at 1/120°: a 2-byte value for the corner, then 1-byte
        # deltas, down the first column and along each row.
        d = np.frombuffer(raw, dtype=np.int8).astype(int)
        ix = round(120 * (lon_from_dateline - 5 * (tx - 1) + 1 / 240))
        iy = round(120 * (lat_from_start - 5 * (ty - 1) + 1 / 240))
        value = 128 * d[0] + d[1]
        value += sum(d[600 * i + 1] for i in range(1, iy))
        value += sum(d[600 * (iy - 1) + 1 + i] for i in range(1, ix))
        ratio = (5.0 / 195.0) * (math.exp(0.0195 * value) - 1.0)
        sqm = NATURAL_SKY - 2.5 * math.log10(1.0 + ratio)
        return {
            "ratio": round(ratio, 3), "sqm": round(sqm, 2),
            "zone": next((z for limit, z in ZONES if ratio < limit), "7b"),
            "bortle": bortle(sqm), "source": f"Lorenz atlas {ATLAS_YEAR}",
        }
    return _cached(f"lightpollution_{lat:.4f}_{lon:.4f}", 24 * 90, fetch)


# --- Comets: COBS for what is bright, JPL Horizons for where it is ----------

COMET_MAG_LIMIT = 11
MAX_COMETS = 6


def _horizons_track(designation, lat, lon, elevation_m, start, stop):
    """RA/Dec (degrees) every 30 minutes between two UTC datetimes."""
    fmt = "%Y-%m-%d %H:%M"
    result = _get(
        "https://ssd.jpl.nasa.gov/api/horizons.api",
        format="json", COMMAND=f"'DES={designation};CAP;NOFRAG'",
        OBJ_DATA="'NO'", MAKE_EPHEM="'YES'", EPHEM_TYPE="'OBSERVER'",
        CENTER="'coord@399'",
        SITE_COORD=f"'{lon:.5f},{lat:.5f},{elevation_m / 1000:.3f}'",
        START_TIME=f"'{start.strftime(fmt)}'", STOP_TIME=f"'{stop.strftime(fmt)}'",
        STEP_SIZE="'30 m'", QUANTITIES="'1'", CSV_FORMAT="'YES'",
        ANG_FORMAT="'DEG'",
    ).json()["result"]
    body = result.split("$$SOE")[1].split("$$EOE")[0]
    track = []
    for line in body.strip().splitlines():
        cols = [c.strip() for c in line.split(",")]
        when = datetime.strptime(cols[0], "%Y-%b-%d %H:%M").replace(tzinfo=timezone.utc)
        track.append([when.timestamp(), float(cols[3]), float(cols[4])])
    return track


def comets(lat, lon, elevation_m, start, stop):
    """Comets currently brighter than COMET_MAG_LIMIT, each with a 'track' of
    [unix, ra_deg, dec_deg] rows covering start..stop (UTC datetimes)."""
    def fetch():
        listed = _get("https://cobs.si/api/comet_list.api",
                      **{"is-observed": "true", "cur-mag": COMET_MAG_LIMIT + 1,
                         "page": 1}).json()["objects"]
        out = []
        for c in listed:
            try:
                mag = float(c["current_mag"])
                perihelion = datetime.strptime(
                    c["perihelion_date"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            # COBS keeps the last estimate for comets long past perihelion;
            # only trust magnitudes from the current apparition.
            if mag > COMET_MAG_LIMIT or abs((perihelion - start).days) > 400:
                continue
            out.append({"id": c["name"], "name": c["fullname"], "mag": mag})
        out = sorted(out, key=lambda c: c["mag"])[:MAX_COMETS]
        for c in out:
            c["track"] = _horizons_track(c["id"], lat, lon, elevation_m, start, stop)
        return out
    key = f"comets_{lat:.3f}_{lon:.3f}_{start:%Y%m%d}"
    return _cached(key, 12, fetch)
