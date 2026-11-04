#!/usr/bin/env python3
"""What each observation is for, and when it has enough
(docs/observing-plan-spec.md, Phase 2).

    ./goals.py                    every programme's and planned target's goals
    ./goals.py M31-P3             one field's
    ./goals.py --json

Each programme (programmes/*.toml) and planned target
(programmes/targets/*.toml) says in its [goals] what it is for (its
purpose), how it is timed, and three levels: minimum (the least worth
having), desired (aimed for) and stretch (more, if time is spare), each in
the purpose's own measure. This module reads them, works out a known
transient's reference case, and gives the capture its one rule: keep going
until the desired accepted frames, or the cap. It reads; it never moves
anything. The capture rule is used only with [plan] goals on in config.toml.
"""
import argparse
import math
import re
import statistics
import tomllib
from datetime import date
from pathlib import Path

import config
import interface

ROOT = Path(__file__).parent
PROGRAMMES = ROOT / "programmes"
TARGETS = PROGRAMMES / "targets"

PURPOSES = {
    "nova-patrol": "stacked frames to be searchable; depth, with a clean subtraction, to be worth it",
    "known-transient": "its own brightness to a given error, against a reference of its host",
    "transit": "unbroken ingress, egress and baseline at the precision the depth needs",
    "moving": "coverage of its path, the depth it needs, and the repeat it needs",
    "lead": "the brightness measured to the error its question needs",
}
TIMINGS = {
    "once": "one observation to a quality",
    "revisit": "a revisit after an interval",
    "sequence": "a sequence over several nights",
    "series": "an unbroken time series",
    "deadline": "a follow-up by a deadline",
}
# Frames graded for a search (many stars, sharp) or for photometry (steady
# sky, unsaturated comparison stars): the grading suits the science.
GRADED_ON = {"nova-patrol": "search", "moving": "search", "known-transient": "photometry",
             "transit": "photometry", "lead": "photometry"}

STACKED_SHARE = 0.84    # restack keeps this share of accepted frames: the median of 86 sessions (history.py, 4 Nov 2026)
REJECT_ALLOWANCE = 0.5  # rejections may extend the frames taken by this share of the desired accepted frames
RETAKE_GIVE_UP = 3      # rejected frames in a row, once the desired count has been taken: cloud, not bad luck
CLOUD_STOP = 20         # rejected frames in a row that end any capture
SHOOT_CAP = 1.5         # the time a capture may run, as a multiple of its planned minutes (patrol.SHOOT_CAP)
# Provisional, as worth_depth: a stack whose subtraction is out of line over
# more than this share of its field is limited by the subtraction, not the sky.
QUALITY_MAX = 0.2
# The filter a step is taken in, on a light path with the filter wheel (filters.py):
# a programme's or target's [goals] filter, else L, the most light and the
# patrols' band. A light path without the wheel (the 183C's) ignores it.
FILTER = "L"

CASES = {
    1: "a reference from before the explosion exists: its brightness is measured against that",
    2: "no such reference: a brightness measured against a model of the galaxy, or relative to the last visit, "
       "said as such with its error",
    3: "neither is good enough: a detection or an upper limit only, said as that; more frames don't change this",
}


def enabled(phase, cfg=None):
    """Whether a phase of the plan is switched on in [plan] (goals, windows,
    dispatch). Off unless the person turned it on; the tests and the demo
    use config.example(), where all are off."""
    if cfg is None:
        cfg = plan_config()
    return bool((cfg.get("plan") or {}).get(phase, False))


def plan_config():
    """The settings the plan's phases are read from: config.toml, or the
    example's (all off) with no config.toml or with TY_PLAN=off (the tests)."""
    import os
    if os.environ.get("TY_PLAN") == "off" or not config.FILE.exists():
        return config.example()
    return config.load()


def _load(path):
    with Path(path).open("rb") as f:
        return tomllib.load(f)


def files():
    """(name, path) of every programme and planned target."""
    out = [(p.stem, p) for p in sorted(PROGRAMMES.glob("*.toml"))]
    out += [(f"targets/{p.stem}", p) for p in sorted(TARGETS.glob("*.toml"))]
    return out


def _folder(name):
    import stacking
    return stacking.folder_name(name)


