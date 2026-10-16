#!/usr/bin/env python3
"""A discovery patrol of one field, from pointing the telescope to the
morning's answer: is there anything new?

    ./patrol.py m31-novae --plan        readiness and what it would do; moves nothing
    ./patrol.py m31-novae               point, image, and look for anything new
    ./patrol.py m31-novae --minutes 15  a shorter look
    ./patrol.py --analyse frames/M31/20261020-221500   the looking-for part, on a night already taken
    ./patrol.py m31-novae --dry-run     every step as it would be run, nothing moved or taken

A programme is a file in programmes/ (target, exposure, gain, minutes);
a target name works too. The patrol:

1. checks it is ready: the motion lock, a kept reference for the field
   (reference.py), and how deep the stack should reach from the last focus
   (depth.py --model), saying "refocus first" if the stars are too soft;
2. points the telescope (mount.py goto) and images the field (shoot.py,
   which re-centres and stacks as it goes, and makes the final stack);
3. measures how deep the night's stack reached (depth.py --plant),
   subtracts the reference (difference.py), and vets every candidate
   (vet.py);
4. ends with a short answer, kept as patrol.json: how deep it reached, how
   many candidates, what each was, and the unexplained ones with their
   cut-outs (patrol-N.png: the night, the reference, the difference).

It moves the mount only through mount.py and shoot.py, with every check
they make: a MOTION_LOCKED file stops it before anything moves. A person
starts it; it never decides to move by itself. Nothing is reported to
anyone: an unexplained candidate is for a person to look at.
"""
import argparse
import json
import math
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import numpy as np

import config
import interface

ROOT = Path(__file__).parent
PROGRAMMES = ROOT / "programmes"
SOFT = 16.8        # a 5-minute stack predicted shallower than this: refocus first
FOCUS_STALE = 6.0  # hours: focus older than this is from another night or the cooling since


def programme(name):
    """A programme's settings: from programmes/NAME.toml, or a bare target."""
    path = PROGRAMMES / f"{name}.toml"
    if path.exists():
        with path.open("rb") as f:
            p = tomllib.load(f)
        p.setdefault("name", name)
        return p
    return {"name": name, "target": name, "exposure": 16, "gain": 1500, "minutes": 30}


def readiness(p):
    """What is known before anything moves: the lock, the reference, the
    expected depth. Each item says whether it stops the patrol."""
    import depth
    import focus
    import mount
    import reference
    items = []
    locked = mount.LOCK_FILE.exists()
    items.append({"what": "motion lock", "ok": not locked, "stops": locked,
                  "detail": mount.LOCK_FILE.read_text(encoding="utf-8").strip() if locked else "none"})
    items += sky_now(p)
    ref = reference.newest(p["target"])
    items.append({"what": "reference", "ok": ref is not None, "stops": False,
                  "detail": str(ref) if ref else f"none kept: tonight's stack can become one "
                                                 f"(./reference.py {p['target']} --make)"})
    if focus.FOCUS_FILE.exists():
        f = json.loads(focus.FOCUS_FILE.read_text(encoding="utf-8"))
        hours = (time.time() - f.get("saved", 0)) / 3600
        stale = hours > FOCUS_STALE
        items.append({"what": "focus", "ok": not stale, "stops": False,
                      "detail": f"last focused {hours:.1f} h ago" + ("; focus first (focus.py --motor)" if stale else "")})
    else:
        items.append({"what": "focus", "ok": False, "stops": False, "detail": "never measured; focus first"})
    # What the last measured stack of this field reached, at its star size
    # and sky; the model says what tonight's length would give if the
    # focus and sky are as good. The focus routine's own short frames do
    # not say how wide a long stack's stars will be.
    last = None
    for record in sorted((config.DATA / "frames" / p["target"]).glob("*/depth.json"), key=lambda r: r.stat().st_mtime):
        r = json.loads(record.read_text(encoding="utf-8"))
        if r.get("fwhm_arcsec") and r.get("sky_mag_per_arcsec2"):
            last = r
    try:
        model, _ = depth.fit(depth.measurements())
    except interface.Refusal:
        model = None
    if last and model:
        five = depth.predict(model, last["fwhm_arcsec"], last["sky_mag_per_arcsec2"], 300)
        whole = depth.predict(model, last["fwhm_arcsec"], last["sky_mag_per_arcsec2"], 60 * p["minutes"])
        items.append({"what": "expected depth", "ok": five >= SOFT, "stops": False, "kind": "inferred",
                      "detail": f"with stars {last['fwhm_arcsec']}\" and a {last['sky_mag_per_arcsec2']} sky as last "
                                f"measured: half found at about G {five:.1f} in 5 minutes, {whole:.1f} in "
                                f"{p['minutes']:g} (± {model['scatter']:.1f})"
                                + ("" if five >= SOFT else "; shallow: sharper focus or a darker sky would help")})
    else:
        items.append({"what": "expected depth", "ok": True, "stops": False, "kind": "not known",
                      "detail": "no measured stack of this field to predict from"})
    return items


