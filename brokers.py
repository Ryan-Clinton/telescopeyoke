#!/usr/bin/env python3
"""Public alerts worth a look from here tonight: new transients the surveys
have seen, bright enough for this rig, and up in the dark.

    ./brokers.py                      the last 5 days' new transients, brighter than 17.5
    ./brokers.py --days 10 --brighter 18 --json
    ./brokers.py --demo               the example site, for trying it out
    ./brokers.py --unreported         the last 30 days' bright ones nobody has reported, up here or not
    ./brokers.py --follow ZTF26acaznbf --plan     what following one would do; moves nothing
    ./brokers.py --follow ZTF26acaznbf            point at it, image it, and measure it

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
    position (within REPORTED_WITHIN arcseconds);
  - real by ZTF's deep-learning real-or-bogus score (drb) on its best
    detection, at least REAL: the stamp classifier calls some ghosts by
    bright stars a supernova.

With --unreported it looks back further (30 days unless --days says
otherwise), keeps those up here or not, and lists only the ones on
neither Rochester list: the search for something the surveys saw and
nobody wrote up. Such a one is rare, and still has to be looked for on
the Transient Name Server by hand: the Rochester lists leave out most
transients nobody has classified yet, which the Server has.

Each comes with its brightest altitude tonight and when, whether it is
brightening, how sure the classifier is, and the links to look it up. The
Transient Name Server needs a key to be asked, so it is not asked: a
person checks there before calling anything new. ZTF's own teams report
most of what it finds, so an alert nobody has reported is rare; the use
of this is mostly to find something real to point at.

--follow is the confirmation picture, on a person's yes: running it is
the yes. It keeps the object's place under its name (cache/transients.json,
so mount.py and shoot.py know it), then runs the patrol on it, with every
check the patrol makes (the motion lock first; the sky, the darkness, the
focus): a GoTo, the frames, the stack and its depth. Its first night
becomes its field's reference, so a second visit is subtracted from the
first. Then the object is measured in each stack at its place (forced.py)
beside ZTF's last magnitude. A patrol already running is stopped by a
person first; the patrol is run again afterwards. Unfiltered against ZTF's
g or r, and on a galaxy's light where it sits on one: a rough match, not
a measurement to report. Without --follow nothing here moves the mount or
uses the camera.
"""
import argparse
import datetime
import json
import time

import numpy as np
import requests
from astropy.time import Time

import config
import interface
import records

ALERCE = "https://api.alerce.online/ztf/v1/objects"
EXPLORER = "https://alerce.online/object/{oid}"
TNS_SEARCH = "https://www.wis-tns.org/search?ra={ra:.5f}&decl={dec:.5f}&radius=5&coords_unit=arcsec"
MOST = 200               # objects asked for: the classifier's surest first
SURE = 0.5               # the classifier's probability at least this
MIN_MINUTES = 30         # up in the dark for at least this long tonight
MONTH = 30.0             # days looked back with --unreported
MOST_MONTH = 1000        # objects asked for with --unreported
REPORTED_WITHIN = 5.0    # arcseconds from a reported nova or supernova
PAUSE = 0.2              # seconds between questions to the broker
REAL = 0.5               # ZTF's deep real-or-bogus score at least this on some detection
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


def realness(oid, get=requests.get):
    """ZTF's real-or-bogus score on the object's best detection: the deep
    one (drb) where there is one, else the older rb; None if neither."""
    reply = get(f"{ALERCE}/{oid}/detections", timeout=60)
    reply.raise_for_status()
    scores = [d.get("drb") if d.get("drb") is not None else d.get("rb") for d in reply.json()]
    scores = [float(x) for x in scores if x is not None]
    return max(scores) if scores else None


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


def transients_file():
    return config.DATA / "cache" / "transients.json"


def keep_target(oid, ra, dec, note):
    """The object's place under its name, for mount.py and shoot.py."""
    path = transients_file()
    kept = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    kept[oid] = {"ra": round(float(ra), 6), "dec": round(float(dec), 6), **note}
    path.parent.mkdir(parents=True, exist_ok=True)
    records.write(path, kept)


def follow(oid, minutes, plan=False, dry_run=False, say=print, get=requests.get, patrol_run=None, measure=None):
    """Point at one of the broker's objects, image it through the patrol, and
    measure it there. `patrol_run` and `measure` stand in for the patrol
    and forced photometry (for the tests)."""
    import argparse as _argparse
    import forced
    import patrol
    reply = get(f"{ALERCE}/{oid}", timeout=60)
    reply.raise_for_status()
    o = reply.json()
    if not o or o.get("meanra") is None:
        raise interface.Refusal("TARGET_UNKNOWN", f"ALeRCE has no object {oid}.")
    mag, band, rising = brightness(oid, get)
    ztf = {"mag": mag, "band": f"ZTF {band}", "brightening": rising,
           "last_seen": Time(o["lastmjd"], format="mjd").datetime.strftime("%Y-%m-%d %H:%M")}
    keep_target(oid, o["meanra"], o["meandec"], {"kept_by": "brokers.py --follow", **ztf})
    say(f"{oid} at RA {o['meanra']:.5f} Dec {o['meandec']:+.5f}: {ztf['band']} {mag} when last seen, {ztf['last_seen']} UTC")
    patrol_run = patrol_run or (lambda a: patrol.run(a, say))
    done = patrol_run(_argparse.Namespace(programme=oid, plan=plan, minutes=minutes, analyse=None, sweep=False,
                                          all_history=False, dry_run=dry_run, json=False))
    answer = {"follow": oid, "ra": round(float(o["meanra"]), 5), "dec": round(float(o["meandec"]), 5), "ztf": ztf,
              "patrol": done, "measured": None, "kind": "measured"}
    if plan or dry_run:
        return answer
    measure = measure or (lambda: forced.history(oid, o["meanra"], o["meandec"], say))
    rows = [r for r in measure() if r.get("in_picture")]
    answer["measured"] = rows[-1] if rows else None
    if answer["measured"] and answer["measured"].get("mag") is not None:
        say(f"Measured here: G {answer['measured']['mag']:.2f} ± {answer['measured']['error']:.2f} (unfiltered, "
            f"approximately Gaia G) beside {ztf['band']} {mag}")
    elif answer["measured"]:
        say(f"Not seen here: fainter than G {answer['measured'].get('limit')}")
    return answer


