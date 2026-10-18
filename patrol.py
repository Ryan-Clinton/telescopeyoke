#!/usr/bin/env python3
"""A discovery patrol of one field, from pointing the telescope to the
morning's answer: is there anything new?

    ./patrol.py m31-novae --plan        readiness and what it would do; moves nothing
    ./patrol.py m31-novae               point, image, and look for anything new
    ./patrol.py m31-novae --minutes 15  a shorter look
    ./patrol.py --analyse frames/M31/20261020-221500   the looking-for part, on a night already taken
    ./patrol.py m31-novae --dry-run     every step as it would be run, nothing moved or taken
    ./patrol.py --sweep                 search every session of the last 3 days not yet searched
    ./patrol.py --sweep --all-history   every session there has ever been

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

Every session is searched, not only the patrol's: when shoot.py or
restack.py finishes a stack of a field that has a reference (and the
session is not one the reference was made from), it starts
`patrol.py --analyse` on it in the background at low priority, its lines
kept in the session's patrol.log. --sweep searches what that missed, and
--sweep --all-history every session kept, for when the search improves.
"""
import argparse
import datetime
import json
import math
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import numpy as np

import config
import interface
import records

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
    ref, owner = reference.for_field(p["target"])
    items.append({"what": "reference", "ok": ref is not None, "stops": False,
                  "detail": (str(ref) if owner == p["target"] else
                             f"{owner}'s ({ref}) where it overlaps; tonight's stack becomes the panel's own"
                             if ref else f"none kept: tonight's stack can become one "
                                         f"(./reference.py {p['target']} --make)")})
    when = focus.last_focused()
    if when is not None:
        hours = (time.time() - when) / 3600
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
    base = p["target"].rsplit("-P", 1)[0] if "-P" in p["target"] else p["target"]
    for folder in dict.fromkeys((p["target"], base)):     # the panel's own stacks, else the object's
        for record in sorted((config.DATA / "frames" / folder).glob("*/depth.json"), key=lambda r: r.stat().st_mtime):
            r = json.loads(record.read_text(encoding="utf-8"))
            if r.get("fwhm_arcsec") and r.get("sky_mag_per_arcsec2"):
                last = r
        if last:
            break
    try:
        model, _ = depth.fit(depth.measurements())
    except interface.Refusal:
        model = None
    if last and model:
        five = depth.predict(model, last["fwhm_arcsec"], last["sky_mag_per_arcsec2"], 300)
        whole = depth.predict(model, last["fwhm_arcsec"], last["sky_mag_per_arcsec2"], 60 * p["minutes"])
        items.append({"what": "expected depth", "ok": five >= SOFT, "stops": False, "kind": "inferred",
                      "detail": f"with stars {last['fwhm_arcsec']}\" and a {last['sky_mag_per_arcsec2']} sky as last "
                                f"measured: half found at about G {five:.1f} in 5 minutes"
                                + ("" if p["minutes"] == 5 else f", {whole:.1f} in {p['minutes']:g}")
                                + f" (± {model['scatter']:.1f})"
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
             "--exposure", str(p["exposure"]), "--gain", str(p["gain"]),
             *(["--dither", str(p["dither"])] if p.get("dither") else []), *extra]]


def newest_session(target, after):
    import restack
    sessions = [s for s in restack.all_sessions(target) if s.stat().st_mtime >= after - 5]
    return sessions[-1] if sessions else None