DARK = -12.0       # the Sun below this: dark enough to patrol
DAY = -6.0         # the Sun above this: daylight, and the patrol does not start


def sky_now(p, when=None):
    """Whether the field can be reached and whether it is dark, now, and how
    long the run would last before dawn or the mount's limit ends it."""
    import mount
    import polaris
    import shoot
    from astropy import units as u
    from astropy.time import Time
    try:
        site = config.load()["site"]
    except (SystemExit, KeyError, OSError):
        return [{"what": "sky", "ok": True, "stops": False, "kind": "not known",
                 "detail": "no site in config.toml: altitude and darkness not checked"}]
    items = []
    try:
        plan = mount.plan_goto(p["target"], site)
        items.append({"what": "field", "ok": True, "stops": False, "kind": "inferred",
                      "detail": f"{p['target']} at altitude {plan['altitude_deg']:.0f}°, hour angle "
                                f"{plan['hour_angle_hours']:+.1f} h, {plan['pier_side']} side"})
    except interface.Refusal as refused:
        items.append({"what": "field", "ok": False, "stops": True, "kind": "inferred", "detail": refused.message})
    sun = polaris.sun_now(site, when)[0]
    items.append({"what": "darkness", "ok": sun < DARK, "stops": sun > DAY, "kind": "inferred",
                  "detail": f"the Sun at {sun:.0f}°" + ("" if sun < DARK else
                                                       "; too light to patrol" if sun > DAY else "; twilight")})
    # Would dawn or the mount's limit end the run before its time is up?
    start = when or Time.now()
    for minute in range(10, int(p["minutes"]) + 10, 10):
        why = shoot.night_over(p["target"], site, start + min(minute, p["minutes"]) * u.min)
        if why:
            items.append({"what": "time", "ok": False, "stops": False, "kind": "inferred",
                          "detail": f"the run would end after about {minute - 10} of {p['minutes']:g} minutes: {why}"})
            break
    return items


def steps(p, dry_run=False):
    """The commands the patrol runs to point and image, in order."""
    frames = max(1, round(60 * p["minutes"] / p["exposure"]))
    extra = ["--dry-run"] if dry_run else []
    return [[sys.executable, str(ROOT / "mount.py"), "goto", p["target"], *extra],
            [sys.executable, str(ROOT / "shoot.py"), p["target"], "--frames", str(frames),
             "--exposure", str(p["exposure"]), "--gain", str(p["gain"]), *extra]]


def newest_session(target, after):
    import restack
    sessions = [s for s in restack.all_sessions(target) if s.stat().st_mtime >= after - 5]
    return sessions[-1] if sessions else None


def analyse(session, say=print, chain=None):
    """Depth, difference and vetting on a session, and the answer. `chain`
    replaces the three steps (for the tests)."""
    import depth
    import difference
    import vet
    session = Path(session)
    name = session.parent.name
    answer = {"session": str(session), "object": name}
    run = chain or {
        "depth": lambda: depth.run(argparse.Namespace(target=str(session), near=name, plant=True, sweep=False,
                                                      trials=6), say=quiet(say)),
        "difference": lambda: difference.run(argparse.Namespace(new=str(session), reference=None, near=name,
                                                                plant=0), say=quiet(say)),
        "vet": lambda: vet.run(argparse.Namespace(session=str(session), offline=False, no_halves=False),
                               say=quiet(say)),
    }
    for step in ("depth", "difference", "vet"):
        say(f"{step}...")
        try:
            answer[step] = run[step]()
        except interface.Refusal as stopped:
            answer[step] = {"refused": stopped.code_name, "message": stopped.message}
            say(f"  {step} stopped: {stopped.message}")
            break
    if "candidates" in answer.get("vet", {}):
        measure = (chain or {}).get("measure") or (lambda: tonight(session, answer.get("depth", {})))
        answer["followed"] = follow(name, session.name, answer["vet"]["candidates"], measure)
    answer["summary"] = summary(answer)
    if chain is None and "vet" in answer and "candidates" in answer["vet"]:
        answer["pictures"] = cutouts(session, answer["vet"])
    (session / "patrol.json").write_text(json.dumps(answer, indent=1, default=str), encoding="utf-8")
    for line in answer["summary"]:
        say(line)
    return answer


