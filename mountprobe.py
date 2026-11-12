#!/usr/bin/env python3
"""Measure the mount's drift and the guide scope's flex, both cameras at once.

Stage 1 of docs/mount-probe.md: passive. Nothing is pulsed and the mount is
never moved: it must already be tracking on the field (GoTo it first with
./ty mount goto TARGET --solve). For --minutes (8):

- the guide camera follows its star every 2 s;
- the main camera takes a short frame in L every 30 s and plate-solves it.

Both become a track of where the scope points, in arcseconds north and west
from the start: the guide star through the kept guider calibration's
directions, the main camera from its solves. From the tracks:

- each camera's drift (arcsec a minute, north and west): the same in both is
  the mount (polar alignment, tracking);
- the difference between them over time: growing, the guide scope is moving
  against the main tube (flex);
- each track's scatter about its straight line: in the guide track alone,
  centroid noise and seeing.

    ./mountprobe.py --dry-run
    ./mountprobe.py                 8 minutes where the mount points now
    ./mountprobe.py --minutes 10 --json

The guide camera is held for the whole run (no guider may be running), the
main camera borrowed like any frame, the filter wheel turned to L.
"""

import argparse
import json
import math
import sys
import threading
import time
from datetime import datetime

import numpy as np

import config
import interface

GUIDE_EXPOSURE = 2.0
GUIDE_GAIN = 400
MAIN_EVERY_S = 30.0
MAIN_EXPOSURE = 2.0
FLEX_PX = 1.0          # guide pixels the two tracks must part by, over the run, for flex to count (docs/mount-probe.md)


def pointing_now():
    """(RA, Dec in degrees, west of the pier) from the handset, which must say
    the mount is tracking: this never moves it."""
    import mount
    scope = mount.Mount(watch=False)
    state = scope.state()
    if state != "tracking":
        raise interface.Refusal("INVALID_REQUEST", f"The mount is {state}, not tracking: GoTo the field first "
                                "(./ty mount goto TARGET --solve), then probe.")
    ra, dec = scope.radec()             # degrees, as the handset believes it: a hint and an origin only
    return ra, dec, scope.west(), scope


def directions(dec, west):
    """Unit vectors (guide px) of a north and a west move of the scope, from
    the kept guider calibration, or None without one usable here."""
    import guider
    cal = guider.load_calibration()
    if not cal:
        return None
    cols, why = guider.reuse(cal, dec, west)
    if cols is None:
        return None
    return {k: np.asarray(cols[k], float) / max(float(np.hypot(*cols[k])), 1e-9) for k in ("north", "west")}


def fit(track):
    """(slope per minute, scatter about the line) of each of north and west
    in a track of (seconds, north, west)."""
    if len(track) < 3:
        return None
    t = np.array([r[0] for r in track], float) / 60.0
    answer = {}
    for k, name in ((1, "north"), (2, "west")):
        v = np.array([r[k] for r in track], float)
        slope, start = np.polyfit(t, v, 1)
        answer[name] = {"drift_per_min": round(float(slope), 2),
                        "scatter": round(float(np.std(v - (slope * t + start))), 2)}
    return answer


def ra_sign(guide, main):
    """Which way the guide camera's RA reads on the sky: (+1 or -1, note).

    The guide track's west comes from the ST4 "west" pulse's direction, and
    what that pin does to the pointing is the mount's own convention, never
    assumed: on 11 November 2026 the first probe read the RA drift as the
    same size both ways but opposite (+13.1"/min west by the plate solves,
    -13.9" by the guide camera), which read as 215" of flex. So the sign is
    taken from the run: when both cameras' RA drift is clearly larger than
    its scatter and they are opposite, the guide camera's RA is turned
    round and that is said. When the drift is too small to tell, it is
    left, and RA flex from it is not to be trusted."""
    g, m = fit(guide), fit(main)
    if not g or not m:
        return 1, ""
    gw, mw = g["west"], m["west"]
    span = (max(r[0] for r in main) - min(r[0] for r in main)) / 60.0
    clear = all(abs(a["drift_per_min"]) * span > 2 * max(a["scatter"], 0.1) for a in (gw, mw))
    if not clear:
        return 1, ("RA drift too small against its scatter to tell which way the guide camera's RA "
                   "reads on the sky: RA flex not measured")
    if gw["drift_per_min"] * mw["drift_per_min"] < 0:
        return -1, ("the ST4 west pulse moves the pointing east as the plate solves see it: "
                    "the guide camera's RA turned round to match")
    return 1, ""


