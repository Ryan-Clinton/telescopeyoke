#!/usr/bin/env python3
"""What a light round the house does to the sky the telescope sees.

    ./lighttest.py frames/M31-P3/20261018-220720 --on 22:07:09 --off 22:08:53
    ./lighttest.py SESSION --on 22:07:09 --off 22:08:53 --json

Switch a light on while a run is imaging, note the times (local, to the
second), switch it off, and give the session and the times. Each kept
frame's own record (frames.jsonl: sky level, how many stars, their total
brightness, their width) is put in one of three groups by its exposure:
wholly while the light was on, wholly while it was off, or across a switch
(left out). It says how much the light raised the sky, against the
frame-to-frame scatter of the frames with it off, and whether the stars
changed: a light that dims or blurs the stars is worse than one that only
brightens the sky.

18 October 2026, ralphie-side: the kitchen light raised the sky 7% with the
stars unchanged; the upstairs bathroom and the utility room lights made no
measurable change (docs/nights/2026-10-18/tests.md, measured by hand before
this command). Reads only: nothing moves, and the camera is not used.
"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import interface

MEASURES = (("background", "sky level"), ("stars", "stars"), ("flux", "star brightness"), ("fwhm", "star width"))
CLEAR = 3.0          # a change this many times the frames' own scatter is a real one


def moment(text, day):
    """A local HH:MM[:SS] on the session's night: after midnight belongs to the next day."""
    parts = [int(p) for p in text.split(":")]
    t = day.replace(hour=parts[0], minute=parts[1], second=parts[2] if len(parts) > 2 else 0, microsecond=0)
    if t < day - timedelta(hours=6):
        t += timedelta(days=1)
    return t.timestamp()


def groups(rows, on, off, exposure):
    """The kept frames wholly while the light was on, and wholly while it was off."""
    lit, dark = [], []
    for r in rows:
        if not r.get("accepted") or not r.get("taken"):
            continue
        start, end = r["taken"] - exposure, r["taken"]
        if start >= on and end <= off:
            lit.append(r)
        elif end <= on or start >= off:
            dark.append(r)
    return lit, dark


def compare(lit, dark):
    """Each measure with the light on and off: medians, the change in percent,
    and the change against the off frames' own scatter."""
    out = {}
    for key, name in MEASURES:
        a = np.array([r[key] for r in lit if r.get(key) is not None], float)
        b = np.array([r[key] for r in dark if r.get(key) is not None], float)
        if len(a) < 1 or len(b) < 2:
            continue
        on, off = float(np.median(a)), float(np.median(b))
        scatter = 1.4826 * float(np.median(np.abs(b - off))) or float(np.std(b)) or 1e-9
        out[key] = {"name": name, "on": round(on, 2), "off": round(off, 2),
                    "change_percent": round(100 * (on - off) / off, 1) if off else None,
                    "sigmas": round((on - off) / scatter, 1)}
    return out


def verdict(found):
    sky, flux = found.get("background"), found.get("flux")
    if sky is None:
        return "Not enough frames on both sides of the switches to say."
    words = (f"raises the sky by {sky['change_percent']:.0f}% ({sky['sigmas']:.0f} times the frames' own scatter)"
             if abs(sky["sigmas"]) >= CLEAR else "makes no measurable change to the sky")
    if flux and abs(flux["sigmas"]) >= CLEAR:
        words += f", and changes the stars' brightness by {flux['change_percent']:+.0f}%"
    else:
        words += ", with the stars unchanged"
    return "The light " + words + "."


def run(args, say=print):
    session = Path(args.session)
    log = session / "frames.jsonl"
    if not log.exists():
        raise interface.Refusal("NO_SESSION", f"No frames.jsonl in {session}.")
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    plan = json.loads((session / "session.json").read_text(encoding="utf-8")) if (session / "session.json").exists() \
        else {}
    exposure = float(plan.get("exposure") or args.exposure or 0)
    day = datetime.strptime(session.name[:15], "%Y%m%d-%H%M%S")
    on, off = moment(args.on, day), moment(args.off, day)
    if off <= on:
        raise interface.Refusal("INVALID_REQUEST", "--off must come after --on.")
    lit, dark = groups(rows, on, off, exposure)
    found = compare(lit, dark)
    answer = {"session": session.name, "on": args.on, "off": args.off, "exposure": exposure,
              "frames_on": len(lit), "frames_off": len(dark), "measures": found, "verdict": verdict(found)}
    say(f"{session.name}: {len(lit)} frames with the light on, {len(dark)} with it off "
        f"(frames across a switch left out)")
    for m in found.values():
        say(f"  {m['name']:<16} on {m['on']:>10g}   off {m['off']:>10g}   {m['change_percent']:+.1f}%  "
            f"({m['sigmas']:+.1f} times the scatter)")
    say(answer["verdict"])
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", help="the session folder the run was imaging into")
    ap.add_argument("--on", required=True, help="when the light went on, local HH:MM:SS")
    ap.add_argument("--off", required=True, help="when it went off, local HH:MM:SS")
    ap.add_argument("--exposure", type=float, help="seconds, if the session does not say")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("lighttest", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
