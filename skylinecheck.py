#!/usr/bin/env python3
"""The planner's skyline set against what a night's frames show.

    ./skylinecheck.py 2026-11-03            every session of that night (the evening's date)
    ./skylinecheck.py 2026-11-03 --json

For every frame of every session, where the target was (altitude and
bearing at the frame's time, from its catalogue or mosaic place: a GoTo
centres it by plate solve to within a fifth of a frame, about 0.13
degrees) and which of the planner's limits it was under, kept apart:

- clear: above every limit;
- margin: above the measured skyline but within its margin ([horizon]
  margin), so the planner counts it as down for image quality, not
  because anything is in the way;
- skyline: at or below the measured skyline itself, a physical obstruction
  if the skyline is right there;
- floor or blocked: under [horizon] min_altitude or a blocked direction.

With each, how many frames the run kept. Frames kept below the measured
skyline say the skyline is too high there; frames kept as well inside the
margin as in the clear say the margin cost them. It reads the frame logs,
the site and the skyline; it changes nothing, and the margin is the
person's setting.
"""
import argparse
from datetime import date

import config
import interface

CLASSES = ("clear", "margin", "skyline", "blocked", "floor")


def site_and_horizon(cfg=None):
    cfg = cfg or (config.load() if config.FILE.exists() else config.example())
    return cfg["site"], cfg["horizon"]


def limits_at(az, h):
    """(floor, blocked, skyline, skyline with its margin) in degrees at
    each bearing in `az` (a numpy array)."""
    import numpy as np
    import horizon
    floor = np.full_like(az, float(h["min_altitude"]))
    blocked = np.zeros_like(az)
    for b in h.get("blocked", []):
        lo, hi = b["from"] % 360, b["to"] % 360
        inside = (az >= lo) & (az <= hi) if lo <= hi else (az >= lo) | (az <= hi)
        blocked[inside] = np.maximum(blocked[inside], b["altitude"])
    skyline = h.get("skyline") or []
    raw = horizon.limit(skyline, az, 0.0) if skyline else np.zeros_like(az)
    padded = horizon.limit(skyline, az, h.get("margin", 0.0)) if skyline else np.zeros_like(az)
    return floor, blocked, raw, padded


def classify(alt, floor, blocked, raw, padded):
    """The limit a frame was under, as CLASSES names it: the strictest one
    it falls below, the measured skyline before its margin."""
    if alt <= floor:
        return "floor"
    if alt <= blocked:
        return "blocked"
    if alt <= raw:
        return "skyline"
    if alt <= padded:
        return "margin"
    return "clear"


def where(field, times, site):
    """(alt, az) arrays of a field's place at unix times, or None if it
    can't be found."""
    import numpy as np
    import astropy.units as u
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord
    from astropy.time import Time
    import mount
    try:
        t = mount.find_target(field)
    except (Exception, interface.Refusal):
        return None
    loc = EarthLocation(lat=site["latitude"] * u.deg, lon=site["longitude"] * u.deg,
                        height=site.get("elevation_m", 0) * u.m)
    frame = AltAz(obstime=Time(np.asarray(times), format="unix"), location=loc)
    aa = SkyCoord(ra=t["ra"] * u.deg, dec=t["dec"] * u.deg).transform_to(frame)
    return aa.alt.deg, aa.az.deg


def check(evening, data=None, cfg=None):
    import history
    site, h = site_and_horizon(cfg)
    rows = [s for s in history.sessions(data=data) if s["night"] == evening.isoformat()]
    out = []
    for s in rows:
        frames = [f for f in s["log"] if isinstance(f.get("taken"), (int, float))]
        if not frames:
            continue
        pos = where(s["field"], [f["taken"] for f in frames], site)
        if pos is None:
            out.append({"field": s["field"], "session": s["folder"].name, "found": False})
            continue
        alt, az = pos
        floor, blocked, raw, padded = limits_at(az, h)
        counts = {c: {"frames": 0, "kept": 0} for c in CLASSES}
        for i, f in enumerate(frames):
            c = classify(alt[i], floor[i], blocked[i], raw[i], padded[i])
            counts[c]["frames"] += 1
            counts[c]["kept"] += bool(f.get("accepted"))
        out.append({"field": s["field"], "session": s["folder"].name, "found": True,
                    "alt": [round(float(alt.min()), 1), round(float(alt.max()), 1)],
                    "az": [round(float(az.min()), 1), round(float(az.max()), 1)],
                    "skyline_there": [round(float(raw.min()), 1), round(float(raw.max()), 1)],
                    "limits": counts, "verdict": verdict(counts)})
    totals = {c: {"frames": sum(r["limits"][c]["frames"] for r in out if r.get("found")),
                  "kept": sum(r["limits"][c]["kept"] for r in out if r.get("found"))} for c in CLASSES}
    return {"night": evening.isoformat(), "margin": h.get("margin", 0.0), "min_altitude": h["min_altitude"],
            "skyline_points": len(h.get("skyline") or []), "sessions": out, "totals": totals,
            "verdict": verdict(totals)}


def share(c):
    return c["kept"] / c["frames"] if c["frames"] else None


def verdict(counts):
    """What the frames say about the limits, in words."""
    said = []
    sky, margin, clear = (counts[k] for k in ("skyline", "margin", "clear"))
    if sky["frames"]:
        if sky["kept"]:
            said.append(f"{sky['kept']} of {sky['frames']} frames kept at or below the measured skyline: "
                        "it is too high there, or the target was off its centre")
        else:
            said.append(f"none of {sky['frames']} frames at or below the measured skyline kept: it holds")
    if margin["frames"]:
        m, c = share(margin), share(clear)
        if c is not None and m is not None and m >= c - 0.1:
            said.append(f"{margin['kept']} of {margin['frames']} frames inside the margin kept, as well as in the "
                        f"clear ({100 * c:.0f}%): the margin cost these frames nothing in quality")
        else:
            said.append(f"{margin['kept']} of {margin['frames']} frames inside the margin kept"
                        + (f", against {100 * c:.0f}% in the clear" if c is not None else ""))
    return "; ".join(said) or "every frame clear of every limit"


def run(args, say=print):
    result = check(date.fromisoformat(args.night))
    say(f"Night of {result['night']}: margin {result['margin']:g} degrees above {result['skyline_points']} "
        f"measured skyline points, lowest altitude {result['min_altitude']:g}")
    for r in result["sessions"]:
        if not r["found"]:
            say(f"  {r['field']} {r['session'][9:13]}: not in the catalogue")
            continue
        parts = ", ".join(f"{c} {v['kept']}/{v['frames']}" for c, v in r["limits"].items() if v["frames"])
        say(f"  {r['field']} {r['session'][9:13]}: alt {r['alt'][0]}-{r['alt'][1]}, az {r['az'][0]}-{r['az'][1]}, "
            f"skyline {r['skyline_there'][0]}-{r['skyline_there'][1]}; kept/frames {parts}")
    say(f"All: {result['verdict']}")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("night", help="the evening's date (YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("skylinecheck", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
