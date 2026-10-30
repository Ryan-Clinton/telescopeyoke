#!/usr/bin/env python3
"""What the stream shows, decided in one place.

    ./stream.py director           what it is showing now and why, and what it left out
    ./stream.py director --clear   forget the target the telescope was last aimed at

Before 31 October 2026, stream.py and streamlook.py each read status.json,
the activity lines, the newest picture's age, the schedule and lucky.json,
and worked out for themselves what the telescope was doing. On 30 October
the telescope was filming the Moon while the stream named the last run
(M31), said "Tonight complete" and showed an empty picture, and each was
fixed as it was seen. Now:

- what the telescope is aimed at is its own record, cache/target.json, set
  by every GoTo (mount.py), a Moon video (moon.py) and any lucky-imaging
  video (lucky.py capture), and cleared when the night is ended and the
  mount parked (schedule.py end). The newer of it and a run that is imaging
  names the target: a run's status never names it once the telescope has
  been aimed somewhere else;
- `direct` takes everything once and gives one answer: the scene, the
  target, the programme, the activity, the picture, a headline when one of
  those has just changed, and what it left out and why;
- stream.py writes that answer to cache/broadcast.json every few seconds
  (`update`) and draws from it.

The target, the programme and the activity are kept apart: the Moon, lunar
lucky imaging, capturing; M31-P3, nova patrol, imaging; WASP-12, exoplanet
transit, imaging.

Which picture wins, highest first (PRIORITY):

1. focusing or polar alignment: their own layouts, which show the camera's
   star and the bolts to turn;
2. a fresh frame from the camera (younger than FRESH_S), whatever takes
   it: what the telescope sees now. During an imaging run of the target its
   stack is the big picture and the frame sits in its corner, since the
   stack is made of those frames and is as current as they are;
3. a Moon video being stacked or made into the mineral Moon: its last frame;
4. the GoTo moving to the target;
5. "end" once tonight's schedule has run out and nothing above is
   happening: the stream stops;
6. the current run's stack, after its frames have stopped;
7. nothing: "idle".

The schedule never outranks the camera: a schedule run to its end ends the
night only when nothing above it is happening.
"""
import json
import time

import config
import records

TARGET_FILE = config.DATA / "cache" / "target.json"
STATE_FILE = config.DATA / "cache" / "broadcast.json"
FRESH_S = 120             # a newest picture younger than this is the camera seeing now
TARGET_S = 12 * 3600      # a target aimed at longer ago than this is another night's
HEADLINE_S = 4            # a change of target or activity is announced over the picture this long

PRIORITY = {"focus": 100, "polar": 100, "live": 90, "processing": 80, "slew": 70, "stack": 60,
            "idle": 0, "end": 0}
ON_AIR = 80               # a scene this high puts the stream on air by itself

# What each kind of target is doing, by the activity, in plain words for the stream.
PROGRAMMES = {"moon": "lunar lucky imaging", "transit": "exoplanet transit", "patrol": "nova patrol",
              "deep_sky": "deep-sky imaging", "planet": "planetary imaging"}
ACTIVITIES = {"goto": "slewing", "solve": "plate solving", "focus": "focusing", "polar": "polar aligning",
              "imaging": "imaging", "live": "live view", "centring": "centring", "capturing": "capturing",
              "ranking": "ranking frames", "stacking": "stacking", "done": "result ready",
              "mineral": "mineral processing", "lucky": "lucky imaging"}
HEADLINES = {"capturing": "LUCKY IMAGING STARTED", "stacking": "STACKING THE BEST FRAMES",
             "mineral": "MINERAL COLOUR PROCESSING", "done": "RESULT READY", "focus": "CHECKING FOCUS",
             "polar": "POLAR ALIGNMENT", "imaging": "IMAGING STARTED", "goto": "MOVING THE TELESCOPE"}


def aim(name, kind=None, now=None):
    """The telescope is being aimed at `name`: it is the target until another
    is aimed at, the night ends or it is cleared. Never an error: this is
    called from inside a GoTo, and a full disk must not stop the move."""
    try:
        import sky
        records.write(TARGET_FILE, {"name": name, "kind": kind or sky.object_kind(name),
                                    "set_at": now or time.time()})
    except Exception:            # anything at all: the GoTo goes on without it
        pass


def clear():
    """Nothing is the target any more (the mount parked, or cleared by hand)."""
    try:
        TARGET_FILE.unlink()
    except OSError:
        pass


def aimed(now=None):
    """{"name", "kind", "set_at"} of the target the telescope was last aimed
    at tonight, or None."""
    try:
        t = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(t, dict) or not t.get("name") or (now or time.time()) - t.get("set_at", 0) > TARGET_S:
        return None
    return t


def _phase_of(phase):
    """The activity a phase line belongs to (activity.PHASES)."""
    if phase is None:
        return None
    if phase.startswith("focus"):
        return "focus"
    if phase.startswith("polar"):
        return "polar"
    return phase


