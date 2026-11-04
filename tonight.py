#!/usr/bin/env python3
"""What is worth pointing the telescope at tonight, and is the weather up to it.

    ./tonight.py                 report for tonight (or the night in progress)
    ./tonight.py --date 2026-10-10
    ./tonight.py --week          the weather verdict for each of the next seven nights
    ./tonight.py --json          machine-readable, for driving the mount
    ./tonight.py --html web/index.html
    ./tonight.py --offline       skip weather, seeing and comets
    ./tonight.py --demo          try it with made-up weather at an example site
"""
import argparse
import json
import statistics
import sys
import time
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

import config
import feeds
import sky

ROOT = Path(__file__).parent


# --- gathering ---------------------------------------------------------------

FOG_VISIBILITY_M = 1000   # the Met Office's fog
FOG_DEW_GAP = 0.5         # degrees: air this close to its dew point ...
FOG_WIND = 5              # km/h: ... and this still, mist and fog form


def foggy(h):
    """Whether fog is likely in this forecast hour: the visibility forecast
    under a kilometre or, without one, saturated air with hardly any wind.
    2 November 2026: fog came in at 20:40 (Gary, half a mile away: "I can see
    nothing"), and the forecast had said only "dew likely"; its cloud cover
    does not count fog at the ground."""
    if h.get("visibility") is not None:
        return h["visibility"] < FOG_VISIBILITY_M
    return h["temp"] - h["dew_point"] <= FOG_DEW_GAP and (h["wind"] or 0) <= FOG_WIND