def matches(p, field):
    mosaic = p.get("mosaic")
    if mosaic and re.fullmatch(rf"{re.escape(mosaic)}-P\d+", field):
        return True
    target = p.get("target")
    return bool(target) and (target == field or _folder(target) == field)


def purpose_of(p):
    """A programme's purpose: as it says, else from what it is."""
    g = p.get("goals", {})
    if g.get("purpose"):
        return g["purpose"]
    if p.get("mosaic") or p.get("both_halves"):
        return "nova-patrol"
    return "lead"


def timing_of(p, purpose):
    g = p.get("goals", {})
    if g.get("timing"):
        return g["timing"]
    return {"nova-patrol": "revisit", "transit": "series", "moving": "sequence"}.get(purpose, "once")


def levels(g):
    """minimum, worth, desired and stretch, each a dict of its measures,
    from a [goals] table. The Phase 1 names are kept: searchable_frames is
    the minimum's stacked frames, worth_depth the worth-it depth."""
    minimum = {k: v for k, v in (("stacked", g.get("searchable_frames", g.get("minimum_frames"))),) if v is not None}
    worth = {k: v for k, v in (("depth", g.get("worth_depth")), ("stacked", g.get("worth_frames")),
                               ("quality_max", g.get("quality_max", QUALITY_MAX if g.get("worth_depth") else None)))
             if v is not None}
    desired = {k: v for k, v in (("stacked", g.get("desired_frames")), ("depth", g.get("desired_depth")),
                                 ("error", g.get("desired_error"))) if v is not None}
    stretch = {k: v for k, v in (("stacked", g.get("stretch_frames")), ("depth", g.get("stretch_depth")))
               if v is not None}
    return minimum, worth, desired, stretch


def reference_case(field, g, kept=None):
    """Which of the three cases a known transient's measurement is (the
    spec's Phase 2): 1 with a reference made before it was discovered (ours
    or an archive's), 2 with a model of the host or a last visit to measure
    against, 3 otherwise. (case, why). Our own pictures become a host
    reference only once the transient has faded below what they reach,
    which is said by `faded_below` in the target's file."""
    discovered = g.get("discovered")
    if g.get("archive_reference"):
        return 1, f"an archive picture of the host from before it: {g['archive_reference']}"
    if kept is None:
        import reference
        kept = reference.kept(field)
    if discovered:
        when = date.fromisoformat(str(discovered))
        for version in kept:
            names = [Path(s).name for s in version.get("sessions", [])]
            dates = [date(int(n[:4]), int(n[4:6]), int(n[6:8])) for n in names if re.match(r"\d{8}-", n)]
            if dates and max(dates) < when:
                return 1, f"our own reference v{version.get('version')} is from {max(dates)}, before {when}"
    if g.get("faded_below") is not None:
        return 1, f"it has faded below G {g['faded_below']}, under what our own pictures reach"
    if g.get("host_model"):
        return 2, "measured against a model of the host galaxy, said as such with its error"
    if not discovered:
        return 3, "its discovery date is not in its file, so no reference of ours can be shown to be from before it"
    return 3, f"no reference of the host from before {discovered}, and no model of the host"


def of(field, cfg_files=None):
    """The goals for a field (a folder name such as M31-P3 or NGC3310):
    a dict with programme, purpose, timing, graded_on, minimum, worth,
    desired, stretch, cap and notes. A field no programme or target names
    has purpose None and nothing to meet."""
    for name, path in (cfg_files or files()):
        p = _load(path)
        if matches(p, field):
            return from_programme(name, p, field)
    return {"field": field, "programme": None, "purpose": None, "timing": None, "graded_on": "search",
            "minimum": {}, "worth": {}, "desired": {}, "stretch": {}, "cap": SHOOT_CAP, "case": None, "filter": FILTER, "notes":
            ["no programme or planned target names it: not judged"]}