def analyse(session, say=print, chain=None, both_halves=True, alerting=True):
    """Depth, difference and vetting on a session, and the answer. `chain`
    replaces the three steps (for the tests)."""
    import depth
    import difference
    import vet
    session = Path(session)
    name = session.parent.name
    answer = {"session": str(session), "object": name}
    count = (lambda: len(vet.restack_frames(session))) if chain is None else chain.get("frames", lambda: vet.HALVES_FROM)
    frames = count()
    if frames < vet.HALVES_FROM:
        # Too few to check the halves of the night, or for the stack to throw
        # out a cosmic ray or a satellite: what it finds is mostly those.
        message = (f"too few frames to search: {frames}, and checking each half of the night needs "
                   f"{vet.HALVES_FROM}")
        answer["depth"] = {"refused": "INVALID_REQUEST", "message": message}
        say(f"  {message}")
        answer["summary"] = summary(answer)
        records.write(session / "patrol.json", answer, schema="patrol", stamp=True, default=str)
        return answer
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
        shallow = too_shallow(answer[step]) if step == "depth" else None
        if shallow:
            answer["difference"] = {"refused": "INVALID_REQUEST", "message": shallow}
            say(f"  difference stopped: {shallow}")
            break
    if "candidates" in answer.get("vet", {}):
        measure = (chain or {}).get("measure") or (lambda: tonight(session, answer.get("depth", {})))
        answer["followed"] = follow(name, session.name, answer["vet"]["candidates"], measure, both_halves)
    answer["summary"] = summary(answer)
    if chain is None and "vet" in answer and "candidates" in answer["vet"]:
        answer["pictures"] = cutouts(session, answer["vet"])
    records.write(session / "patrol.json", answer, schema="patrol", stamp=True, default=str)
    for line in answer["summary"]:
        say(line)
    if chain is None and alerting:
        answer["alerted"] = alert(name, session, answer, say)
    return answer


def unexplained(result):
    """The vetted candidates nothing explained."""
    return [c for c in (result.get("vet") or {}).get("candidates", []) if c["verdict"].startswith("unexplained")]


def alert(name, session, result, say=print, packet=None, send=None):
    """The person told at once of the unexplained candidates: each one's
    report packet made (report.py), and the text and pictures sent
    (notify.py). Returns the book's IDs alerted. `packet` and `send` stand
    in for report.py and notify.py (for the tests)."""
    import notify
    vetted = unexplained(result)
    if not vetted:
        return []
    followed = result.get("followed") or []
    ids = [f["id"] for f in followed
           if any(abs(f["ra"] - c["ra"]) < 1e-3 and abs(f["dec"] - c["dec"]) < 1e-3 for c in vetted)]
    if packet is None:
        import report
        packet = lambda wanted: report.run(argparse.Namespace(id=wanted, quick=False, json=False), say=lambda *_: None)
    made = []
    for wanted in ids:
        try:
            packet(wanted)
            made.append(wanted)
        except Exception as error:      # a packet is a help; the alert still goes
            say(f"  no report packet for {wanted}: {error}")
    text = notify.candidate_alert(name, session, vetted, followed, result.get("pictures", []), made)
    pictures = [(path, f"{name} candidate {n}: the night, the reference, the difference")
                for n, path in enumerate(result.get("pictures", []), 1)]
    sent = (send or notify.send)(text, pictures=pictures, say=say)
    if sent:
        say(f"  alert sent: {len(vetted)} unexplained")
    return ids


CONFIRM_MINUTES = 10   # a second look at a field with an unexplained candidate, while the telescope is there


def second_look(p, name, say=print, dry_run=False, run_command=None, search=None):
    """More frames of the same field, at once, searched as the first were:
    a real object is there again, most false ones are not. No GoTo: the
    telescope is already there. It dithers before the first frame, so a
    candidate falls on other pixels than the first time: a defect of the
    camera does not move with the sky, a real object does."""
    frames = max(1, round(60 * CONFIRM_MINUTES / p["exposure"]))
    cmd = [sys.executable, str(ROOT / "shoot.py"), name, "--frames", str(frames), "--exposure", str(p["exposure"]),
           "--gain", str(p["gain"]), "--dither-first", *(["--dry-run"] if dry_run else [])]
    say(f"== a second look at {name}: {CONFIRM_MINUTES:g} minutes more")
    say("$ " + " ".join(Path(c).name if c.endswith(".py") else c for c in cmd[1:]))
    began = time.time()
    run_command = run_command or (lambda c: subprocess.run(c, stdout=sys.stdout, env=dict(os.environ, TY_PATROL="1")))
    done = run_command(cmd)
    if done.returncode != 0 or dry_run:
        return {"stopped": f"shoot.py stopped (exit {done.returncode})"} if done.returncode else {"dry_run": True}
    session = newest_session(name, began)
    if session is None:
        return {"stopped": "no frames kept"}
    return (search or (lambda s: analyse(s, say, both_halves=p.get("both_halves", True))))(session)