def parting(guide, main):
    """How far the two tracks part over the run, arcsec north and west: the
    guide track's straight line against the main camera's, end against start."""
    g, m = fit(guide), fit(main)
    if not g or not m:
        return None
    span = (max(r[0] for r in main) - min(r[0] for r in main)) / 60.0
    return {k: round((g[k]["drift_per_min"] - m[k]["drift_per_min"]) * span, 1) for k in ("north", "west")}


def probe(minutes, say=print):
    import guidecam
    import guider
    ra0, dec0, west, scope = pointing_now()
    units = directions(dec0, west)
    if units is None:
        raise interface.Refusal("INVALID_REQUEST", "No guider calibration usable here: run the guider once "
                                "(./guidecam.py calibrate) so the guide star's moves can be read as north and west.")
    import subprocess
    turned = subprocess.run([sys.executable, str(config.ROOT / "sxwheel.py"), "move", "L"],
                            capture_output=True, text=True)
    if turned.returncode != 0:
        raise interface.Refusal("INVALID_REQUEST", f"The filter wheel did not turn to L: {turned.stdout.strip()} "
                                f"{turned.stderr.strip()}")
    guide_track, main_track, problems = [], [], []
    # Where the scope really points, from the sky: the handset's position is
    # only a hint, searched near first and then blind. 12 November 2026: the
    # handset was about 50° out in RA and every solve near it failed, so a
    # probe in a clear spell got no main-camera track at all.
    try:
        first = scope.where_really(ra0, dec0, radius=5, exposure=MAIN_EXPOSURE, wider=180)
    except Exception as problem:            # the probe goes on: the solves after it may still work
        first, _ = None, problems.append(f"first plate solve: {problem}")
    if first:
        off = math.degrees(math.acos(min(1.0, math.sin(math.radians(dec0)) * math.sin(math.radians(first["dec"]))
                                         + math.cos(math.radians(dec0)) * math.cos(math.radians(first["dec"]))
                                         * math.cos(math.radians(first["ra"] - ra0)))))
        if off > 1:
            problems.append(f"the handset is {off:.1f}° from where the sky says the scope points; "
                            "the sky's position is used")
        ra0, dec0 = first["ra"], first["dec"]
    stop = threading.Event()
    began = time.time()

    def main_camera():
        """A plate solve every MAIN_EVERY_S, as a track of pointing (arcsec)."""
        while not stop.is_set():
            try:
                found = scope.where_really(ra0, dec0, radius=5, exposure=MAIN_EXPOSURE)
            except Exception as problem:        # a lost frame is a gap in the track, not the end
                found, _ = None, problems.append(f"main camera: {problem}")
            if found:
                mid = found["when"].unix - MAIN_EXPOSURE / 2
                north = (found["dec"] - dec0) * 3600.0
                west_as = -(((found["ra"] - ra0 + 180) % 360) - 180) * 3600.0 * math.cos(math.radians(dec0))
                main_track.append((mid - began, north, west_as))
            stop.wait(MAIN_EVERY_S)

    worker = threading.Thread(target=main_camera, daemon=True)
    with guidecam.GuideCamera(role="probe", size=guidecam.GUIDE_SIZE, speed=guidecam.GUIDE_SPEED) as cam:
        star = guider.first_star(cam, GUIDE_EXPOSURE, GUIDE_GAIN, say)
        where = (star.x, star.y)
        start = None
        worker.start()
        try:
            while time.time() - began < minutes * 60:
                frame, times = cam.timed_frame(GUIDE_EXPOSURE, GUIDE_GAIN)
                found, why = guider.follow(frame, where)
                if found is None:
                    problems.append(f"guide star lost at {times['mid'] - began:.0f} s: {why}")
                    continue
                where = (found.x, found.y)
                start = start or where
                moved = np.subtract(where, start)
                # A star moving the way a north pulse moves it means the scope pointed north.
                north = float(np.dot(moved, units["north"])) * guider.SCALE
                west_as = float(np.dot(moved, units["west"])) * guider.SCALE
                guide_track.append((times["mid"] - began, north, west_as))
        finally:
            stop.set()
            worker.join(timeout=MAIN_EXPOSURE + 60)
    sign, sign_note = ra_sign(guide_track, main_track)
    if sign < 0:
        guide_track = [(t, n, -w) for t, n, w in guide_track]
    if sign_note:
        problems.append(sign_note)
    # Both tracks from the same moment: the guide track is moved to agree
    # with the main camera's first point, so only how they change is compared.
    if main_track and guide_track:
        t0 = main_track[0][0]
        near = min(guide_track, key=lambda r: abs(r[0] - t0))
        guide_track = [(t, n - near[1] + main_track[0][1], w - near[2] + main_track[0][2]) for t, n, w in guide_track]
    return record(guide_track, main_track, problems, ra0, dec0, west, minutes)