def from_programme(name, p, field=None):
    g = p.get("goals", {})
    purpose = purpose_of(p)
    minimum, worth, desired, stretch = levels(g)
    notes = []
    case = None
    if purpose == "known-transient":
        case, why = reference_case(field or _folder(p.get("target", name)), g)
        notes.append(f"case {case}: {CASES[case]} ({why})")
        if case == 3:
            # More frames don't change the case: no stretch, and the desired
            # level is what a detection or an upper limit needs.
            stretch = {}
            desired.pop("error", None)
    if worth.get("depth") is not None:
        notes.append(f"worth it at G {worth['depth']:g}: provisional, until set from measured completeness")
    return {"field": field, "programme": name, "purpose": purpose, "timing": timing_of(p, purpose),
            "graded_on": g.get("graded_on", GRADED_ON.get(purpose, "search")),
            "minimum": minimum, "worth": worth, "desired": desired, "stretch": stretch,
            "cap": float(g.get("cap", SHOOT_CAP)), "case": case, "filter": str(g.get("filter") or FILTER),
            "notes": notes}


def flat(goals):
    """The Phase 1 [goals] names outcome.judge reads."""
    out = {}
    if "stacked" in goals["minimum"]:
        out["searchable_frames"] = goals["minimum"]["stacked"]
    for key, name in (("depth", "worth_depth"), ("stacked", "worth_frames"), ("quality_max", "quality_max")):
        if key in goals["worth"]:
            out[name] = goals["worth"][key]
    for key, name in (("stacked", "desired_frames"), ("depth", "desired_depth")):
        if key in goals["desired"]:
            out[name] = goals["desired"][key]
    for key, name in (("stacked", "stretch_frames"), ("depth", "stretch_depth")):
        if key in goals["stretch"]:
            out[name] = goals["stretch"][key]
    if goals.get("purpose"):
        out["purpose"] = goals["purpose"]
    return out


# --- the capture's one rule ----------------------------------------------------------

def accepted_for(stacked, share=STACKED_SHARE):
    """Accepted frames needed for `stacked` frames after the quality pass."""
    return max(1, math.ceil(stacked / share))


def seconds_for_depth(model, fwhm_arcsec, sky, depth_g):
    """The stacked seconds the depth model says reach `depth_g` (half of
    faint stars found) with stars this wide under this sky."""
    rest = depth_g - model["constant"] - model["fwhm"] * math.log10(fwhm_arcsec) - model["sky"] * sky
    return 10 ** (rest / model["time"])


def capture_rule(goals, minutes, share=STACKED_SHARE, exposure=None, model=None, prior=None):
    """What a capture of this field keeps going for: (desired accepted
    frames, cap in minutes, most frames to take). A desired count of
    stacked frames becomes accepted ones through the quality pass's
    measured share. A desired depth becomes the frames the depth model
    says reach it, with the field's last measured star width and sky
    (`prior`, prior_for()): modelled, and the cap still holds. With
    neither, or no model to turn a depth into frames, None: the capture
    keeps the minutes it was given."""
    want = goals["desired"].get("stacked")
    if want is None and goals["desired"].get("depth") is not None and model and prior and exposure \
            and prior.get("fwhm"):
        seconds = seconds_for_depth(model, prior["fwhm"], prior["sky"], goals["desired"]["depth"])
        want = max(math.ceil(seconds * share / exposure), goals["minimum"].get("stacked") or 0)
    if want is None:
        return None
    accepted = accepted_for(want, share)
    return {"accepted": accepted, "cap_minutes": round(minutes * goals.get("cap", SHOOT_CAP), 1),
            "most_frames": accepted + max(2, math.ceil(REJECT_ALLOWANCE * accepted))}


def keep_capturing(accepted, captured, rejected_in_row, elapsed_s, rule, cloud=0):
    """(go on?, why it stops). The one rule that replaces retakes() and the
    patrol's SHOOT_CAP. A stall costs time, which runs to the cap. A frame
    lost to cloud is a pause: it costs time, not one of the frames the
    rejections may take, and cloud alone never ends a capture with time
    left (a passing cloud is waited out; the time cap then lets the
    telescope go). Any other rejection (trailed, soft) costs a frame, which
    runs to the most frames; `rejected_in_row` counts only those, and
    CLOUD_STOP of them in a row, or RETAKE_GIVE_UP once the desired count
    has been taken, mean something other than the sky is wrong. `cloud` is
    the frames lost to cloud so far."""
    if accepted >= rule["accepted"]:
        return False, "desired accepted frames reached"
    if elapsed_s >= 60 * rule["cap_minutes"]:
        return False, "time cap reached (stalls, cloud and slow frames)"
    if captured - cloud >= rule["most_frames"]:
        return False, "frame cap reached (rejections)"
    if rejected_in_row >= CLOUD_STOP:
        return False, "every frame rejected, not for cloud: focus, trailing or the camera"
    if captured - cloud >= rule["accepted"] and rejected_in_row >= RETAKE_GIVE_UP:
        return False, "no retakes after rejections in a row (not cloud)"
    return True, None