def weather_report(night, lat, lon, source=feeds):
    """Hourly conditions through the night plus a go/no-go verdict."""
    w = source.weather(lat, lon)
    if not w:
        return None
    t = np.array(w["time"], dtype=float)
    keep = (night.at(t, night.sun_alt) < sky.BODY_SUN_LIMIT) \
        & (t >= night.unix[0]) & (t <= night.unix[-1]) \
        & (t >= datetime.now(timezone.utc).timestamp() - 3600)
    blocks = source.seeing(lat, lon) or []
    hours = []
    for i in np.flatnonzero(keep):
        near = min(blocks, key=lambda b: abs(b["time"] - t[i]), default=None)
        if near and abs(near["time"] - t[i]) > 5400:
            near = None
        hours.append({
            "time": datetime.fromtimestamp(t[i], night.tz),
            "cloud": w["cloud_cover"][i], "low": w["cloud_cover_low"][i],
            "mid": w["cloud_cover_mid"][i], "high": w["cloud_cover_high"][i],
            "rain_chance": w["precipitation_probability"][i] or 0,
            "rain_mm": w["precipitation"][i] or 0,
            "temp": w["temperature_2m"][i], "dew_point": w["dew_point_2m"][i],
            "humidity": w["relative_humidity_2m"][i],
            "wind": w["wind_speed_10m"][i], "gust": w["wind_gusts_10m"][i],
            # Where it blows from, in degrees: shelter on one side is no help from another.
            "wind_from": (w.get("wind_direction_10m") or [None] * len(t))[i],
            # Metres; None from a source without it (the demo).
            "visibility": (w.get("visibility") or [None] * len(t))[i],
            "seeing": near and near["seeing"],
            "transparency": near and near["transparency"],
        })
    if not hours:
        return None

    for h in hours:
        h["fog"] = foggy(h)
        h["clear"] = clear_hour(h)
    centres = _centres(source, lat, lon, t[keep])
    for h, c in zip(hours, centres or [None] * len(hours)):
        h["centres"] = c
    single = _longest(hours, lambda h: h["clear"])
    # With the four centres, the spell is the hours at least half of them call
    # clear (as ryanclinton.uk's Meanwhile page): not one model's pessimism or
    # the most hopeful one's. Without them, the one forecast's.
    agreed = (lambda h: h["centres"] is not None and h["centres"]["of"] > 0
              and h["centres"]["clear"] * 2 >= h["centres"]["of"])
    best = _longest(hours, agreed) if centres else single
    # Rain, fog, dew and the cloud by the same evidence as the spell: at least
    # half the centres when they are here, the one forecast when not. 4 November
    # 2026: the one forecast's rain could still have made a night the centres
    # agreed was clear NO-GO.
    def most(h, key, own):
        c = h["centres"]
        return c[key] * 2 >= c["of"] if c and c["of"] else own

    def by(key, fs):
        n = max((h["centres"][key] for h in fs if h["centres"]), default=None)
        return None if n is None else f"{n} of {max(h['centres']['of'] for h in fs if h['centres'])} centres"
    mean_cloud = statistics.mean(h["centres"]["cloud"] if h["centres"] and h["centres"]["of"] else h["cloud"]
                                 for h in hours)
    wet = [h for h in hours if most(h, "wet", h["rain_chance"] >= 30 or h["rain_mm"] > 0)]
    notes = []
    if wet:
        notes.append(f"rain possible from {wet[0]['time']:%H:%M} "
                     f"({by('wet', wet) or str(max(h['rain_chance'] for h in wet)) + '% chance'})")
    gust = max(h["gust"] for h in hours)
    if gust >= 35:
        notes.append(f"gusts to {gust:.0f} km/h will shake the scope")
    elif gust >= 25:
        notes.append(f"breezy, gusts to {gust:.0f} km/h")
    fog = [h for h in hours if most(h, "fog", h["fog"])]
    if fog:
        seen = [h["visibility"] for h in fog if h["visibility"] is not None]
        notes.append(f"fog likely from {fog[0]['time']:%H:%M}"
                     + (f" ({by('fog', fog)})" if by("fog", fog) else
                        f" (visibility down to {min(seen) / 1000:.1f} km)" if seen else
                        " (air at its dew point with hardly any wind)"))
    damp = [h for h in hours if most(h, "damp", h["temp"] - h["dew_point"] <= 2)]
    if damp:
        notes.append(f"dew likely from {damp[0]['time']:%H:%M}; cover the laptop")

    split = any(h["centres"] and h["centres"]["clear"] * 4 < h["centres"]["of"] * 3 for h in best)
    if centres and [h["time"] for h in best] != [h["time"] for h in single]:
        notes.insert(0, "forecasts disagree: " + spell_words(best, "the four centres", centres=True)
                     + "; the default forecast alone: " + spell_words(single, ""))
    elif split:
        notes.insert(0, "the centres are split: " + spell_words(best, "half or more", centres=True))
    if len(best) >= 3 and not split:
        verdict = "GO"
    elif len(best) >= 1 or mean_cloud < 60:
        verdict = "MARGINAL"
    else:
        verdict = "NO-GO"
    if len(wet) > len(hours) / 2:
        verdict = "NO-GO"
    return {
        "verdict": verdict, "mean_cloud": round(mean_cloud),
        "clear_from": best[0]["time"] if best else None,
        "clear_to": best[-1]["time"] if best else None,
        "clear_hours": len(best), "notes": notes, "hours": hours,
        "fog_hours": [h["time"] for h in fog],
        "single_clear_hours": len(single), "centres": bool(centres),
    }


def clear_hour(h):
    """One forecast hour clear enough to observe: cloud 30% or less, dry, no fog.
    ryanclinton.uk's Meanwhile page judges each centre's hours by this too."""
    return (h["cloud"] <= 30 and (h.get("rain_chance") or 0) < 30
            and (h.get("rain_mm") or 0) == 0 and not h["fog"])


def _longest(hours, ok):
    """The longest run of consecutive hours for which ok(hour) holds."""
    best, run = [], []
    for h in hours:
        run = run + [h] if ok(h) else []
        if len(run) > len(best):
            best = run
    return best