def tonight(session, measured):
    """A way to measure any place in tonight's stack, for following up the
    candidates on file: (ra, dec) -> (mag, error, limit)."""
    from astropy.io import fits
    import depth
    import forced
    lum = depth.brightness(fits.getdata(session / "final.fits"))
    wcs = depth.plate(lum, session.parent.name)
    rng = np.random.default_rng(3)

    def at(ra, dec):
        x, y = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
        if not (40 <= x < lum.shape[1] - 40 and 40 <= y < lum.shape[0] - 40):
            return None, None, None
        return forced.measure_at(lum, x, y, measured.get("fwhm_px", 4.0), measured["zeropoint"], rng)
    return at


def follow(name, night, vetted, measure):
    """Add tonight's candidates to the field's book, and measure every open
    one in tonight's stack. Returns the open candidates as they now stand."""
    import candidates
    book = candidates.load(name)
    candidates.add_night(book, night, vetted)
    if any(k["open"] and not any(n["night"] == night for n in k["nights"]) for k in book["candidates"]):
        candidates.follow_up(book, night, measure(), None)
    candidates.save(book)
    return [{"id": k["id"], "ra": k["ra"], "dec": k["dec"], "seen_on": candidates.nights_seen(k),
             "of": len(k["nights"]), "tonight": next((n for n in k["nights"] if n["night"] == night), None)}
            for k in book["candidates"] if k["open"]]


def quiet(say):
    """Pass on a step's own lines indented, so the patrol's own stand out."""
    return lambda line: say("    " + str(line))


