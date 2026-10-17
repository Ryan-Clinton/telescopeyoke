#!/usr/bin/env python3
"""Public alerts worth a look from here tonight: new transients the surveys
have seen, bright enough for this rig, and up in the dark.

    ./brokers.py                      the last 5 days' new transients, brighter than 17.5
    ./brokers.py --days 10 --brighter 18 --json
    ./brokers.py --demo               the example site, for trying it out

The Zwicky Transient Facility photographs the northern sky every few
nights and publishes an alert for every change; brokers sort the alerts.
This asks ALeRCE (alerce.online), whose stamp classifier labels each new
object from its first pictures, for the objects first seen in the last
few days that it calls a supernova, and keeps those that are:

  - bright enough: its last measured magnitude in either filter at or
    brighter than --brighter (this rig reaches about G 17.8 in a night's
    stack of M31; a single field in an hour, about the same);
  - up here in the dark tonight: above the horizon limits and the
    measured skyline, with the Sun below -18° (or the darkest the night
    gets), for at least MIN_MINUTES;
  - not already on the Rochester lists of novae and supernovae, by
    position (within REPORTED_WITHIN arcseconds).

Each comes with its brightest altitude tonight and when, whether it is
brightening, how sure the classifier is, and the links to look it up. The
Transient Name Server needs a key to be asked, so it is not asked: a
person checks there before calling anything new. ZTF's own teams report
most of what it finds, so an alert nobody has reported is rare; the use
of this is mostly to find something real to point at.

Nothing here moves the mount or uses the camera; imaging one is a person's
decision (./mount.py goto RA DEC, then ./shoot.py).
"""
import argparse
import datetime
import time

import numpy as np
import requests
from astropy.time import Time

import config
import interface

ALERCE = "https://api.alerce.online/ztf/v1/objects"
EXPLORER = "https://alerce.online/object/{oid}"
TNS_SEARCH = "https://www.wis-tns.org/search?ra={ra:.5f}&decl={dec:.5f}&radius=5&coords_unit=arcsec"
MOST = 200               # objects asked for: the classifier's surest first
SURE = 0.5               # the classifier's probability at least this
MIN_MINUTES = 30         # up in the dark for at least this long tonight
REPORTED_WITHIN = 5.0    # arcseconds from a reported nova or supernova
PAUSE = 0.2              # seconds between questions to the broker
BANDS = {1: "g", 2: "r", 3: "i"}


def new_objects(days, now=None, get=requests.get, most=MOST):
    """ALeRCE's objects first seen in the last `days` that its stamp
    classifier calls a supernova, surest first."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = Time(now).mjd - days
    out, page = [], 1
    while len(out) < most:
        reply = get(ALERCE + "/", timeout=120, params={
            "classifier": "stamp_classifier", "class": "SN", "firstmjd": f"{since:.3f}",
            "probability": SURE, "page_size": min(100, most), "page": page,
            "order_by": "probability", "order_mode": "DESC"})
        reply.raise_for_status()
        items = reply.json().get("items") or []
        out += [i for i in items if i.get("firstmjd", 0) >= since]
        if len(items) < min(100, most):
            break
        page += 1
    return out[:most]


def brightness(oid, get=requests.get):
    """(the brightest last magnitude, its filter, whether it is brightening)
    from the object's statistics in each filter."""
    reply = get(f"{ALERCE}/{oid}/magstats", timeout=60)
    reply.raise_for_status()
    rows = [r for r in reply.json() if r.get("maglast") is not None]
    if not rows:
        return None, None, None
    best = min(rows, key=lambda r: r["maglast"])
    rising = best.get("magfirst") is not None and best["maglast"] < best["magfirst"] - 0.1
    return round(float(best["maglast"]), 2), BANDS.get(best.get("fid"), "?"), bool(rising)