SEARCH_FLOOR = 16.0   # G: a stack whose half-found depth is brighter than this is not searched


def too_shallow(measured):
    """Why a stack is too shallow to search, or None. Such a stack could
    not show a nova in M31 (they peak near G 17.5), and its soft, faint
    stars do not subtract cleanly from a deep reference: the stars
    themselves come up as candidates."""
    half = (measured or {}).get("completeness", {}).get("all", {}).get("mag_50")
    if half is None or half >= SEARCH_FLOOR:
        return None
    return (f"too shallow to search: half of planted stars found at G {half}, brighter than G {SEARCH_FLOOR:g}; "
            f"a nova in M31 peaks near G {NOVA_PEAK[0]:g}")


def tonight(session, measured):
    """A way to measure any place in tonight's stack, for following up the
    candidates on file: (ra, dec) -> (mag, error, limit)."""
    from astropy.io import fits
    import depth
    import forced
    lum = depth.brightness(fits.getdata(session / "final.fits"))
    wcs = depth.plate(lum, session.parent.name)
    rng = np.random.default_rng(3)
    # The light above the reference, where there is one: the galaxy and the
    # faint stars under a candidate are not its light.
    above = forced.above_reference(lum, wcs, session.parent.name, lambda image: depth.plate(image, session.parent.name))
    if above is not None:
        lum = np.nan_to_num(above)

    def at(ra, dec):
        x, y = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
        if not (40 <= x < lum.shape[1] - 40 and 40 <= y < lum.shape[0] - 40):
            return None, None, None
        return forced.measure_at(lum, x, y, measured.get("fwhm_px", 4.0), measured["zeropoint"], rng)
    return at


def follow(name, night, vetted, measure, both_halves=True):
    """Add tonight's candidates to the field's book, and measure every open
    one in tonight's stack. Returns the open candidates as they now stand."""
    import candidates

    def tonight_too(book):
        candidates.add_night(book, night, vetted, both_halves)
        if any(k["open"] and not any(n["night"] == night for n in k["nights"]) for k in book["candidates"]):
            candidates.follow_up(book, night, measure(), None)
        return book
    book = candidates.change(name, tonight_too)
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
        left = [c for c in v["candidates"] if c["verdict"].startswith("unexplained")]
        if left:
            lines.append(f"Unexplained: {len(left)}. Look at each before anything else; a real one is seen "
                         "again on another night.")
            for c in left:
                lines.append(f"  {c['score']:.1f} sigma at RA {c['ra']:.5f} Dec {c['dec']:+.5f}, about "
                             f"G {c.get('mag')}, both halves {c.get('halves')}")
                for clue in c.get("clues", []):
                    lines.append(f"    clue: {clue}")
        else:
            lines.append("Nothing unexplained: nothing new tonight that this rig could see.")
    for k in a.get("followed", []):
        t = k["tonight"] or {}
        what = ("seen again" if t.get("seen") and t.get("forced") else "found tonight" if t.get("seen")
                else f"not seen (fainter than G {t['limit']})" if t.get("limit") is not None
                else "not seen, and no limit there (off the stack's edge, or too little light to measure)" if t
                else "not measured")
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


# --- which fields, in what order ---------------------------------------------------

NOVA_PEAK = (17.5, 1.0)   # G: the middle and spread of M31 novae's peaks, for the completeness (estimated)
DEBT_DAYS = 10.0          # a field unwatched longer than this counts as this long
OVERHEAD = 1.5            # minutes a field costs beyond its frames: the GoTo and the plate solve
KNOWN_FRESH = 86400       # seconds the list of known novae is kept before it is fetched again


def fields(p, keep=True):
    """The fields a programme covers: its target, or its mosaic's panels,
    planned (as ./mosaic.py would) and kept if none is yet."""
    if not p.get("mosaic"):
        return [p["target"]]
    import mosaic
    import mount
    target = mount.find_target(p["mosaic"])
    kept = mosaic.load(target["id"])
    if kept is None:
        columns, rows = (int(v) for v in str(p.get("grid", "4x2")).lower().split("x"))
        kept = mosaic.plan(target, columns, rows)
        if keep:
            mosaic.folder().mkdir(parents=True, exist_ok=True)
            records.write(mosaic.path(target["id"]), kept)
    return [panel["id"] for panel in kept["panels"]]


