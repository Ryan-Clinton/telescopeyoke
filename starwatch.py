#!/usr/bin/env python3
"""A watch on a star that dims without warning, Tabby's star first: a short
look on any clear night, measured against the stars round it, and a
warning when it is fainter than usual.

    ./starwatch.py tabby --plan          what it would do; moves nothing
    ./starwatch.py tabby                 point, image for 10 minutes, measure, and say if it is dipping
    ./starwatch.py tabby --measure frames/Tabby/20261020-193000    a night already taken
    ./starwatch.py tabby --history       every night measured so far

KIC 8462852 (Tabby's star, or Boyajian's star, V 11.7 in Cygnus) dimmed by
up to 22% in irregular dips of days in the Kepler spacecraft's four years
of pictures, found by volunteers in 2015; nobody has fully explained it.
Amateurs watch it for the AAVSO because its dips come without warning, and
the first to see one lets the big telescopes take its spectrum while it
lasts: in 2017 that is how the dips named Elsie, Celeste, Skara Brae and
Angkor were caught.

`starwatch.py NAME` keeps the star by name (cache/transients.json, so
./mount.py goto Tabby knows it), runs the patrol on it (patrol.py, with
every check it makes: the motion lock first) for --minutes, then measures
it (in programmes/NAME.toml's 4 s frames, short enough not to fill the
camera's wells on a star of G 11.8) as variables.py measures every star: batches of --bin frames, each put
on Gaia's scale by the other stars in the picture. The night's median goes
into frames/FIELD/starwatch.json beside the nights before; once there are
BASELINE_NIGHTS of them, a night WARN magnitudes or more fainter than
their median, and well outside its own scatter, is called a dip. The
brightness is unfiltered on Gaia's G scale, so it compares night with
night here, not with V-band reports elsewhere. Reporting a dip (AAVSO's
forum, its observation upload) is a person's decision.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np

import config
import interface
import records

STARS = {
    "tabby": {"name": "Tabby", "programme": "tabby", "id": "KIC 8462852", "aka": "Tabby's star, Boyajian's star",
              "ra": 301.564392, "dec": 44.456839, "v": 11.7},
}
MINUTES = 10.0
BIN = 10
BRIGHTEST = 10.5         # G: trusted in its programme's 4 s frames (16 s ones fill the wells near G 13)
WARN = 0.03              # magnitudes fainter than usual that make a dip
BASELINE_NIGHTS = 3      # nights measured before a usual level is trusted
WITHIN = 5.0             # arcseconds from the star's place to a measured star


def star(key):
    found = STARS.get(key.lower())
    if found is None:
        raise interface.Refusal("TARGET_UNKNOWN", f"No watched star '{key}': {', '.join(STARS)}.")
    return found


def record_path(s):
    import stacking
    return config.DATA / "frames" / stacking.folder_name(s["name"]) / "starwatch.json"


def history(s):
    path = record_path(s)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"star": s["id"], "nights": []}


def judge_night(nights, latest):
    """How the latest night compares with the usual level of the others."""
    before = [n["mag"] for n in nights if n["session"] != latest["session"]]
    if len(before) < BASELINE_NIGHTS:
        return {"baseline": None, "dimmer": None, "dipping": False,
                "why": f"{len(before)} other night(s) measured; a usual level needs {BASELINE_NIGHTS}"}
    usual = float(np.median(before))
    spread = 1.4826 * float(np.median(np.abs(np.array(before) - usual)))
    error = latest["scatter"] / math.sqrt(max(latest["points"], 1))
    dimmer = latest["mag"] - usual
    dipping = dimmer >= WARN and dimmer >= 3 * math.hypot(error, spread)
    return {"baseline": round(usual, 3), "dimmer": round(dimmer, 3), "dipping": bool(dipping),
            "why": f"{dimmer:+.3f} mag against the usual {usual:.3f} (night-to-night spread {spread:.3f}, "
                   f"tonight's error {error:.3f})"}


def measure(key, session, size=BIN, say=print, night=None):
    """The star in one night's frames, added to its record."""
    import variables
    import vet
    s = star(key)
    session = Path(session)
    n = night or variables.night(session, s["name"], size, say, brightest=BRIGHTEST)
    stars = np.asarray(n["stars"])
    if not len(stars):
        raise interface.Refusal("NO_SESSION", f"No star measured in {session.name}.")
    near = vet.separation(s["ra"], s["dec"], stars[:, 0], stars[:, 1])
    j = int(np.argmin(near))
    if near[j] > WITHIN:
        raise interface.Refusal("NO_SESSION", f"{s['id']} is not among the stars measured in {session.name} (nearest "
                                              f"{near[j]:.0f}\" away): outside the picture, too bright or crowded.")
    mags = np.asarray(n["mags"])[:, j]
    mags = mags[np.isfinite(mags)]
    if not len(mags):
        raise interface.Refusal("NO_SESSION", f"{s['id']} was not measured in any batch of {session.name}.")
    jd = [t for t in n["jd"] if t is not None]
    latest = {"session": session.name, "jd": round(float(np.mean(jd)), 5) if jd else None,
              "mag": round(float(np.median(mags)), 4), "points": int(len(mags)),
              "scatter": round(float(np.std(mags, ddof=1)) if len(mags) > 1 else 0.0, 4),
              "batches": [round(float(m), 4) for m in mags]}
    record = history(s)
    record["nights"] = [x for x in record["nights"] if x["session"] != latest["session"]] + [latest]
    record["nights"].sort(key=lambda x: x["session"])
    path = record_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    records.write(path, record, stamp=True)
    verdict = judge_night(record["nights"], latest)
    answer = {"star": s["id"], "name": s["name"], "night": latest, "nights_measured": len(record["nights"]),
              **verdict, "kind": "measured"}
    say(f"{s['id']} on {session.name}: G {latest['mag']:.3f} ± {latest['scatter']:.3f} over {latest['points']} batches")
    say(("DIPPING: " if verdict["dipping"] else "  ") + verdict["why"])
    if verdict["dipping"]:
        say("Look again tomorrow night, and see the AAVSO's forum for whether others see it too; telling them is "
            "your decision.")
    return answer