def summary(a):
    """The patrol's answer in a few lines."""
    lines = []
    d = a.get("depth", {})
    if "zeropoint" in d:
        half = d.get("completeness", {}).get("all", {}).get("mag_50")
        lines.append(f"Depth: half of planted stars found at G {half}; stars {d.get('fwhm_arcsec')}\", "
                     f"sky {d.get('sky_mag_per_arcsec2')} mag per square arcsecond.")
    diff = a.get("difference", {})
    if "candidates" in diff:
        lines.append(f"Subtracted from the reference: {len(diff['candidates'])} candidates above "
                     f"{diff.get('threshold', 5):g} sigma ({diff.get('fading_peaks')} fading peaks as a "
                     "yardstick for noise).")
    v = a.get("vet", {})
    if "candidates" in v:
        verdicts = {}
        for c in v["candidates"]:
            key = c["verdict"].split(":")[0].split(" (")[0]
            verdicts[key] = verdicts.get(key, 0) + 1
        for key, n in sorted(verdicts.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {n} {key}")
        left = [c for c in v["candidates"] if c["verdict"] == "unexplained: worth a person's eyes"]
        if left:
            lines.append(f"Unexplained: {len(left)}. Look at each before anything else; a real one is seen "
                         "again on another night.")
            for c in left:
                lines.append(f"  {c['score']:.1f} sigma at RA {c['ra']:.5f} Dec {c['dec']:+.5f}, about "
                             f"G {c.get('mag')}, both halves {c.get('halves')}")
        else:
            lines.append("Nothing unexplained: nothing new tonight that this rig could see.")
    for k in a.get("followed", []):
        t = k["tonight"] or {}
        what = ("seen again" if t.get("seen") and t.get("forced") else "found tonight" if t.get("seen")
                else f"not seen (fainter than G {t.get('limit')})" if t else "not measured")
        lines.append(f"On file: {k['id']}, seen on {k['seen_on']} of {k['of']} nights; tonight {what}"
                     + ("  <- seen on more than one night: look hard" if k["seen_on"] >= 2 else ""))
    for step in ("depth", "difference", "vet"):
        if isinstance(a.get(step), dict) and "refused" in a[step]:
            lines.append(f"Stopped at {step}: {a[step]['message']}")
    return lines


def cutouts(session, vetted, half=32):
    """For each unexplained candidate, a picture: the night, the reference
    and the difference side by side."""
    from astropy.io import fits
    from astropy.wcs import WCS
    from PIL import Image
    import depth
    import difference
    record = json.loads((session / "candidates.json").read_text(encoding="utf-8"))
    ref = depth.brightness(fits.getdata(record["reference"]))
    score = fits.getdata(session / "difference.fits")
    ref_wcs = WCS(fits.getheader(session / "difference.fits"))
    new = depth.brightness(fits.getdata(record["new"]))
    new_wcs = depth.plate(new, session.parent.name)
    laid, _, _ = difference.refine(difference.onto(np.where(new == 0, np.nan, new), new_wcs, ref.shape, ref_wcs), ref)
    made = []
    for n, c in enumerate(e for e in vetted["candidates"] if e["verdict"].startswith("unexplained")):
        x, y = c["x"], c["y"]
        panels = []
        for image, scale in ((laid, None), (ref, None), (score, (-6.0, 10.0))):
            cut = np.nan_to_num(image[max(y - half, 0):y + half, max(x - half, 0):x + half])
            lo, hi = scale or np.percentile(cut, [2, 99.8])
            panels.append(np.clip((cut - lo) / (hi - lo + 1e-9) * 255, 0, 255).astype(np.uint8))
        height = min(p.shape[0] for p in panels)
        gap = np.full((height, 4), 255, np.uint8)
        row = np.hstack([panels[0][:height], gap, panels[1][:height], gap, panels[2][:height]])
        path = session / f"patrol-{n + 1}.png"
        Image.fromarray(row).resize((row.shape[1] * 4, row.shape[0] * 4), Image.NEAREST).save(path)
        made.append(str(path))
    return made


def run(args, say=print):
    if args.analyse:
        return analyse(args.analyse, say)
    p = programme(args.programme)
    if args.minutes:
        p["minutes"] = args.minutes
    items = readiness(p)
    say(f"Patrol {p['name']}: {p['target']}, {p['minutes']} minutes of {p['exposure']} s frames at gain {p['gain']}")
    for item in items:
        say(f"  {'ok ' if item['ok'] else 'NO '} {item['what']}: {item['detail']}")
    plan = steps(p, dry_run=args.dry_run)
    for cmd in plan:
        say("  then: " + " ".join(Path(c).name if c.endswith(".py") else c for c in cmd[1:]))
    say("  then: depth.py --plant, difference.py against the reference, vet.py, and the answer")
    answer = {"programme": p, "readiness": items, "steps": [" ".join(c[1:]) for c in plan]}
    if args.plan:
        return answer
    stopping = [i for i in items if i["stops"]]
    if any(i["what"] == "motion lock" for i in stopping):
        raise interface.Refusal("MOTION_LOCKED", "The motion lock is in place: nothing will move. "
                                + next(i["detail"] for i in stopping if i["what"] == "motion lock"))
    if stopping:
        raise interface.Refusal("INVALID_REQUEST", "Not now: " + "; ".join(i["detail"] for i in stopping))
    began = time.time()
    for cmd in plan:
        say("$ " + " ".join(Path(c).name if c.endswith(".py") else c for c in cmd[1:]))
        done = subprocess.run(cmd)
        if done.returncode != 0:
            raise interface.Refusal("INVALID_REQUEST", f"{Path(cmd[1]).name} stopped (exit {done.returncode}); "
                                    "the patrol stops with it.")
    if args.dry_run:
        return answer
    session = newest_session(p["target"], began)
    if session is None:
        raise interface.Refusal("NO_SESSION", "shoot.py kept no frames tonight.")
    answer["analysis"] = analyse(session, say)
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("programme", nargs="?", help="a programme in programmes/ (m31-novae), or a target name")
    ap.add_argument("--plan", action="store_true", help="readiness and what it would do; moves nothing")
    ap.add_argument("--minutes", type=float, help="how long to image (default: the programme's)")
    ap.add_argument("--analyse", metavar="SESSION", help="only look for anything new in a session already taken")
    ap.add_argument("--dry-run", action="store_true", help="every step as it would be run; nothing moved or taken")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    if not args.programme and not args.analyse:
        ap.error("name a programme, or --analyse SESSION")
    interface.main("patrol", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