def known_novae(ra, dec, within=2.0):
    """Where novae have been reported near a field, this year and last
    (the Rochester lists, kept for a day), as (ra, dec) rows."""
    import vet
    cache = config.DATA / "cache" / "known-novae.json"
    rows = None
    if cache.exists() and time.time() - cache.stat().st_mtime < KNOWN_FRESH:
        rows = json.loads(cache.read_text(encoding="utf-8"))
    if rows is None:
        year = time.gmtime().tm_year
        try:
            rows = [[r["ra"], r["dec"]] for r in vet.reported((year - 1, year))]
        except Exception:
            rows = []
        if rows:
            cache.parent.mkdir(parents=True, exist_ok=True)
            records.write(cache, rows, indent=None)
    return [(a, d) for a, d in rows if vet.separation(ra, dec, a, d) <= within * 3600]


def completeness(depth50, peak=NOVA_PEAK):
    """The share of novae whose peak is brighter than a stack's half-found
    magnitude (estimated, from a typical spread of peaks)."""
    mean, spread = peak
    return 0.5 * (1 + math.erf((depth50 - mean) / (spread * math.sqrt(2))))


def priorities(p, names, known, expected, last_seen, now=None):
    """Each field's priority, highest first: the novae reported in it (plus
    one, so an empty field is not ruled out), the share of novae it should
    catch at its expected depth, and the days since it was last watched,
    over the minutes it costs. `expected` and `last_seen` are functions of
    a field's name: its expected half-found magnitude, and when (seconds)
    it was last imaged, or None."""
    import mosaic
    import mount
    now = now or time.time()
    width, height = mosaic.field()
    reach = math.sqrt(width * height / math.pi) * 3600       # a circle of the frame's area, arcsec
    import vet
    rows = []
    for name in names:
        t = mount.find_target(name)
        inside = sum(1 for a, d in known if vet.separation(t["ra"], t["dec"], a, d) <= reach)
        depth50 = expected(name)
        share = completeness(depth50)
        seen = last_seen(name)
        days = DEBT_DAYS if seen is None else min(DEBT_DAYS, max(0.0, (now - seen) / 86400))
        minutes = p["minutes"] + OVERHEAD
        rows.append({"field": name, "novae_reported": inside, "expected_mag_50": round(depth50, 2),
                     "share_of_novae": round(share, 3), "days_unwatched": round(days, 1),
                     "minutes": minutes, "priority": round((inside + 1) * share * days / minutes, 4),
                     "kinds": {"novae_reported": "reported", "expected_mag_50": "inferred",
                               "share_of_novae": "estimated", "days_unwatched": "measured"}})
    return sorted(rows, key=lambda r: -r["priority"])


def fit(rows, minutes_left):
    """The fields that fit in the night, highest priority first."""
    chosen, used = [], 0.0
    for r in rows:
        if minutes_left is None or used + r["minutes"] <= minutes_left:
            chosen.append(r)
            used += r["minutes"]
    return chosen


def night_left(p, site, when=None, longest=480):
    """Minutes until dawn or the mount's limit ends imaging the programme's
    target, up to `longest`; None if unknown."""
    import shoot
    from astropy import units as u
    from astropy.time import Time
    start = when or Time.now()
    for minute in range(10, longest + 10, 10):
        if shoot.night_over(p.get("mosaic") or p["target"], site, start + minute * u.min):
            return minute - 10
    return longest


