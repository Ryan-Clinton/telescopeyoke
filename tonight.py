#!/usr/bin/env python3
"""What is worth pointing the telescope at tonight, and is the weather up to it.

    ./tonight.py                 report for tonight (or the night in progress)
    ./tonight.py --date 2026-10-10
    ./tonight.py --json          machine-readable, for driving the mount
    ./tonight.py --html web/index.html
    ./tonight.py --offline       skip weather, seeing and comets
    ./tonight.py --demo          try it with made-up weather at an example site
"""
import argparse
import html
import json
import statistics
import sys
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import config
import feeds
import sky

ROOT = Path(__file__).parent


# --- gathering ---------------------------------------------------------------

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
            "seeing": near and near["seeing"],
            "transparency": near and near["transparency"],
        })
    if not hours:
        return None

    # Longest run of consecutive mostly-clear, dry hours.
    best, run = [], []
    for h in hours:
        clear = h["cloud"] <= 30 and h["rain_chance"] < 30 and h["rain_mm"] == 0
        run = run + [h] if clear else []
        if len(run) > len(best):
            best = run
    mean_cloud = statistics.mean(h["cloud"] for h in hours)
    wet = [h for h in hours if h["rain_chance"] >= 30 or h["rain_mm"] > 0]
    notes = []
    if wet:
        notes.append(f"rain possible from {wet[0]['time']:%H:%M} "
                     f"({max(h['rain_chance'] for h in wet)}% chance)")
    gust = max(h["gust"] for h in hours)
    if gust >= 35:
        notes.append(f"gusts to {gust:.0f} km/h will shake the scope")
    elif gust >= 25:
        notes.append(f"breezy, gusts to {gust:.0f} km/h")
    damp = [h for h in hours if h["temp"] - h["dew_point"] <= 2]
    if damp:
        notes.append(f"dew likely from {damp[0]['time']:%H:%M}; cover the laptop")

    if len(best) >= 3:
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
    }


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
            out.append(result)
    return out


def build(cfg, date=None, offline=False, demo=False):
    # In demo mode the weather and sky brightness come from demo.py.
    source = feeds
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

    mid = len(night.unix) // 2
    # Moonrise and moonset only matter between dusk and dawn.
    moon_rise, moon_set = night.crossings(night.moon_alt, 0, night.sun_alt < 0)
    sunset, sunrise = night.crossings(-night.sun_alt, 0.833)
    dark = night.span(night.dark)
    return {
        "site": site["name"], "date": night.date,
        "generated": datetime.now(night.tz),
        "sunset": sunset, "sunrise": sunrise,
        "dark_level": night.dark_level,
        "dark_start": dark and dark[0], "dark_end": dark and dark[1],
        "dark_hours": round(float(night.dark.sum() * sky.STEP_MIN / 60), 1),
        "moon": {
            "illumination": round(float(night.moon_illum[mid]) * 100),
            "waxing": bool(night.moon_waxing),
            "rise": moon_rise, "set": moon_set,
            "up_in_darkness": bool((night.dark & (night.moon_alt > 0)).any()),
        },
        "light_pollution": pollution,
        "weather": None if offline else weather_report(night, lat, lon, source),
        "targets": results,
    }


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
                "Wind/gust", "Seeing", "Transp."]


def weather_row(h):
    see, transp = seeing_text(h)
    return [hm(h["time"]), f"{h['cloud']}%", f"{h['low']}/{h['mid']}/{h['high']}",
            f"{h['rain_chance']}%", f"{h['temp']:.0f}°C",
            f"{h['temp'] - h['dew_point']:.1f}°", f"{h['wind']:.0f}/{h['gust']:.0f}",
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
    return "\n".join(out)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Telescope - tonight</title>
<style>
  :root {{ --bg: #0b0d12; --panel: #141821; --line: #262c3a; --text: #d7dce6;
          --dim: #8a93a6; --go: #4cc38a; --marginal: #e0b341; --nogo: #e5636b; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 20px 16px 40px; background: var(--bg);
         color: var(--text); font: 15px/1.5 system-ui, sans-serif; }}
  main {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 2px; }}
  h2 {{ font-size: 15px; margin: 28px 0 8px; color: var(--dim);
       text-transform: uppercase; letter-spacing: .06em; }}
  .dim {{ color: var(--dim); font-size: 13px; }}
  .verdict {{ display: inline-block; margin: 14px 0 4px; padding: 4px 14px;
             border-radius: 999px; font-weight: 700; color: #0b0d12; }}
  .GO {{ background: var(--go); }} .MARGINAL {{ background: var(--marginal); }}
  .NO-GO {{ background: var(--nogo); }}
  dl {{ display: grid; grid-template-columns: 90px 1fr; gap: 6px 12px;
       background: var(--panel); border: 1px solid var(--line);
       border-radius: 8px; padding: 14px 16px; margin: 10px 0 0; }}
  dt {{ color: var(--dim); }} dd {{ margin: 0; }}
  .scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
  table {{ border-collapse: collapse; width: 100%; background: var(--panel);
          font-variant-numeric: tabular-nums; white-space: nowrap; }}
  th, td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--line); }}
  th {{ color: var(--dim); font-weight: 600; font-size: 13px; }}
  tr:last-child td {{ border-bottom: 0; }}
  img {{ max-width: 100%; border-radius: 8px; border: 1px solid var(--line); }}