def centre_agreement(c, times):
    """For each unix hour in times: {"clear": centres calling it clear, "of":
    centres covering it} from feeds.weather_centres()' reply c."""
    index = {int(x): i for i, x in enumerate(c["time"])}
    out = []
    for x in times:
        i = index.get(int(x))
        clear = of = wet = fog = damp = 0
        cloud = []
        by = {}
        for m, name in feeds.CENTRES.items():
            g = c.get(m) or {}
            v = lambda k: (g.get(k) or [None] * len(c["time"]))[i]
            if i is None or v("cloud_cover") is None:
                continue
            h = {"cloud": v("cloud_cover"), "rain_chance": v("precipitation_probability"),
                 "rain_mm": v("precipitation"), "temp": v("temperature_2m"),
                 "dew_point": v("dew_point_2m"), "wind": v("wind_speed_10m"), "visibility": v("visibility")}
            h["fog"] = (h["visibility"] is not None or (h["temp"] is not None and h["dew_point"] is not None)) \
                and foggy(h)
            of += 1
            clear += clear_hour(h)
            wet += (h["rain_chance"] or 0) >= 30 or (h["rain_mm"] or 0) > 0
            fog += bool(h["fog"])
            damp += h["temp"] is not None and h["dew_point"] is not None and h["temp"] - h["dew_point"] <= 2
            cloud.append(h["cloud"])
            by[name] = {"cloud": h["cloud"], "clear": clear_hour(h), "fog": bool(h["fog"]),
                        "wet": (h["rain_chance"] or 0) >= 30 or (h["rain_mm"] or 0) > 0,
                        "dew_gap": None if h["temp"] is None or h["dew_point"] is None
                        else round(h["temp"] - h["dew_point"], 1),
                        "wind": h["wind"], "visibility": h["visibility"]}
        out.append({"clear": clear, "of": of, "wet": wet, "fog": fog, "damp": damp,
                    "cloud": statistics.mean(cloud) if cloud else None, "by": by})
    return out


def _centres(source, lat, lon, times):
    """Each hour's agreement among the four centres, or None when the source
    has none (the demo) or they could not be had: the one forecast stands."""
    get = getattr(source, "weather_centres", None)
    if not get:
        return None
    try:
        c = get(lat, lon)
        out = centre_agreement(c, times) if c else None
    except Exception:      # noqa: BLE001 - a failed second opinion leaves the first standing
        return None
    return out if out and any(a["of"] for a in out) else None


def spell_words(run, who, centres=False):
    """"<who> clear 01:00-04:00 (3 of 4 at worst)", "<who> no clear spell"."""
    if not run:
        return f"{who} no clear spell".strip()
    words = f"{who} clear {hm(run[0]['time'])}-{hm(run[-1]['time'] + timedelta(hours=1))}".strip()
    if centres:
        worst = min(run, key=lambda h: h["centres"]["clear"] / h["centres"]["of"])["centres"]
        words += f" ({worst['clear']} of {worst['of']} at worst"
        if worst["clear"] * 4 < worst["of"] * 3:     # a split: say where the agreement is firm
            firm = _longest(run, lambda h: h["centres"]["clear"] * 4 >= h["centres"]["of"] * 3)
            words += (f"; 3 of 4 or more {hm(firm[0]['time'])}-{hm(firm[-1]['time'] + timedelta(hours=1))}"
                      if firm else "; never 3 of 4")
        words += ")"
    return words


def week(cfg, demo=False, nights=7):
    """The weather verdict for tonight and the nights after it, as (date,
    report) pairs. The forecast reaches about a week; the far end of it is
    a guide and no more."""
    source = feeds
    if demo:
        import demo as source
    site = cfg["site"]
    first = sky.Night(cfg).date
    out = []
    for n in range(nights):
        night = sky.Night(cfg, first + timedelta(days=n))
        out.append((night.date, weather_report(night, site["latitude"], site["longitude"], source)))
    return out


def render_forecast(rep):
    """The four forecasting centres side by side, hour by hour through the
    dark: each one's cloud (* = that centre calls the hour clear: 30% or
    less, dry, no fog; R rain, F fog), then the dew gap, wind and visibility
    from all four, and the verdict they make together. 4 November 2026: the
    night's comparison was made from scratch scripts; this is it as a command."""
    w = rep and rep.get("weather")
    if not w:
        return "No forecast (offline, or the weather service could not be reached)."
    hours = [h for h in w["hours"] if h.get("centres") and h["centres"].get("by")]
    if not hours:
        return ("The four centres could not be had; the default forecast alone: "
                + weather_line(w))
    names = list(feeds.CENTRES.values())

    def cell(c):
        if not c:
            return "-"
        return f"{c['cloud']:.0f}%" + ("*" if c["clear"] else "R" if c["wet"] else "F" if c["fog"] else "")
    rows = [[f"{h['time']:%H:%M}"] + [cell(h["centres"]["by"].get(n)) for n in names]
            + [f"{h['centres']['clear']}/{h['centres']['of']}"] for h in hours]

    def spread(key, fmt):
        vals = [c[key] for h in hours for c in h["centres"]["by"].values() if c.get(key) is not None]
        return fmt(min(vals), max(vals)) if vals else "-"
    out = [f"{rep['site']} - the four forecasting centres, {rep['date']}", "",
           table(["time"] + names + ["clear"], rows), "",
           "* clear (30% cloud or less, dry, no fog)   R rain   F fog", "",
           "dew gap " + spread("dew_gap", lambda a, b: f"{a:.1f}-{b:.1f}°C")
           + ", wind " + spread("wind", lambda a, b: f"{a:.0f}-{b:.0f} km/h")
           + ", visibility " + spread("visibility", lambda a, b: f"{a / 1000:.0f}-{b / 1000:.0f} km"),
           "together: " + weather_line(w)]
    return "\n".join(out)