def expected_depth(p):
    """A function: a field's expected half-found magnitude in the
    programme's minutes, from its own last measured stack, else the
    object's, through the depth model; the programme's guess if neither."""
    import depth
    try:
        model, _ = depth.fit(depth.measurements())
    except interface.Refusal:
        model = None

    def last_of(name):
        found = None
        for record in sorted((config.DATA / "frames" / name).glob("*/depth.json"), key=lambda r: r.stat().st_mtime):
            r = json.loads(record.read_text(encoding="utf-8"))
            if r.get("fwhm_arcsec") and r.get("sky_mag_per_arcsec2"):
                found = r
        return found

    def expected(name):
        base = name.rsplit("-P", 1)[0] if "-P" in name else name
        last = last_of(name) or last_of(base)
        if model and last:
            return depth.predict(model, last["fwhm_arcsec"], last["sky_mag_per_arcsec2"], 60 * p["minutes"])
        return 17.0
    return expected


def last_watched(name):
    """When a field was last imaged (seconds), from its newest session, or None."""
    import restack
    sessions = restack.all_sessions(name)
    return sessions[-1].stat().st_mtime if sessions else None


def run(args, say=print):
    if getattr(args, "sweep", False):
        return sweep(args.all_history, say=say)
    if args.analyse:
        session = Path(args.analyse)
        result = analyse(args.analyse, say)
        # A panel's first night becomes its reference whichever way it was
        # imaged: through the patrol or by shoot.py alone (18 October 2026,
        # panel 8 imaged directly was left with nothing to search against).
        first_reference(session.parent.name, session, say)
        return result
    p = programme(args.programme)
    if args.minutes:
        p["minutes"] = args.minutes
    names = fields(p)
    order = None
    if len(names) > 1:
        import mount
        centre = mount.find_target(p["mosaic"])
        rows = priorities(p, names, known_novae(centre["ra"], centre["dec"]), expected_depth(p), last_watched)
        try:
            left = night_left(p, config.load()["site"])
        except (SystemExit, KeyError, OSError):
            left = None
        order = fit(rows, left)
        p = dict(p, target=order[0]["field"] if order else names[0])
    items = readiness(p)
    what = (f"{len(order)} of {len(names)} panels of {p['mosaic']}, {p['minutes']:g} minutes each" if order is not None
            else f"{p['target']}, {p['minutes']:g} minutes")
    say(f"Patrol {p['name']}: {what}, {p['exposure']} s frames at gain {p['gain']}")
    for item in items:
        say(f"  {'ok ' if item['ok'] else 'NO '} {item['what']}: {item['detail']}")
    if order is not None:
        say(f"  order, by novae reported x share caught x days unwatched / minutes ({left} minutes of night left):")
        for r in order:
            say(f"    {r['field']:<8} priority {r['priority']:.3f}: {r['novae_reported']} novae reported, "
                f"catch {100 * r['share_of_novae']:.0f}% at G {r['expected_mag_50']}, {r['days_unwatched']} days unwatched")
    chosen = [r["field"] for r in order] if order is not None else [p["target"]]
    plans = {name: steps(dict(p, target=name), dry_run=args.dry_run) for name in chosen}
    for name in chosen[:1]:
        for cmd in plans[name]:
            say("  then: " + " ".join(Path(c).name if c.endswith(".py") else c for c in cmd[1:])
                + ("   (and the same for each panel)" if len(chosen) > 1 and cmd is plans[name][-1] else ""))
    say("  then: depth.py --plant, difference.py against the reference, vet.py, and the answer")
    answer = {"programme": p, "readiness": items, "steps": [" ".join(c[1:]) for name in chosen for c in plans[name]]}
    if order is not None:
        answer["order"] = order
    # For a person to confirm (the console's plan): what moves first, and where to.
    # In daylight no panel fits what is left of the night, and nothing would move.
    answer.update(would_move=bool(chosen), target=chosen[0] if chosen else None,
                  goto=first_goto(chosen[0]) if chosen else None)
    if args.plan:
        return answer
    stopping = [i for i in items if i["stops"]]
    if any(i["what"] == "motion lock" for i in stopping):
        raise interface.Refusal("MOTION_LOCKED", "The motion lock is in place: nothing will move. "
                                + next(i["detail"] for i in stopping if i["what"] == "motion lock"))
    if stopping:
        raise interface.Refusal("INVALID_REQUEST", "Not now: " + "; ".join(i["detail"] for i in stopping))
    answer["fields"] = []
    # A mosaic's panels are finished (the final picture, then the search) in
    # the background while the mount goes on to the next: on 18 October 2026
    # each panel kept the mount waiting about a minute and a half for them.
    # A second look at a panel with something unexplained then comes once the
    # panels are done, with a GoTo back to it.
    behind = len(chosen) > 1 and not args.dry_run
    finishing, pool = [], None
    if behind:
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=1)

    def finish_panel(name, session):
        if behind:
            import restack
            restack.run(session, say=lambda *_: None)
        result = analyse(session, say, both_halves=p.get("both_halves", True))
        made = first_reference(name, session, say)
        return {"field": name, "analysis": result, "reference_made": made}

    for name in chosen:
        say(f"== {name}")
        began = time.time()
        stopped = None
        for cmd in plans[name]:
            if behind and Path(cmd[1]).name == "shoot.py":
                cmd = [*cmd, "--no-restack"]       # the final picture is made in the background
            say("$ " + " ".join(Path(c).name if c.endswith(".py") else c for c in cmd[1:]))
            # Through sys.stdout as it stands: with --json that is stderr, and
            # the commands' own lines must not land in the middle of the answer.
            # TY_PATROL: shoot.py leaves the search to the patrol, which does it next.
            done = subprocess.run(cmd, stdout=sys.stdout, env=dict(os.environ, TY_PATROL="1"))
            if done.returncode != 0:
                stopped = f"{Path(cmd[1]).name} stopped (exit {done.returncode})"
                break
        if stopped:
            if len(chosen) == 1:
                raise interface.Refusal("INVALID_REQUEST", stopped + "; the patrol stops with it.")
            say(f"  {stopped}; on to the next panel")
            answer["fields"].append({"field": name, "stopped": stopped})
            continue
        if args.dry_run:
            continue
        session = newest_session(name, began)
        if session is None:
            answer["fields"].append({"field": name, "stopped": "no frames kept"})
            continue
        if behind:
            say(f"  {name}: its picture and search go on in the background; on to the next panel")
            finishing.append(pool.submit(finish_panel, name, session))
            continue
        entry = finish_panel(name, session)
        if unexplained(entry["analysis"]):
            entry["second_look"] = second_look(p, name, say)
        answer["fields"].append(entry)
    if behind:
        pool.shutdown(wait=True)
        for done in finishing:
            try:
                entry = done.result()
            except Exception as problem:     # one panel's search failing is not the night's
                say(f"  a panel's search failed: {problem}")
                continue
            if unexplained(entry["analysis"]):
                goto = plans[entry["field"]][0]
                say(f"== back to {entry['field']} for a second look")
                if subprocess.run(goto, stdout=sys.stdout, env=dict(os.environ, TY_PATROL="1")).returncode == 0:
                    entry["second_look"] = second_look(p, entry["field"], say)
            answer["fields"].append(entry)
    if order is not None and answer["fields"] and not args.dry_run:
        # Every night's frames of the mosaic as one picture, growing with this night's.
        import stitch
        say(f"Joining every night's {p['mosaic']} panels into one picture, in the background: "
            f"{stitch.later(p['mosaic'])}")
    if len(chosen) == 1 and answer["fields"] and "analysis" in answer["fields"][0]:
        answer["analysis"] = answer["fields"][0]["analysis"]
    return answer