def up_tonight(night, ra, dec, least=MIN_MINUTES):
    """For each place, (highest altitude, its time, minutes usable) tonight,
    or None where it is not up in the dark long enough."""
    from sky import STEP_MIN
    alt, az = night.altaz_fixed(ra, dec)
    out = []
    for a, z in zip(alt, az):
        usable = night.dark & night.future & (a >= night.horizon(z, night.min_alt))
        minutes = int(usable.sum()) * STEP_MIN
        if minutes < least:
            out.append(None)
            continue
        i = int(np.argmax(np.where(usable, a, -99)))
        out.append((round(float(a[i]), 1), night.local(i), minutes))
    return out


def reported_near(ra, dec, rows, within=REPORTED_WITHIN):
    """The name of a reported nova or supernova at the place, or None."""
    import vet
    for r in rows:
        if vet.separation(ra, dec, r["ra"], r["dec"]) <= within:
            return r["name"]
    return None


def search(cfg, days, brighter, say=print, get=requests.get, reported=None, now=None):
    """The answer: the alerts worth a look from here tonight."""
    import sky
    import vet
    now = now or datetime.datetime.now(datetime.timezone.utc)
    objects = new_objects(days, now, get)
    night = sky.Night(cfg, now=now)
    ras = np.array([o["meanra"] for o in objects], float)
    decs = np.array([o["meandec"] for o in objects], float)
    up = up_tonight(night, ras, decs) if len(objects) else []
    if reported is None:
        year = now.year
        reported = vet.reported((year - 1, year))
    picked, faint, down, known = [], 0, 0, 0
    for o, when in zip(objects, up):
        if when is None:
            down += 1
            continue
        mag, band, rising = brightness(o["oid"], get)
        time.sleep(PAUSE)
        if mag is None or mag > brighter:
            faint += 1
            continue
        name = reported_near(o["meanra"], o["meandec"], reported)
        if name:
            known += 1
        alt, at, minutes = when
        picked.append({"oid": o["oid"], "ra": round(float(o["meanra"]), 5), "dec": round(float(o["meandec"]), 5),
                       "mag": mag, "band": f"ZTF {band}", "brightening": rising,
                       "first_seen": Time(o["firstmjd"], format="mjd").datetime.strftime("%Y-%m-%d %H:%M"),
                       "detections": int(o.get("ndet") or 0),
                       "probability": round(float(o.get("probability") or 0), 2),
                       "highest": alt, "highest_at": at.strftime("%H:%M"), "minutes_up": minutes,
                       "reported": name, "tns": "not asked: check by hand",
                       "links": {"alerce": EXPLORER.format(oid=o["oid"]),
                                 "tns": TNS_SEARCH.format(ra=o["meanra"], dec=o["meandec"])}})
    picked.sort(key=lambda p: (p["reported"] is not None, p["mag"]))
    answer = {"broker": "ALeRCE", "days": days, "brighter": brighter, "asked": len(objects),
              "not_up": down, "too_faint": faint, "already_reported": known, "worth_a_look": picked,
              "night": str(night.date), "kind": "measured"}
    say(f"{len(objects)} new transients from ALeRCE in {days:g} days; {down} not up in the dark here tonight, "
        f"{faint} fainter than {brighter:g}; {len(picked)} left, {known} of them already on the Rochester lists")
    for p in picked:
        say(f"  {p['oid']}  {p['ra']:.5f} {p['dec']:+.5f}  {p['band']} {p['mag']:.2f}"
            f"{', brightening' if p['brightening'] else ''}  {p['highest']:.0f}° high at {p['highest_at']}"
            f"  {'reported as ' + p['reported'] if p['reported'] else 'not on the Rochester lists'}")
    if picked:
        say("Check the Transient Name Server (the links in --json) before calling anything new. Imaging one is "
            "your decision: ./mount.py goto RA DEC, then ./shoot.py.")
    return answer


def run(args, say=print):
    cfg = config.example() if args.demo else config.load()
    return search(cfg, args.days, args.brighter, say)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=5.0, help="first seen in the last this many days (default 5)")
    ap.add_argument("--brighter", type=float, default=17.5, help="last magnitude at least this bright (default 17.5)")
    ap.add_argument("--demo", action="store_true", help="the example site instead of config.toml")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("brokers", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