def render_week(site, days):
    out = [f"{site} - the week's nights", ""]
    out += [f"{date:%a %d %b}  {weather_line(w)}" for date, w in days]
    return "\n".join(out + ["", "The last few nights of a week's forecast often change: look again nearer the time."])


def comet_results(night, lat, lon, elevation, source=feeds):
    start = datetime.fromtimestamp(night.unix[0], timezone.utc)
    stop = datetime.fromtimestamp(night.unix[-1], timezone.utc)
    out = []
    for c in source.comets(lat, lon, elevation, start, stop) or []:
        track = np.array(c["track"])
        ra = np.degrees(np.unwrap(np.radians(track[:, 1])))
        ra = night.at(night.unix, np.interp(night.unix, track[:, 0], ra)) % 360
        dec = np.interp(night.unix, track[:, 0], track[:, 2])
        alt, az = night.altaz_moving(ra, dec)
        target = {"id": c["id"], "name": c["name"], "kind": "comet", "mag": c["mag"]}
        result = night.assess(target, ra, dec, alt, az)
        if result:
            result["motion_arcsec_min"] = comet_motion(track, result["best"].timestamp())
            out.append(result)
    return out


def comet_motion(track, when):
    """How fast the comet moves across the sky at `when` (unix), in
    arcseconds a minute, from the two rows of its track either side: a frame
    longer than about the seeing divided by this smears it."""
    i = int(np.clip(np.searchsorted(track[:, 0], when), 1, len(track) - 1))
    (t0, ra0, dec0), (t1, ra1, dec1) = track[i - 1], track[i]
    apart = sky.separation(ra0, dec0, ra1, dec1) * 3600
    return round(float(apart / max((t1 - t0) / 60, 1e-9)), 2)


MOST_CAMPAIGNS = 8   # Target Tool stars listed: the most wanted first