def first_goto(name):
    """mount.py's plan for the first GoTo, or why it is refused; None
    without a site."""
    import mount
    try:
        site = config.load()["site"]
    except (SystemExit, KeyError, OSError):
        return None
    try:
        plan = mount.plan_goto(name, site)
        plan.pop("side_note", None)
        return plan
    except interface.Refusal as refused:
        return {"would_move": False, "error": refused.as_error()}


def first_reference(name, session, say=print):
    """A panel's first night becomes its own reference, once measured."""
    import reference
    if reference.newest(name) is not None or not (session / "depth.json").exists():
        return None
    try:
        made = reference.make(name, str(session / "final.fits"))
    except interface.Refusal as held:
        say(f"  {name} has no reference of its own, and tonight's stack will not become one: {held.message}")
        return None
    say(f"  {name} had no reference of its own: tonight's stack is now v{made['version']}")
    return made["file"]


SWEEP_DAYS = 3      # --sweep without --all-history: sessions this recent


def searchable(session):
    """Whether a session can be searched for anything new: it has a final
    stack, its field has a reference it was not made from, and it has not
    been searched already."""
    import reference
    session = Path(session)
    if not (session / "final.fits").is_file() or (session / "patrol.json").exists():
        return False
    ref, owner = reference.for_field(session.parent.name)
    if ref is None or (reference.newest(session.parent.name) is None and is_panel(session.parent.name)):
        # A mosaic panel with no reference of its own: searched all the same,
        # so its depth is measured and its first good night becomes its reference.
        return is_panel(session.parent.name)
    return session.resolve() not in reference.sessions_used(owner)


