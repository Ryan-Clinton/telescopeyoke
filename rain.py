#!/usr/bin/env python3
"""Rain on the radar: where the nearest is, and when it gets here.

    ./rain.py                 the nearest rain, its movement, and when (and for
                              how long) rain upwind reaches the site
    ./rain.py --json
    ./rain.py --watch --every 15 --until 06:00 --flash "Living room"
                              look every 15 minutes; a line (and the room's
                              lights pulsed blue) only when rain is due within
                              WARN_MIN, starts, or clears again

The radar is RainViewer's public composite (api.rainviewer.com: the national
radars, the Met Office's here, a picture every 10 minutes, the last two
hours, no forecast). A 3 x 3 block of zoom-7 tiles round the site covers
about 250 km each way at 0.7 km a pixel. The rain's movement is measured
between the last hour's radar pictures as the clouds' is (clouds._shift);
with too little rain on the map to measure, the cloud's movement from the
satellite (clouds.approach) is used and said.

The tiles asked for are ~180 km squares, so the request says the region,
not the place.

12 November 2026: a shower at about 23:50 had the scope bagged in a hurry;
the person asked for a warning, and whether it is a quick shower or the
night's end.
"""
import argparse
import io
import json
import math
import time
from datetime import datetime, timedelta

import numpy as np
import requests
from PIL import Image

import config
import interface

API = "https://api.rainviewer.com/public/weather-maps.json"
ZOOM = 7                 # the deepest the public tiles go
TILES = 1                # tiles each side of the site's: a 3 x 3 block
NEAR_KM = 5              # rain this close to a point on the track counts as there
WARN_MIN = 45            # rain due within this: a warning
SHOWER_MIN = 30          # rain lasting no more than this on the track: a shower
AHEAD_H = 4
STATE = config.DATA / "cache" / "rain.json"


def _pixel(lat, lon):
    n = 2 ** ZOOM * 256
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _frame(host, path, x0, y0):
    """The 3 x 3 tiles of one radar picture, as rain (True) or not."""
    size = 256 * (2 * TILES + 1)
    rain = np.zeros((size, size), bool)
    for j in range(-TILES, TILES + 1):
        for i in range(-TILES, TILES + 1):
            r = requests.get(f"{host}{path}/256/{ZOOM}/{x0 + i}/{y0 + j}/0/0_0.png", timeout=15)
            r.raise_for_status()
            alpha = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))[..., 3]
            rain[(j + TILES) * 256:(j + TILES + 1) * 256, (i + TILES) * 256:(i + TILES + 1) * 256] = alpha > 0
    return rain