def record(guide_track, main_track, problems, ra0, dec0, west, minutes):
    g, m = fit(guide_track), fit(main_track)
    apart = parting(guide_track, main_track)
    import guider
    flex_as = FLEX_PX * guider.SCALE
    reading = []
    if g and m:
        for k in ("north", "west"):
            reading.append(f"{k}: the mount drifts {m[k]['drift_per_min']:+.1f}\"/min by the main camera, "
                           f"{g[k]['drift_per_min']:+.1f}\"/min by the guide camera")
        if apart:
            big = {k: v for k, v in apart.items() if abs(v) > flex_as}
            reading.append(("the guide scope moved against the main tube: " + ", ".join(
                f"{v:+.1f}\" {k}" for k, v in big.items()) + f" over the run (more than one guide pixel, "
                f"{flex_as:.1f}\"; counts once it repeats)") if big else
                f"no flex beyond one guide pixel ({flex_as:.1f}\"): the two tracks part by "
                f"{apart['north']:+.1f}\" north, {apart['west']:+.1f}\" west")
        reading.append(f"guide track scatter {g['north']['scatter']:.1f}\" north, {g['west']['scatter']:.1f}\" "
                       f"west; main {m['north']['scatter']:.1f}\", {m['west']['scatter']:.1f}\"")
    else:
        reading.append("too few points in one of the tracks to compare")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = config.DATA / "frames" / "guide"
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f"probe-{stamp}.json"
    answer = {"stage": 1, "at": stamp, "ra": round(ra0, 4), "dec": round(dec0, 4),
              "side": "west" if west else "east", "minutes": minutes,
              "guide_points": len(guide_track), "main_points": len(main_track),
              "guide": g, "main": m, "parting": apart, "flex_threshold": round(flex_as, 2),
              "problems": problems, "reading": reading, "raw": str(raw)}
    raw.write_text(json.dumps({**answer, "guide_track": guide_track, "main_track": main_track}), encoding="utf-8")
    return answer


def dry_run(minutes):
    ra0, dec0, west, _ = pointing_now()
    units = directions(dec0, west)
    return {"stage": 1, "would": (f"hold the guide camera and follow its star every {GUIDE_EXPOSURE:g} s, turn the "
                                  f"wheel to L and plate-solve the main camera every {MAIN_EVERY_S:g} s, for "
                                  f"{minutes:g} minutes; no pulses, no mount moves"),
            "ra": round(ra0, 4), "dec": round(dec0, 4), "side": "west" if west else "east",
            "calibration_usable": units is not None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=8.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    def work():
        answer = dry_run(args.minutes) if args.dry_run else probe(args.minutes)
        if not args.json:
            if args.dry_run:
                print(f"Would {answer['would']}.")
                print(f"At RA {answer['ra']:.3f}, Dec {answer['dec']:+.3f}, {answer['side']} of the pier; guider "
                      f"calibration {'usable' if answer['calibration_usable'] else 'NOT usable: calibrate first'}.")
            else:
                print(f"Probe at Dec {answer['dec']:+.1f}, {answer['side']} of the pier, {answer['minutes']:g} min: "
                      f"{answer['guide_points']} guide points, {answer['main_points']} main-camera solves")
                for line in answer["reading"]:
                    print(f"  - {line}")
                for line in answer["problems"][:5]:
                    print(f"  ! {line}")
                print(f"  raw tracks: {answer['raw']}")
        return answer

    interface.main("mountprobe", work, args.json)


if __name__ == "__main__":
    main()