</style></head><body><main>
<h1>{site}</h1>
<div class="dim">Night of {date} &middot; updated {generated} &middot; refreshes every 5 minutes</div>
{verdict}
<dl>{summary}</dl>
{scope}
{camera}
<h2>Top targets</h2>
<div class="scroll">{targets}</div>
<p class="dim">Sky is the background brightness at each target's best time,
including moonlight; higher is darker.</p>
{clouds}
<h2>Hour by hour</h2>
<div class="scroll">{weather}</div>
<p class="dim">Weather: Open-Meteo. Seeing: 7Timer. Light pollution: D. Lorenz atlas.
Comets: COBS and JPL Horizons. Catalogue: OpenNGC (CC-BY-SA-4.0).</p>
</main>
<script>
  // Reload the telescope pictures without reloading the whole page.
  setInterval(() => {{
    for (const img of document.querySelectorAll("img[data-live]")) {{
      img.src = img.dataset.live + "?t=" + Date.now();
    }}
  }}, 1000);
</script>
</body></html>
"""


def html_table(head, rows):
    e = html.escape
    cells = lambda tag, r: "".join(f"<{tag}>{e(c)}</{tag}>" for c in r)
    body = "".join(f"<tr>{cells('td', r)}</tr>" for r in rows)
    return f"<table><thead><tr>{cells('th', head)}</tr></thead><tbody>{body}</tbody></table>"


def render_html(rep, top, out_dir):
    w = rep["weather"]
    verdict = f'<div class="verdict {w["verdict"]}">{w["verdict"]}</div>' if w else ""
    summary = "".join(f"<dt>{k}</dt><dd>{html.escape(v)}</dd>"
                      for k, v in summary_lines(rep))
    # Shown once the camera side saves frames next to the page.
    camera = ""
    frame = out_dir / "latest.jpg"
    if frame.exists():
        # The timestamp stops the browser showing a cached older frame.
        taken = datetime.fromtimestamp(frame.stat().st_mtime, rep["generated"].tzinfo)
        camera = ('<h2>Latest frame through the telescope</h2>'
                  f'<img src="latest.jpg?t={taken.timestamp():.0f}" data-live="latest.jpg" '
                  'alt="Latest camera frame">')
    clouds = ""
    if (out_dir / "clouds.jpg").exists():
        clouds = ('<h2>Cloud from the satellite (bright = cloud, dark = clear)</h2>'
                  '<img src="clouds.jpg" alt="Infrared satellite image of cloud over the site">')
    scope = ""
    if (out_dir / "scope.jpg").exists():
        scope = ('<h2>The telescope (laptop camera, updates during slews)</h2>'
                 '<img src="scope.jpg" data-live="scope.jpg" alt="View of the telescope">')
    return PAGE.format(
        site=html.escape(rep["site"]), date=f"{rep['date']:%A %d %B %Y}",
        generated=f"{rep['generated']:%H:%M}", verdict=verdict, summary=summary,
        camera=camera, scope=scope, clouds=clouds,
        targets=html_table(TARGET_HEAD, [target_row(i, t) for i, t in
                                         enumerate(rep["targets"][:top], 1)]),
        weather=html_table(WEATHER_HEAD, [weather_row(h) for h in w["hours"]])
        if w else "<p class='dim'>No forecast available.</p>",
    )


def write_html(rep, top, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(rep, top, path.parent))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", type=Date.fromisoformat,
                    help="evening date of the night to plan (default: tonight)")
    ap.add_argument("--top", type=int, default=25, help="targets to list")
    ap.add_argument("--kind", help="only this type, e.g. galaxy, planet, globular")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="made-up weather at the example site; needs no setup")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", metavar="FILE", help="also write an HTML page")
    args = ap.parse_args()

    cfg = config.example() if args.demo else config.load()
    rep = build(cfg, args.date, args.offline, args.demo)
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