def gather(st, now=None, procedure=False):
    """Everything the director looks at, read once: the run's status
    (status.json), the target aimed at, the activity lines, the newest
    picture's age, the lucky imaging's stage, focusing or polar alignment
    (`procedure`, when the caller has just read it), and whether tonight's
    schedule has more due or has run out."""
    import activity
    import stream
    import streamlook
    now = now or time.time()
    if procedure is False:
        procedure, _, _ = stream.broadcasting(now)
    try:
        p = json.loads((config.DATA / "web" / "lucky.json").read_text(encoding="utf-8"))
        lucky = p.get("stage") if now - p.get("at", 0) <= FRESH_S else None
    except (OSError, ValueError, AttributeError):
        lucky = None
    return {"now": now, "status": st, "target": aimed(now), "phase": activity.phase(),
            "image_age": stream.latest_age(now), "lucky": lucky, "procedure": procedure,
            "run_imaging": stream.imaging(st), "between": not stream.imaging(st) and stream.runner_alive()
            and stream.due_soon(st, now), "schedule_over": stream.night_over(st),
            "transit": bool(streamlook.transit_for(st.get("name") or ""))}


def _family(name, kind, given):
    """moon, transit, patrol, planet or deep_sky: what sort of show the target is."""
    if kind == "moon":
        return "moon"
    if given.get("transit"):
        return "transit"
    if "-P" in (name or ""):
        return "patrol"
    return kind or "deep_sky"


def direct(given, before=None):
    """The one answer to "what is the observatory doing, and what goes on
    screen?", from `gather`'s dict: {"scene", "target", "target_kind",
    "programme", "activity", "image", "image_age", "run_current",
    "priority", "on_air", "headline", "ignored"}. `before` is the last
    answer, for the headline when the target or activity changes."""
    import sky
    now, st = given["now"], given.get("status") or {}
    ignored = []
    run_name = st.get("name") or None
    run_at = now - st["age"] if run_name and isinstance(st.get("age"), (int, float)) else None
    aimed_at = given.get("target")
    # A run is still on while it images, or while its process runs it (paused by cloud).
    run_on = bool(run_name) and (bool(given.get("run_imaging")) or st.get("running") is True)
    # The newer of what was last aimed at and a run that is on names the target.
    if run_on and (aimed_at is None or (run_at or 0) >= aimed_at["set_at"]):
        name, kind = run_name, st.get("object_kind") or sky.object_kind(run_name)
    elif aimed_at:
        name, kind = aimed_at["name"], aimed_at.get("kind") or sky.object_kind(aimed_at["name"])
    else:
        name, kind = None, None
    run_current = run_on and name == run_name
    if run_name and not run_current:
        ignored.append(f"status target {run_name}: " + (
            f"the telescope was aimed at {name} after it" if name else "its run has ended"))
    if run_current and aimed_at and aimed_at["name"] != name:
        ignored.append(f"aimed at {aimed_at['name']}: the {run_name} run has imaged since")

    phase = _phase_of(given.get("phase"))
    lucky = given.get("lucky") if phase in ("lucky", "mineral") else None
    activity = lucky if phase == "lucky" and lucky else phase
    age = given.get("image_age")
    fresh = age is not None and age < FRESH_S
    family = _family(name, kind, given) if name else None
    if given.get("procedure"):
        scene, image, room = given["procedure"], "procedure", given["procedure"]
    elif fresh:
        stacked = run_current and phase not in ("lucky", "live", "mineral")
        scene, image, room = f"{family or 'sky'}_{'stack' if stacked else _moon_scene(activity)}", \
            "stack" if stacked else "latest", "live"
    elif phase in ("lucky", "mineral") and (family == "moon" or kind is None):
        scene, image, room = f"moon_{_moon_scene(activity)}", "latest" if age is not None else "none", "processing"
    elif phase == "goto":
        scene, image, room = "slew", "none", "slew"
    elif given.get("schedule_over") and not given.get("between"):
        scene, image, room = "end", "none", "end"
    elif run_current or (run_name and (st.get("stack") or {}).get("current") and name == run_name):
        scene, image, room = f"{family}_stack", "stack", "stack"
    else:
        scene, image, room = "idle", "none", "idle"
    if given.get("schedule_over") and scene != "end":
        ignored.append("schedule run to its end: " + ("the camera is seeing" if fresh else f"{scene} is on"))
    if not fresh and age is not None and image == "latest":
        ignored.append(f"newest picture {int(age)} s old: shown as the last of the video")

    if family == "moon":
        programme = "mineral Moon" if phase == "mineral" else (
            "live view" if phase == "live" else PROGRAMMES["moon"] if phase == "lucky" else "lunar imaging")
    elif phase == "live" and not run_current:
        programme = "live view"
    else:
        programme = PROGRAMMES.get(family) if name else None
    answer = {"scene": scene, "target": name, "target_kind": kind, "programme": programme,
              "activity": ACTIVITIES.get(activity, activity) if activity else ("live view" if fresh else "idle"),
              "image": image, "image_age": None if age is None else round(age, 1), "run_current": run_current,
              "priority": PRIORITY[room], "on_air": PRIORITY[room] >= ON_AIR, "updated": now, "ignored": ignored}
    answer["headline"] = headline(answer, activity, before)
    return answer