def look(site=None):
    import concurrent.futures

    import clouds
    from scipy.ndimage import binary_dilation
    site = site or config.load()["site"]
    lat, lon = site["latitude"], site["longitude"]
    maps = requests.get(API, timeout=15).json()
    past = maps["radar"]["past"]
    if not past:
        return {"error": "the radar service has no pictures just now"}
    gx, gy = _pixel(lat, lon)
    x0, y0 = int(gx // 256), int(gy // 256)
    sx, sy = gx - (x0 - TILES) * 256, gy - (y0 - TILES) * 256        # the site in the block, pixels
    km = 40075.0 * math.cos(math.radians(lat)) / (2 ** ZOOM * 256)   # km a pixel, both ways (Mercator)
    chosen = [past[-7], past[-4], past[-1]] if len(past) >= 7 else [past[0], past[-1]]
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        frames = list(pool.map(lambda f: _frame(maps["host"], f["path"], x0, y0), chosen))
    now = frames[-1]
    taken = datetime.fromtimestamp(chosen[-1]["time"])
    answer = {"picture": taken.strftime("%H:%M"), "rain_here": bool(now[int(sy), int(sx)])}

    ys, xs = np.nonzero(now)
    if len(xs):
        east, north = (xs - sx) * km, (sy - ys) * km
        dist = np.hypot(east, north)
        i = int(np.argmin(dist))
        answer["nearest_km"] = round(float(dist[i]))
        answer["nearest_bearing"] = clouds._compass(math.degrees(math.atan2(east[i], north[i])) % 360)
        answer["rain_share"] = round(float(now.mean()), 3)
    else:
        answer["nearest_km"] = None

    # The movement: the rain's own, or the cloud's from the satellite.
    move, source = None, None
    if len(frames) == 3 and frames[0].sum() > 200 and now.sum() > 200:
        minutes = (chosen[-1]["time"] - chosen[0]["time"]) / 60
        s = clouds._shift(frames[0].astype(float), now.astype(float))
        if s:
            move, source = (s[0] * km / minutes * 60, -s[1] * km / minutes * 60), "the rain's own movement"
    if move is None:
        cloud = clouds.approach(site, fresh_s=900)
        if cloud.get("move_kmh"):
            move, source = tuple(cloud["move_kmh"]), "the cloud's movement on the satellite"
    answer["movement_from"] = source
    if move is None or answer["nearest_km"] is None:
        answer["arrives_min"] = 0 if answer["rain_here"] else None
        answer["lines"] = lines(answer)
        return answer
    answer["speed_kmh"] = round(math.hypot(*move))
    answer["moving_from"] = clouds._compass((math.degrees(math.atan2(move[0], move[1])) + 180) % 360)

    near = binary_dilation(now, iterations=max(1, round(NEAR_KM / km)))
    size = now.shape[0]

    def along(m):
        """(minutes until rain upwind reaches the site, minutes it lasts on the track)."""
        start = None
        for minutes in range(0, AHEAD_H * 60 + 1, 5):
            x = round(sx - m[0] / km * minutes / 60)
            y = round(sy + m[1] / km * minutes / 60)
            if not (0 <= x < size and 0 <= y < size):
                return start, None
            wet = bool(near[y, x])
            if start is None and wet:
                start = minutes
            elif start is not None and not wet:
                return start, minutes - start
        return start, None

    best, lasts = along(move)
    others = [along((move[0] * f, move[1] * f))[0] for f in (0.75, 1.25)]
    starts = [s for s in [best] + others if s is not None]
    answer.update(arrives_min=best, lasts_min=lasts,
                  arrives_range_min=[min(starts), max(starts)] if starts else None)
    answer["lines"] = lines(answer)
    return answer


def kind(lasts):
    if lasts is None:
        return "its end beyond the radar's reach: more than a shower, maybe the night's end"
    return f"a shower, about {lasts} min" if lasts <= SHOWER_MIN else f"lasting about {lasts} min"


def lines(a):
    if a.get("error"):
        return [f"rain: {a['error']}"]
    clock = lambda m: (datetime.now() + timedelta(minutes=m)).strftime("%H:%M")  # noqa: E731
    out = [f"radar {a['picture']}: " + ("RAIN OVER THE SITE" if a["rain_here"] else "no rain over the site")]
    if a["nearest_km"] is None:
        out.append("no rain within about 250 km")
        return out
    out.append(f"nearest rain {a['nearest_km']} km {a['nearest_bearing']}")
    if a.get("speed_kmh") is not None:
        out.append(f"moving from the {a['moving_from']} at about {a['speed_kmh']} km/h ({a['movement_from']})")
    if a.get("arrives_min") is None:
        out.append(f"no rain on its way here within {AHEAD_H} h at that speed")
    elif a["arrives_min"] > 0:
        lo, hi = a["arrives_range_min"]
        out.append(f"rain reaches here about {clock(a['arrives_min'])} (in {a['arrives_min']} min; range "
                   f"{clock(lo)}-{clock(hi)}): {kind(a.get('lasts_min'))}")
    elif a.get("lasts_min") is not None:
        out.append(f"rain here now: {kind(a['lasts_min'])} more")
    return out


def watch(every, until, room=None, say=print):
    """Look every `every` minutes until `until` (HH:MM); say a line only when
    the warning changes: rain due within WARN_MIN, rain here, or clear again."""
    import alert
    end = datetime.strptime(until, "%H:%M").replace(year=datetime.now().year, month=datetime.now().month,
                                                     day=datetime.now().day)
    if end < datetime.now():
        end += timedelta(days=1)
    last = None
    while datetime.now() < end:
        try:
            a = look()
        except (requests.RequestException, ValueError, OSError) as problem:
            say(f"{datetime.now():%H:%M} rain check failed ({problem}); trying again next time")
            a = None
        if a and not a.get("error"):
            due = a.get("arrives_min")
            state = ("here" if a["rain_here"] else "due" if due is not None and due <= WARN_MIN else "dry")
            if state != last:
                if state != "dry" or last is not None:
                    say(f"{datetime.now():%H:%M} " + ("RAIN WARNING: " if state != "dry" else "rain warning over: ")
                        + "; ".join(a["lines"]))
                if state != "dry" and room:
                    try:
                        alert.flash(room, "Blue")
                    except Exception as problem:        # a light that fails never stops the watch
                        say(f"  the {room} lights could not be pulsed: {problem}")
                if last is None and state == "dry":
                    say(f"{datetime.now():%H:%M} rain watch on: " + "; ".join(a["lines"]))
                last = state
            _keep(a)
        time.sleep(every * 60)


def _keep(a):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({**a, "t": time.time()}), encoding="utf-8")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--watch", action="store_true", help="look again every --every minutes until --until")
    ap.add_argument("--every", type=float, default=15)
    ap.add_argument("--until", default="06:00", help="HH:MM")
    ap.add_argument("--flash", metavar="ROOM", help="with --watch: pulse this Hue room's lights blue on a warning")
    args = ap.parse_args()
    if args.watch:
        watch(args.every, args.until, args.flash, say=lambda line: print(line, flush=True))
        return

    def work():
        a = look()
        _keep(a)
        if not args.json:
            print("\n".join(a.get("lines") or []))
        return a

    interface.main("rain", work, args.json)


if __name__ == "__main__":
    main()
