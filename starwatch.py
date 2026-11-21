#!/usr/bin/env python3
"""A watch on a star that dims without warning, Tabby's star first: a short
look on any clear night, measured against the stars round it, and a
warning when it is fainter than usual.

    ./starwatch.py tabby --plan          what it would do; moves nothing
    ./starwatch.py tabby                 point, image for 10 minutes, measure, and say if it is dipping
    ./starwatch.py tabby --measure frames/Tabby/20261020-193000    a night already taken
    ./starwatch.py tabby --history       every night measured so far
    ./starwatch.py tabby --colour        5 minutes each in B and R, each against its own nights

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
their median, and well outside its own scatter, is called a dip. Only
nights of the same camera and filter are compared. The brightness is that
camera's instrumental band put on Gaia's G scale, so it compares night with
night in that band here, not with V-band reports elsewhere. Reporting a dip (AAVSO's
forum, its observation upload) is a person's decision.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
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
TRANSIT_DEPTH = 0.012    # mag: the proposed companion's 1.1% transit (programmes/tabby.toml)
COLOUR_BANDS = ("B", "R")
COLOUR_MINUTES = 5.0     # each band; 30 batches' worth of 4 s frames between them
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


def session_band(session):
    """The camera and filter a session was taken with, from its own frames."""
    import filters
    import stacking
    from astropy.io import fits
    lights = sorted(session.glob("light-*.fits"))
    try:
        header = stacking.load_light(lights[0])[1] if lights else fits.getheader(session / "final.fits")
    except (OSError, IndexError, ValueError) as why:
        # An unknown band must not join any night's baseline.
        raise interface.Refusal("NO_SESSION", f"Cannot read the camera and filter of {session.name}: {why}") from None
    camera, name = filters.band_key(header)
    return {"camera": camera, "filter": name, "band": filters.band(header)}


def series(night):
    """Which nights can be compared. One kept with no camera is the 183C's,
    unfiltered: every night before 21 November 2026."""
    return night.get("camera") or config.LEGACY_CAMERA, night.get("filter") or None


def scale(night):
    return f"{night['band']}, on Gaia's G scale," if night.get("band") else "G"


def judge_night(nights, latest):
    """How the latest night compares with the usual level of the others
    taken with the same camera and filter."""
    before = [n["mag"] for n in nights if n["session"] != latest["session"] and series(n) == series(latest)]
    if len(before) < BASELINE_NIGHTS:
        return {"baseline": None, "dimmer": None, "dipping": False,
                "why": f"{len(before)} other night(s) measured with this camera and filter; "
                       f"a usual level needs {BASELINE_NIGHTS}"}
    usual = float(np.median(before))
    spread = 1.4826 * float(np.median(np.abs(np.array(before) - usual)))
    error = latest["scatter"] / math.sqrt(max(latest["points"], 1))
    dimmer = latest["mag"] - usual
    dipping = dimmer >= WARN and dimmer >= 3 * math.hypot(error, spread)
    why = (f"{dimmer:+.3f} mag against the usual {usual:.3f} (night-to-night spread {spread:.3f}, "
           f"tonight's error {error:.3f})")
    # A dip is the star's alone: not on a night whose check stars were unsteady or moved with it.
    doubt = None
    if latest.get("check_scatter") is not None and latest["check_scatter"] >= WARN:
        doubt = f"the check stars scattered {latest['check_scatter']:.3f} mag that night"
    levels = [n["check_level"] for n in nights if n["session"] != latest["session"]
              and series(n) == series(latest) and n.get("check_level") is not None]
    if doubt is None and latest.get("check_level") is not None and len(levels) >= BASELINE_NIGHTS:
        moved = latest["check_level"] - float(np.median(levels))
        if abs(moved) >= WARN / 2:
            doubt = f"the check stars moved {moved:+.3f} mag themselves"
    if dipping and doubt:
        dipping, why = False, f"{why}; not called a dip: {doubt}"
    return {"baseline": round(usual, 3), "dimmer": round(dimmer, 3), "dipping": bool(dipping),
            "uncertainty": round(math.hypot(error, spread), 4), "why": why}


def colour_change(nights, blue="B", red="R"):
    """Whether the blue band has dimmed more than the red on the same night,
    each against its own usual level. Positive: redder than usual. A colour
    change is evidence about what is in the way, not an answer."""
    def last(band):
        found = [n for n in nights if n.get("filter") == band]
        return found[-1] if found else None
    b, r = last(blue), last(red)
    if b is None or r is None:
        return {"change": None, "why": f"no {blue if b is None else red} night measured yet"}
    if b.get("jd") is None or r.get("jd") is None or abs(b["jd"] - r["jd"]) > 0.5:
        return {"change": None, "why": f"the latest {blue} and {red} are not from the same night"}
    jb, jr = judge_night(nights, b), judge_night(nights, r)
    if jb["dimmer"] is None or jr["dimmer"] is None:
        return {"change": None, "why": f"{blue} and {red} each need {BASELINE_NIGHTS} earlier nights for a usual level"}
    change = jb["dimmer"] - jr["dimmer"]
    error = math.hypot(jb["uncertainty"], jr["uncertainty"])
    return {"change": round(change, 3), "uncertainty": round(error, 4), "significant": bool(abs(change) >= 3 * error),
            "why": f"{blue} {jb['dimmer']:+.3f}, {red} {jr['dimmer']:+.3f}: {blue}-{red} {change:+.3f} ± {error:.3f} mag"}


def transit_reach(nights, depth=TRANSIT_DEPTH):
    """Whether this camera and filter's nights are steady enough to see the
    proposed companion's transit at three sigma: measured from the newest
    night's series, its night-to-night spread with a night's own error."""
    if not nights:
        return {"can_see": None, "why": "no night measured"}
    same = [n for n in nights if series(n) == series(nights[-1])]
    camera, name = series(nights[-1])
    label = f"{camera}, {name or 'unfiltered'}"
    if len(same) < BASELINE_NIGHTS:
        return {"can_see": None, "nights": len(same),
                "why": f"{label}: {len(same)} night(s), {BASELINE_NIGHTS} needed to measure the spread"}
    mags = np.array([n["mag"] for n in same])
    spread = 1.4826 * float(np.median(np.abs(mags - np.median(mags))))
    error = float(np.median([n["scatter"] / math.sqrt(max(n["points"], 1)) for n in same]))
    noise = math.hypot(spread, error)
    return {"can_see": bool(depth >= 3 * noise), "nights": len(same), "noise": round(noise, 4),
            "why": f"{label}: {len(same)} nights, noise {noise:.4f} mag; a {depth:.3f} mag transit needs "
                   f"{depth / 3:.4f} or better"}


def transit_window(nights, windows, depth=TRANSIT_DEPTH):
    """The newest series' nights inside the proposed transit's windows against
    those outside them. Never a detection by itself: 2.3 sigma is all the
    proposal has, and a single site sees only part of a 21-hour transit."""
    if not nights:
        return {"seen": None, "why": "no night measured"}
    same = [n for n in nights if series(n) == series(nights[-1]) and n.get("jd") is not None]
    inside = [n for n in same if any(a <= n["jd"] <= b for a, b in windows)]
    outside = [n for n in same if n not in inside]
    if not inside or len(outside) < BASELINE_NIGHTS:
        return {"seen": None, "inside": len(inside), "outside": len(outside),
                "why": f"{len(inside)} night(s) in a window and {len(outside)} outside; "
                       f"needs 1 and {BASELINE_NIGHTS}"}
    level = np.array([n["mag"] for n in outside])
    usual = float(np.median(level))
    spread = 1.4826 * float(np.median(np.abs(level - usual)))
    change = float(np.median([n["mag"] for n in inside])) - usual
    error = math.hypot(spread, float(np.median([n["scatter"] / math.sqrt(max(n["points"], 1)) for n in inside])))
    return {"seen": bool(change >= max(depth / 2, 3 * error)), "inside": len(inside), "outside": len(outside),
            "change": round(change, 4), "uncertainty": round(error, 4),
            "why": f"{change:+.4f} ± {error:.4f} mag in the window against {len(outside)} nights outside it"}


def check_stars(n, j):
    """How up to 10 stars of about the target's brightness behaved that night:
    (their typical scatter, their typical level against Gaia), so a noisy
    night or a shifted scale is told from a change in the star."""
    stars, mags = np.asarray(n["stars"]), np.asarray(n["mags"])
    near = np.argsort(np.abs(stars[:, 2] - stars[j, 2]))
    near = [i for i in near if i != j and np.isfinite(mags[:, i]).sum() >= 3][:10]
    if not near:
        return None, None
    return (round(float(np.median([np.nanstd(mags[:, i], ddof=1) for i in near])), 4),
            round(float(np.median([np.nanmedian(mags[:, i]) - stars[i, 2] for i in near])), 4))


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
    check_scatter, check_level = check_stars(n, j)
    latest = {"session": session.name, "jd": round(float(np.mean(jd)), 5) if jd else None,
              "mag": round(float(np.median(mags)), 4), "points": int(len(mags)),
              "scatter": round(float(np.std(mags, ddof=1)) if len(mags) > 1 else 0.0, 4),
              "batches": [round(float(m), 4) for m in mags], "check_scatter": check_scatter,
              "check_level": check_level,
              **session_band(session)}
    record = history(s)
    record["nights"] = [x for x in record["nights"] if x["session"] != latest["session"]] + [latest]
    record["nights"].sort(key=lambda x: x["session"])
    path = record_path(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    records.write(path, record, stamp=True)
    verdict = judge_night(record["nights"], latest)
    answer = {"star": s["id"], "name": s["name"], "night": latest, "nights_measured": len(record["nights"]),
              **verdict, "kind": "measured"}
    say(f"{s['id']} on {session.name}: {scale(latest)} {latest['mag']:.3f} ± {latest['scatter']:.3f} "
        f"over {latest['points']} batches")
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
    # The telescope is let go once the frames are in, as every patrol does: the
    # search runs on in the background. On 2 November 2026 the search of
    # Tabby's field waited 8 minutes on a catalogue server with the telescope
    # held, and the night's next target stood still.
    done = patrol_run(_argparse.Namespace(programme=s["programme"], plan=plan, minutes=minutes, analyse=None, sweep=False,
                                          all_history=False, dry_run=dry_run, json=False, release=True, wait=False))
    if plan or dry_run:
        return {"star": s["id"], "name": s["name"], "patrol": done, "kind": "inferred"}
    session = (done.get("analysis") or {}).get("session") or (
        str(patrol.newest_session(s["name"], began) or "") or None)
    if not session:
        raise interface.Refusal("NO_SESSION", f"No frames of {s['id']} were kept.")
    measure_run = measure_run or (lambda: measure(key, session, BIN, say))
    # The frames are in and measuring moves nothing: the next step need not
    # wait for it (21 November 2026: B and R stood idle behind L's measuring).
    import mount
    mount.release()
    return dict(measure_run(), patrol=done)


def colour_look(key, minutes=COLOUR_MINUTES, dry_run=False, say=print, run_command=subprocess.run):
    """The star in B then R, each measured against its own earlier nights.
    Through mount.py and shoot.py, which keep every check; shoot.py moves
    and focuses the filter. The search is left out: this measures one star."""
    import mount
    import patrol
    s = star(key)
    p = patrol.programme(s["programme"])
    extra = ["--dry-run"] if dry_run else []
    frames = math.ceil(minutes * 60 / p["exposure"])

    def step(script, *words):
        done = run_command([sys.executable, str(config.ROOT / script), *words, *extra],
                           env=dict(os.environ, TY_PATROL="1"))
        if done.returncode:
            raise interface.Refusal("INVALID_REQUEST", f"{script} stopped (exit {done.returncode}).")

    if not dry_run:
        mount.claim("starwatch.py --colour")
    try:
        step("mount.py", "goto", s["name"], "--solve")
        sessions = []
        for band in COLOUR_BANDS:
            began = time.time()
            # Frames only: stacking and measuring wait until both bands are
            # in, so neither holds the telescope (21 November 2026).
            step("shoot.py", s["name"], "--filter", band, "--frames", str(frames), "--minutes",
                 f"{minutes * patrol.SHOOT_CAP:g}", "--exposure", str(p["exposure"]), "--gain", str(p["gain"]),
                 "--no-restack")
            if dry_run:
                continue
            session = patrol.newest_session(s["name"], began)
            if session is None:
                raise interface.Refusal("NO_SESSION", f"No {band} frames of {s['id']} were kept.")
            sessions.append(session)
    finally:
        if not dry_run:
            mount.release()
    if dry_run:
        return {"star": s["id"], "name": s["name"], "kind": "inferred"}
    import restack
    measured = []
    for session in sessions:
        if not (session / "final.fits").is_file():
            restack.run(session, say=say)
        measured.append(measure(key, session, BIN, say))
    colour = colour_change(history(s)["nights"], *COLOUR_BANDS)
    say(f"Colour: {colour['why']}")
    return {"star": s["id"], "name": s["name"], "bands": measured, "colour": colour, "kind": "measured"}


def run(args, say=print):
    s = star(args.star)
    if args.colour is not None:
        return colour_look(args.star, args.colour, args.plan or args.dry_run, say)
    if args.transit_reach:
        import patrol
        nights = history(s)["nights"]
        reach = transit_reach(nights)
        windows = [w for watch in patrol.programme(s["programme"]).get("watch", []) for w in watch.get("windows", [])]
        window = transit_window(nights, windows)
        say(reach["why"])
        say(f"In the windows: {window['why']}")
        return {"star": s["id"], "name": s["name"], "transit_reach": reach, "transit_window": window, "kind": "measured"}
    if args.history:
        record = history(s)
        for n in record["nights"]:
            say(f"  {n['session']}: {scale(n)} {n['mag']:.3f} ± {n['scatter']:.3f} ({n['points']} batches)")
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
    ap.add_argument("--colour", type=float, nargs="?", const=COLOUR_MINUTES, metavar="MINUTES",
                    help=f"image in {' then '.join(COLOUR_BANDS)}, this long each (default {COLOUR_MINUTES:g})")
    ap.add_argument("--transit-reach", action="store_true",
                    help="whether the nights so far are steady enough for the proposed 1.1%% transit; only reads")
    ap.add_argument("--bin", type=int, default=BIN, help=f"frames in each point (default {BIN})")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("starwatch", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