def look(key, minutes=MINUTES, plan=False, dry_run=False, say=print, patrol_run=None, measure_run=None):
    """Point at the star, image it through the patrol, and measure it."""
    import argparse as _argparse
    import brokers
    import patrol
    s = star(key)
    brokers.keep_target(s["name"], s["ra"], s["dec"], {"kept_by": "starwatch.py", "id": s["id"]})
    patrol_run = patrol_run or (lambda a: patrol.run(a, say))
    began = __import__("time").time()
    done = patrol_run(_argparse.Namespace(programme=s["programme"], plan=plan, minutes=minutes, analyse=None, sweep=False,
                                          all_history=False, dry_run=dry_run, json=False))
    if plan or dry_run:
        return {"star": s["id"], "name": s["name"], "patrol": done, "kind": "inferred"}
    session = (done.get("analysis") or {}).get("session") or (
        str(patrol.newest_session(s["name"], began) or "") or None)
    if not session:
        raise interface.Refusal("NO_SESSION", f"No frames of {s['id']} were kept.")
    measure_run = measure_run or (lambda: measure(key, session, BIN, say))
    return dict(measure_run(), patrol=done)


def run(args, say=print):
    s = star(args.star)
    if args.history:
        record = history(s)
        for n in record["nights"]:
            say(f"  {n['session']}: G {n['mag']:.3f} ± {n['scatter']:.3f} ({n['points']} batches)")
        return {"star": s["id"], "name": s["name"], "nights": record["nights"], "kind": "measured"}
    if args.measure:
        return measure(args.star, args.measure, args.bin, say)
    return look(args.star, args.minutes, args.plan, args.dry_run, say)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("star", help=f"the watched star: {', '.join(STARS)}")
    ap.add_argument("--minutes", type=float, default=MINUTES, help=f"how long to image (default {MINUTES:g})")
    ap.add_argument("--plan", action="store_true", help="what it would do; moves nothing")
    ap.add_argument("--dry-run", action="store_true", help="every step as it would be run")
    ap.add_argument("--measure", metavar="SESSION", help="only measure a night already taken")
    ap.add_argument("--history", action="store_true", help="every night measured so far")
    ap.add_argument("--bin", type=int, default=BIN, help=f"frames in each point (default {BIN})")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("starwatch", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