def search(cfg, days, brighter, say=print, get=requests.get, reported=None, now=None, unreported=False):
    """The answer: the alerts worth a look from here tonight; with
    `unreported`, the bright ones on neither Rochester list, up or not."""
    import sky
    import vet
    now = now or datetime.datetime.now(datetime.timezone.utc)
    objects = new_objects(days, now, get, MOST_MONTH if unreported else MOST)
    night = sky.Night(cfg, now=now)
    ras = np.array([o["meanra"] for o in objects], float)
    decs = np.array([o["meandec"] for o in objects], float)
    up = up_tonight(night, ras, decs) if len(objects) else []
    if reported is None:
        year = now.year
        reported = vet.reported((year - 1, year))
    picked, faint, down, known, bogus = [], 0, 0, 0, 0
    for o, when in zip(objects, up):
        if when is None and not unreported:
            down += 1
            continue
        mag, band, rising = brightness(o["oid"], get)
        time.sleep(PAUSE)
        if mag is None or mag > brighter:
            faint += 1
            continue
        real = realness(o["oid"], get)
        time.sleep(PAUSE)
        if real is not None and real < REAL:
            bogus += 1
            continue
        name = reported_near(o["meanra"], o["meandec"], reported)
        if name:
            known += 1
            if unreported:
                continue
        alt, at, minutes = when or (None, None, 0)
        picked.append({"oid": o["oid"], "ra": round(float(o["meanra"]), 5), "dec": round(float(o["meandec"]), 5),
                       "mag": mag, "band": f"ZTF {band}", "brightening": rising,
                       "first_seen": Time(o["firstmjd"], format="mjd").datetime.strftime("%Y-%m-%d %H:%M"),
                       "detections": int(o.get("ndet") or 0),
                       "probability": round(float(o.get("probability") or 0), 2),
                       "real_bogus": None if real is None else round(real, 2),
                       "highest": alt, "highest_at": at and at.strftime("%H:%M"), "minutes_up": minutes,
                       "reported": name, "tns": "not asked: check by hand",
                       "links": {"alerce": EXPLORER.format(oid=o["oid"]),
                                 "tns": TNS_SEARCH.format(ra=o["meanra"], dec=o["meandec"])}})
    picked.sort(key=lambda p: (p["reported"] is not None, p["mag"]))
    answer = {"broker": "ALeRCE", "unreported": unreported, "days": days, "brighter": brighter, "asked": len(objects),
              "not_up": down, "too_faint": faint, "bogus": bogus, "already_reported": known, "worth_a_look": picked,
              "night": str(night.date), "kind": "measured"}
    if unreported:
        say(f"{len(objects)} new transients from ALeRCE in {days:g} days; {faint} fainter than {brighter:g}, "
            f"{bogus} bogus by ZTF's score, {known} on the Rochester lists; {len(picked)} on neither list")
    else:
        say(f"{len(objects)} new transients from ALeRCE in {days:g} days; {down} not up in the dark here tonight, "
            f"{faint} fainter than {brighter:g}, {bogus} bogus by ZTF's score; {len(picked)} left, {known} of them "
            f"already on the Rochester lists")
    for p in picked:
        up_here = (f"{p['highest']:.0f}° high at {p['highest_at']}" if p["highest"] is not None
                   else "not up here tonight")
        say(f"  {p['oid']}  {p['ra']:.5f} {p['dec']:+.5f}  {p['band']} {p['mag']:.2f}"
            f"{', brightening' if p['brightening'] else ''}  {up_here}"
            f"  {'reported as ' + p['reported'] if p['reported'] else 'not on the Rochester lists'}")
    if picked:
        say("Check the Transient Name Server (the links in --json) before calling anything new. Imaging one is "
            "your decision: ./mount.py goto RA DEC, then ./shoot.py.")
    return answer


def run(args, say=print):
    if args.follow:
        return follow(args.follow, args.minutes, args.plan, args.dry_run, say)
    cfg = config.example() if args.demo else config.load()
    days = args.days if args.days is not None else (MONTH if args.unreported else 5.0)
    return search(cfg, days, args.brighter, say, unreported=args.unreported)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, help="first seen in the last this many days (default 5; 30 with --unreported)")
    ap.add_argument("--brighter", type=float, default=17.5, help="last magnitude at least this bright (default 17.5)")
    ap.add_argument("--unreported", action="store_true",
                    help="the bright ones on neither Rochester list, up here tonight or not")
    ap.add_argument("--follow", metavar="OID", help="point at this object, image it through the patrol, and measure it")
    ap.add_argument("--minutes", type=float, default=20.0, help="with --follow: how long to image (default 20)")
    ap.add_argument("--plan", action="store_true", help="with --follow: what it would do; moves nothing")
    ap.add_argument("--dry-run", action="store_true", help="with --follow: every step as it would be run")
    ap.add_argument("--demo", action="store_true", help="the example site instead of config.toml")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("brokers", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