# --- quick measures -------------------------------------------------------------------

def prior_for(field, data=None):
    """What the field's newest measured stack says to turn a frame log into
    the depth model's units: its pixel scale, its sky (mag/arcsec²) and the
    median sky counts of its accepted frames. Only a stack taken by the
    camera in use through its present light path counts: another camera's
    pixel scale and sky counts would give this one a wrong depth. None if no
    such stack of the field was measured; a folder whose frames have gone to
    the archive cannot say which camera took them and is passed over."""
    import json
    import stacking
    from astropy.io import fits
    data = data or config.DATA
    camera, focal = config.light_path()
    for folder in sorted((data / "frames" / field).glob("*/"), reverse=True):
        try:
            d = json.loads((folder / "depth.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (d.get("scale_arcsec_per_px") and d.get("sky_mag_per_arcsec2")):
            continue
        frame = next(iter(sorted(folder.glob("light-*.fits"))), None)
        if frame is None:
            continue
        took, at = stacking.camera_of(fits.getheader(frame, 1))
        if took != camera or (at is not None and at != focal):
            continue
        log = _log(folder)
        counts = [f["background"] for f in log if f.get("accepted") and f.get("background")]
        if counts:
            return {"scale": d["scale_arcsec_per_px"], "sky": d["sky_mag_per_arcsec2"],
                    "fwhm": d.get("fwhm_arcsec"), "background": statistics.median(counts), "from": folder.name}
    return None


def _log(folder):
    import json
    path = Path(folder) / "frames.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def quick_depth(log, exposure, model, prior, share=STACKED_SHARE):
    """The depth (G) the accepted frames so far should reach, from their
    star width and sky, before the slow measurement: what the next choice
    uses while processing runs (processing never holds the telescope).
    Star width from pixels by the field's measured scale; the sky from the
    field's last measured sky, brighter or darker by the ratio of the sky's
    counts. Modelled, and said so; the measured depth replaces it."""
    import depth
    kept = [f for f in log if f.get("accepted") and f.get("fwhm") and f.get("background")]
    if not kept or not model or not prior:
        return None
    fwhm = statistics.median(f["fwhm"] for f in kept) * prior["scale"]
    background = statistics.median(f["background"] for f in kept)
    sky = prior["sky"] - 2.5 * math.log10(max(background, 1e-3) / max(prior["background"], 1e-3))
    return round(depth.predict(model, fwhm, sky, len(kept) * share * exposure), 2)


def words(g):
    if g["purpose"] is None:
        return [f"{g['field']}: {g['notes'][0]}"]
    head = f"{g['programme']}: {g['purpose']} ({PURPOSES[g['purpose']]}), timed {g['timing']}, " \
           f"frames graded for {g['graded_on']}"

    def said(level):
        parts = []
        if "stacked" in level:
            parts.append(f"{level['stacked']} stacked")
        if "depth" in level:
            parts.append(f"G {level['depth']:g}")
        if "error" in level:
            parts.append(f"to {level['error']:g} mag")
        if "quality_max" in level:
            parts.append(f"subtraction out of line on at most {100 * level['quality_max']:.0f}%")
        return ", ".join(parts) or "not set"
    lines = [head, f"    minimum {said(g['minimum'])}; worth it {said(g['worth'])}; desired {said(g['desired'])}; "
                   f"stretch {said(g['stretch'])}; may run {g['cap']:g} times its minutes"]
    lines += [f"    {n}" for n in g["notes"]]
    return lines


def run(args, say=print):
    if args.field:
        found = [of(args.field)]
    else:
        found = []
        for name, path in files():
            p = _load(path)
            field = p.get("target") or (f"{p['mosaic']}-P1" if p.get("mosaic") else name)
            found.append(from_programme(name, p, _folder(field)))
    for g in found:
        for line in words(g):
            say(line)
    return {"goals": found, "enabled": enabled("goals")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("field", nargs="?", help="a field's folder name, such as M31-P3 or NGC3310")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("goals", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