def _when(value):
    """A Target Tool time (unix seconds, or ISO text) as unix seconds, or None."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp()


def campaign_results(night, lat, lon, source=feeds, now=None):
    """The AAVSO Target Tool's stars this camera can measure tonight: asked
    for by photometry in V or any filter (the camera's green is close to V,
    untransformed), with a range that reaches between variables.BRIGHTEST
    and variables.FAINTEST, and up in the dark here. AAVSO's high-priority
    ones first, then the most overdue for their cadence (days since the last
    measurement over the days asked between them). Empty without a key."""
    import variables
    now = now or time.time()
    out = []
    n = len(night.unix)
    ask = getattr(source, "aavso_targets", None)     # the demo has none
    wanted = []
    for t in (ask(lat, lon, night.min_alt) if ask else None) or []:
        mode, filters = str(t.get("obs_mode") or ""), str(t.get("filter") or "")
        if mode not in ("Photometry", "All") or not any(f in filters for f in ("V", "All")):
            continue
        bright, faint = t.get("max_mag"), t.get("min_mag")
        if bright is None or faint is None or bright > variables.FAINTEST or faint < variables.BRIGHTEST:
            continue
        wanted.append(t)
    if not wanted:
        return []
    alts, azs = night.altaz_fixed([t["ra"] for t in wanted], [t["dec"] for t in wanted])   # all at once
    for t, alt, az in zip(wanted, alts, azs):
        filters, bright, faint = str(t.get("filter") or ""), t["max_mag"], t["min_mag"]
        target = {"id": t["star_name"], "kind": "variable star", "mag": bright}
        r = night.assess(target, np.full(n, t["ra"]), np.full(n, t["dec"]), alt, az)
        if not r:
            continue
        last = _when(t.get("last_data_point"))
        days = None if last is None else round((now - last) / 86400, 1)
        cadence = t.get("obs_cadence")
        overdue = None if days is None or not cadence else round(days / cadence, 1)
        r.update({"section": t.get("obs_section"), "priority": bool(t.get("priority")), "var_type": t.get("var_type"),
                  "range": [bright, faint], "filter": filters, "cadence_days": cadence,
                  "days_since_measured": days, "overdue": overdue, "note": t.get("other_info") or "",
                  "link": "https://www.aavso.org/vsx/index.php?view=results.get&ident=" +
                          requests.utils.quote(t["star_name"])})
        out.append(r)
    out.sort(key=lambda r: (not r["priority"], -(r["overdue"] if r["overdue"] is not None else 99)))
    return out[:MOST_CAMPAIGNS]


def literature_results():
    """arXiv's papers not yet marked read on each topic watched
    (literature.py), only the topics with any."""
    import literature
    return [t for t in literature.unread() if t["papers"]]


def supernova_results(night, source=feeds):
    """The bright supernovae (feeds.supernovae) up here in the dark tonight,
    each with its window, brightest first."""
    out = []
    n = len(night.unix)
    for s in source.supernovae(datetime.fromtimestamp(night.unix[0], timezone.utc)) or []:
        alt, az = night.altaz_fixed([s["ra"]], [s["dec"]])
        target = {"id": s["id"], "name": s["host"], "kind": "supernova", "mag": s["mag"]}
        r = night.assess(target, np.full(n, s["ra"]), np.full(n, s["dec"]), alt[0], az[0])
        if r:
            out.append(dict(r, type=s["type"], last_seen=s["last_seen"], peak_mag=s["peak_mag"]))
    return out


def build(cfg, date=None, offline=False, demo=False):
    # In demo mode the weather and sky brightness come from demo.py.
    source = feeds
    feeds.used.clear()
    if demo:
        import demo as source
    site = cfg["site"]
    lat, lon = site["latitude"], site["longitude"]
    night = sky.Night(cfg, date)

    pollution = None
    if "sqm" in site:
        pollution = {"sqm": site["sqm"], "bortle": feeds.bortle(site["sqm"]),
                     "source": "config.toml"}
    elif not offline:
        pollution = source.light_pollution(lat, lon)
    if pollution:
        night.sqm = pollution["sqm"]

    results = []
    targets = sky.load_targets()
    alts, azs = night.altaz_fixed([t["ra"] for t in targets], [t["dec"] for t in targets])
    n = len(night.unix)
    for t, alt, az in zip(targets, alts, azs):
        r = night.assess(t, np.full(n, t["ra"]), np.full(n, t["dec"]), alt, az)
        if r:
            results.append(r)
    for key, (name, appeal) in sky.BODIES.items():
        ra, dec, alt, az = night.body(key)
        target = {"id": name, "kind": "moon" if key == "moon" else "planet",
                  "appeal": appeal}
        r = night.assess(target, ra, dec, alt, az, solar_system=True)
        if r:
            results.append(r)
    if not offline:
        results += comet_results(night, lat, lon, site.get("elevation_m", 0), source)
    results.sort(key=lambda r: -r["score"])
    supernovae = [] if offline else supernova_results(night, source)
    campaigns = [] if offline else campaign_results(night, lat, lon, source)
    papers = [] if offline or demo else literature_results()

    now = datetime.now(night.tz)
    for t in results + supernovae + campaigns:
        # A window "starting" within the next few minutes is open now: the
        # sky is only sampled every ten minutes.
        t["now"] = t["start"] <= now + timedelta(minutes=sky.STEP_MIN) and now <= t["end"]
        t["tags"] = target_tags(t, pollution, now)
    mid = len(night.unix) // 2
    # Moonrise and moonset only matter between dusk and dawn.
    moon_rise, moon_set = night.crossings(night.moon_alt, 0, night.sun_alt < 0)
    sunset, sunrise = night.crossings(-night.sun_alt, 0.833)
    dark = night.span(night.dark)
    report = {
        "site": site["name"], "date": night.date,
        "generated": datetime.now(night.tz),
        "sunset": sunset, "sunrise": sunrise,
        "dark_level": night.dark_level,
        "dark_start": dark and dark[0], "dark_end": dark and dark[1],
        "dark_hours": round(float(night.dark.sum() * sky.STEP_MIN / 60), 1),
        "now": now,
        "moon": {
            "up_at_sunset": bool(night.moon_alt[int(np.argmax(night.sun_alt < 0))] > 0),
            "illumination": round(float(night.moon_illum[mid]) * 100),
            "waxing": bool(night.moon_waxing),
            "rise": moon_rise, "set": moon_set,
            "up_in_darkness": bool((night.dark & (night.moon_alt > 0)).any()),
        },
        "light_pollution": pollution,
        "weather": None if offline else weather_report(night, lat, lon, source),
        "targets": results,
        "supernovae": supernovae,
        "campaigns": campaigns,
        "papers": papers,
        "news": [] if offline else source.news(datetime.now(timezone.utc)) or [],
    }
    # How old each feed's data is: a copy kept because the source failed is
    # said to be stale, never passed off as tonight's.
    report["sources"] = [] if demo or offline else feeds.freshness()
    return report


def target_tags(t, pollution, now):
    """Short reasons a target ranks where it does, for the page."""
    tags = []
    if t["best_alt"] >= 60:
        tags.append("HIGH")
    elif t["best_alt"] < 30:
        tags.append("LOW")
    if t["kind"] not in ("moon", "planet"):
        base = pollution["sqm"] if pollution else 21.0
        if t["sky"] >= base - 0.2:
            tags.append("DARK SKY")
        elif t["sky"] < base - 0.7:
            tags.append("MOONLIGHT")
        if t["moon_sep"] is not None and t["moon_sep"] >= 60 and t["sky"] < base - 0.2:
            tags.append("MOON FAR")
    if t["hours"] >= 3:
        tags.append("GOOD WINDOW")
    if t["start"] > now + timedelta(minutes=sky.STEP_MIN):
        tags.append(f"FROM {t['start']:%H:%M}")
    return tags


# --- rendering ---------------------------------------------------------------

def hm(t):
    return t.strftime("%H:%M") if t else "--:--"


def moon_text(moon):
    phase = "waxing" if moon["waxing"] else "waning"
    events = sorted((t, word) for t, word in
                    ((moon["rise"], "rises"), (moon["set"], "sets")) if t)
    when = ", ".join(f"{word} {hm(t)}" for t, word in events) or "no rise or set tonight"
    return f"{moon['illumination']}% lit, {phase}, {when}"


def sky_text(lp):
    if not lp:
        return "light pollution unknown (assuming 21.0 mag/arcsec²)"
    # Sky-limited imaging needs exposure in proportion to sky brightness.
    penalty = 10 ** (0.4 * (feeds.NATURAL_SKY - lp["sqm"]))
    zone = f"zone {lp['zone']}, " if "zone" in lp else ""
    return (f"{lp['sqm']:.2f} mag/arcsec² at the zenith, moonless "
            f"({zone}about Bortle {lp['bortle']}); faint objects need "
            f"{penalty:.1f}x the exposure of a pristine sky")


def weather_line(w):
    if not w:
        return "no forecast available"
    if w["clear_hours"]:
        clear = (f"clear spell {hm(w['clear_from'])}-"
                 f"{hm(w['clear_to'] + timedelta(hours=1))} ({w['clear_hours']} h)")
    else:
        clear = "no clear spell"
    return "; ".join([f"{w['verdict']}: {clear}, average cloud {w['mean_cloud']}%"]
                     + w["notes"])


def seeing_text(h):
    if not h["seeing"]:
        return "", ""
    return feeds.SEEING[h["seeing"]], feeds.TRANSPARENCY[h["transparency"]]


def target_row(i, t):
    mag = "" if t["mag"] is None else f"{t['mag']:.1f}"
    size = "" if not t["size"] else f"{t['size']:.0f}'"
    return [str(i), t["id"], t["name"][:22], t["kind"], mag, size, hm(t["best"]),
            f"{t['best_alt']:.0f}° {t['direction']}",
            f"{hm(t['start'])}-{hm(t['end'])}",
            "" if t["moon_sep"] is None else f"{t['moon_sep']}°",
            f"{t['sky']:.1f}", f"{t['score']:.0f}"]


TARGET_HEAD = ["#", "Object", "Name", "Type", "Mag", "Size", "Best", "Alt",
               "Window", "Moon", "Sky", "Score"]
WEATHER_HEAD = ["Time", "Cloud", "Low/Mid/High", "Rain", "Temp", "Dew gap",
                "Wind/gust from", "Seeing", "Transp."]


def weather_row(h):
    see, transp = seeing_text(h)
    return [hm(h["time"]), f"{h['cloud']}%", f"{h['low']}/{h['mid']}/{h['high']}",
            f"{h['rain_chance']}%", f"{h['temp']:.0f}°C",
            f"{h['temp'] - h['dew_point']:.1f}°",
            f"{h['wind']:.0f}/{h['gust']:.0f}" + (f" {sky.compass(h['wind_from'])}" if h.get("wind_from") is not None else ""),
            see, transp]


def table(head, rows):
    widths = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip()
    return "\n".join([line(head), "  ".join("-" * w for w in widths)]
                     + [line(r) for r in rows])


def summary_lines(rep):
    return [
        ("Sun", f"sets {hm(rep['sunset'])}, rises {hm(rep['sunrise'])}; "
                f"{rep['dark_level']} darkness {hm(rep['dark_start'])}-"
                f"{hm(rep['dark_end'])} ({rep['dark_hours']} h)"),
        ("Moon", moon_text(rep["moon"])),
        ("Sky", sky_text(rep["light_pollution"])),
        ("Weather", weather_line(rep["weather"])),
    ]


def render_text(rep, top):
    out = [f"{rep['site']} - night of {rep['date']:%a %d %b %Y}", ""]
    out += [f"{k + ':':9}{v}" for k, v in summary_lines(rep)]
    if rep["weather"]:
        out += ["", table(WEATHER_HEAD, [weather_row(h) for h in rep["weather"]["hours"]])]
    rows = [target_row(i, t) for i, t in enumerate(rep["targets"][:top], 1)]
    out += ["", f"Top {len(rows)} of {len(rep['targets'])} observable targets", ""]
    out += [table(TARGET_HEAD, rows), "",
            "Sky = background brightness at the target's best time, including "
            "moonlight (higher is darker)."]
    if rep.get("supernovae"):
        out += ["", "Bright supernovae up tonight (Rochester's active list):"]
        out += [f"  {s['id']} in {s['name']} ({s['type']}), mag {s['mag']:g} on {s['last_seen']}: "
                f"best {hm(s['best'])} at {s['best_alt']:.0f}° {s['direction']}" for s in rep["supernovae"]]
    if rep.get("news"):
        out += ["", "In the sky soon (in-the-sky.org), and the news:"]
        out += [f"  {n['title']}" if n["kind"] == "event" else f"  {n['source']}: {n['title']}" for n in rep["news"]]
    return "\n".join(out)


def write_html(rep, top, path):
    """Write the status page for a report; the page itself lives in page.py."""
    import page
    page.write(rep, top, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", type=Date.fromisoformat,
                    help="evening date of the night to plan (default: tonight)")
    ap.add_argument("--top", type=int, default=25, help="targets to list")
    ap.add_argument("--kind", help="only this type, e.g. galaxy, planet, globular")
    ap.add_argument("--week", action="store_true",
                    help="the weather verdict for each of the next seven nights, and nothing else")
    ap.add_argument("--forecast", action="store_true",
                    help="the four forecasting centres side by side, hour by hour, and nothing else")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="made-up weather at the example site; needs no setup")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", metavar="FILE", help="also write an HTML page")
    args = ap.parse_args()

    cfg = config.example() if args.demo else config.load()
    if args.week:
        if args.json or args.html or args.date or args.offline:
            ap.error("--week prints its own short text: it does not go with --json, --html, --date or --offline")
        print(render_week(cfg["site"]["name"], week(cfg, args.demo)))
        return
    rep = build(cfg, args.date, args.offline, args.demo)
    if args.forecast:
        if args.json or args.html or args.week:
            ap.error("--forecast prints its own short text: it does not go with --json, --html or --week")
        print(render_forecast(rep))
        return
    if args.kind:
        rep["targets"] = [t for t in rep["targets"] if args.kind == t["kind"]
                          or args.kind in t["kind"].replace("+", " ").split()]
    if args.html:
        write_html(rep, args.top, args.html)
    if args.json:
        rep["targets"] = rep["targets"][:args.top]
        json.dump(rep, sys.stdout, indent=1,
                  default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
        print()
    else:
        print(render_text(rep, args.top))


if __name__ == "__main__":
    main()