def is_panel(field):
    """Whether a field is a mosaic panel (M31-P4)."""
    import re
    return re.match(r".+-P\d+$", field) is not None


def search_later(session, say=print, start=subprocess.Popen):
    """Search a session just stacked, in the background at low priority so
    the next target is not kept waiting: patrol.py --analyse, its lines in
    the session's patrol.log. Not in the demo, nor for a session the
    patrol itself is imaging (it searches its own)."""
    session = Path(session)
    if config.DEMO or os.environ.get("TY_PATROL") or not searchable(session):
        return None
    lowly = {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == "nt" else \
        {"preexec_fn": lambda: os.nice(19), "start_new_session": True}
    with open(session / "patrol.log", "w", encoding="utf-8") as log:
        start([sys.executable, str(ROOT / "patrol.py"), "--analyse", str(session)], stdout=log,
              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **lowly)
    say(f"Searching {session.parent.name} {session.name} for anything new, in the background: "
        f"{session / 'patrol.log'}")
    return str(session / "patrol.log")


def taken(session):
    """When a session was taken, from its folder's name (20261014-021118)."""
    try:
        return datetime.datetime.strptime(session.name[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def sweep(all_history=False, days=SWEEP_DAYS, say=print, search=None, now=None):
    """Search every session not yet searched: the last `days`, or all."""
    search = search or (lambda session: analyse(session, say, alerting=not all_history))   # old nights: no alerts
    now = now or datetime.datetime.now()
    found = []
    for session in sorted((config.DATA / "frames").glob("*/*")):
        when = taken(session)
        if not session.is_dir() or when is None or not searchable(session):
            continue
        if not all_history and now - when > datetime.timedelta(days=days):
            continue
        found.append(session)
    say(f"{len(found)} session{'s' if len(found) != 1 else ''} to search"
        f"{'' if all_history else f' from the last {days:g} days'}")
    searched = []
    for session in found:
        say(f"== {session.parent.name} {session.name}")
        try:
            result = search(session)
        except Exception as problem:       # one session's fault must not stop the rest
            say(f"  stopped: {problem.__class__.__name__}: {problem}")
            result = {"summary": [f"stopped: {problem.__class__.__name__}: {problem}"]}
        searched.append({"session": str(session), "summary": (result or {}).get("summary")})
    return {"sweep": "all" if all_history else f"{days:g} days", "searched": searched}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("programme", nargs="?", help="a programme in programmes/ (m31-novae), or a target name")
    ap.add_argument("--plan", action="store_true", help="readiness and what it would do; moves nothing")
    ap.add_argument("--minutes", type=float, help="how long to image (default: the programme's)")
    ap.add_argument("--analyse", metavar="SESSION", help="only look for anything new in a session already taken")
    ap.add_argument("--sweep", action="store_true", help=f"search every session of the last {SWEEP_DAYS} days "
                    "not yet searched")
    ap.add_argument("--all-history", action="store_true", help="with --sweep: every session kept")
    ap.add_argument("--dry-run", action="store_true", help="every step as it would be run; nothing moved or taken")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    if not args.programme and not args.analyse and not args.sweep:
        ap.error("name a programme, or --analyse SESSION, or --sweep")
    if args.all_history and not args.sweep:
        ap.error("--all-history goes with --sweep")
    interface.main("patrol", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