def _moon_scene(activity):
    """The part of a Moon programme an activity is: live, capture, stack or mineral."""
    return {"centring": "capture", "capturing": "capture", "ranking": "stack", "stacking": "stack",
            "done": "stack", "mineral": "mineral"}.get(activity, "live")


def target_words(name, kind):
    """The target as the stream names it: THE MOON, M31."""
    if kind == "moon":
        return "THE MOON"
    return (name or "").partition("-P")[0].upper() if "-P" in (name or "") else (name or "").upper()


def headline(answer, activity, before):
    """{"words", "until"} announcing a new target ("NOW OBSERVING: THE MOON")
    or a new activity ("STACKING THE BEST FRAMES") for HEADLINE_S, carried
    on from `before` until then; None when nothing has just changed."""
    now = answer["updated"]
    before = before or {}
    held = before.get("headline")
    if answer["target"] and answer["target"] != before.get("target"):
        return {"words": f"NOW OBSERVING: {target_words(answer['target'], answer['target_kind'])}",
                "until": now + HEADLINE_S}
    if answer["activity"] != before.get("activity") and _phase_of(activity) in HEADLINES and before:
        return {"words": HEADLINES[_phase_of(activity)], "until": now + HEADLINE_S}
    if held and now < held.get("until", 0):
        return held
    return None


def last():
    """The last answer written, or None."""
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def update(st, now=None, procedure=False):
    """Work out the answer now, from the last one written, and write it to
    cache/broadcast.json; never an error (the stream must go on): if it
    cannot be worked out, the run's own status is shown as before there was
    a director, on air while the camera sees."""
    try:
        answer = direct(gather(st, now, procedure), last())
    except Exception as error:
        import stream
        answer = {"scene": "unknown", "target": st.get("name"), "target_kind": st.get("object_kind"),
                  "programme": None, "activity": "unknown", "image": "stack", "image_age": None,
                  "run_current": True, "priority": 0, "on_air": bool(procedure) or stream.seeing(now),
                  "updated": now or time.time(), "headline": None, "ignored": [f"not worked out: {error}"]}
    try:
        records.write(STATE_FILE, answer)
    except OSError:
        pass
    return answer


def report(answer):
    """The answer in lines, for a person at a terminal: what is on screen,
    and what was left out and why."""
    lines = ["STREAM DIRECTOR", "",
             f"target:     {answer['target'] or 'none'}" + (f" ({answer['target_kind']})" if answer['target'] else ""),
             f"programme:  {answer['programme'] or 'none'}",
             f"activity:   {answer['activity']}",
             f"scene:      {answer['scene']} (priority {answer['priority']}, "
             f"{'on air' if answer['on_air'] else 'not on air by itself'})",
             f"image:      {answer['image']}" + (f", newest picture {answer['image_age']:.0f} s old"
                                                 if answer.get("image_age") is not None else ", no picture")]
    if answer.get("headline"):
        lines.append(f"headline:   {answer['headline']['words']}")
    lines += [f"ignored:    {why}" for why in answer["ignored"]] or ["ignored:    nothing"]
    return "\n".join(lines)


def examples(now):
    """The scenes the stream has, each as what `gather` would read: for
    `./stream.py scenes` and the tests. Made up for the look only."""
    old_m31 = {"name": "M31", "age": 9000, "accepted": 50, "captured": 60, "exposure": 16,
               "running": False, "stack": {"current": True},
               "schedule": {"steps": [{"label": "M31, 30 min", "status": "done"}]}}
    m31 = dict(old_m31, age=10, running=True)
    old_moon = {"name": "Moon", "age": 9000, "accepted": 199, "object_kind": "moon", "running": False,
                "stack": {"current": True}}
    moon = {"name": "Moon", "kind": "moon", "set_at": now - 600}
    base = {"now": now, "procedure": None, "lucky": None, "between": False, "schedule_over": False,
            "transit": False, "run_imaging": False}
    return {
        "moon-live": dict(base, status=old_m31, target=moon, phase="live", image_age=3, schedule_over=True),
        "moon-capture": dict(base, status=old_m31, target=moon, phase="lucky", lucky="capturing", image_age=1),
        "moon-stack": dict(base, status=old_m31, target=moon, phase="lucky", lucky="stacking", image_age=400),
        "moon-mineral": dict(base, status=old_m31, target=moon, phase="mineral", lucky="mineral", image_age=900),
        "deep-sky-stack": dict(base, status=m31, target={"name": "M31", "kind": "deep_sky", "set_at": now - 3600},
                               phase="imaging", image_age=10, run_imaging=True),
        "deep-sky-live": dict(base, status=old_moon, target={"name": "M31", "kind": "deep_sky", "set_at": now - 60},
                              phase="live", image_age=2),
        "slew": dict(base, status=old_m31, target={"name": "M33", "kind": "deep_sky", "set_at": now - 5},
                     phase="goto", image_age=None),
        "focus": dict(base, status=old_m31, target=None, phase="focus_walk", image_age=2, procedure="focus"),
        "end": dict(base, status=old_m31, target=None, phase=None, image_age=7200, schedule_over=True),
    }
