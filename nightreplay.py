#!/usr/bin/env python3
"""Replay a recorded night under a scheduling policy, to compare policies
on the same sky (docs/observing-plan-spec.md, Phase 5).

    ./nightreplay.py 2026-11-03                       the night's own plan, as-run and current, 50 runs each
    ./nightreplay.py 2026-11-03 --check               the replay against what was recorded, in two parts
    ./nightreplay.py 2026-11-03 --protect 04:00       a step the person times for 04:00 put in the plan
    ./nightreplay.py 2026-11-03 --stress camera-dead  the same night with the camera failing at its middle
    ./nightreplay.py 2026-11-03 --json

The current policy is the running code, not a copy of it: each step is
started through schedule.prepared, a patrol chooses and keeps to its budget
through patrol.fit, field_minutes, room, shoot_minutes and
second_look_put_off, and a capture stops on shoot.stop_for, the functions
the telescope itself runs by. The as-run policy is the code as it stood on
3 November 2026, reconstructed in AsRun below; it is labelled so, as no
running code stands behind it.

What it uses, and how each figure is labelled:

- Recorded: the night's plan (cache/schedules/DATE.json), the frames
  taken and why each was rejected, the gaps between them, the moves
  between sessions, the depth inputs (star width and sky) measured that
  night, which fields' searches found something unexplained, and how each
  search ended.
- Modelled: everything the record cannot say. A field at a time the
  telescope was not on it borrows the cloud of the frames taken nearest
  that time, from whatever field. Cadence, moves, the quality pass's
  stacked share and depth come from the night's own measures or
  history.py's, with their spread. A search the record has no answer for
  fails its subtraction at the rate earlier nights' searches did, drawn
  afresh in each run. Monte Carlo runs give each measure its uncertainty.
- Chronological: the costs come from nights before the one replayed, and
  a depth is calibrated only by that night's stacks measured before the
  moment it is asked for, as the telescope would know them then.
- Not modelled, and said so: a supernova's photometry, what a search would
  discover, a step stopped by hand.

Each visit says the share of its frames whose sky was recorded on that
same field within five minutes. No policy is credited with frames the
record cannot establish: what is modelled is said so.
"""
import argparse
import json
import math
import random
import re
import statistics
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, time as dtime
from pathlib import Path

import config
import history
import interface
import live
import outcome
import patrol
import schedule
import shoot

NEAR_S = 5 * 60          # a recorded frame this close in time stands for the sky then
FAR_S = 15 * 60          # beyond this, the night's overall cloud is used
SEARCHABLE = 8           # stacked frames the search needs (vet.HALVES_FROM)
KEEP = 0.85              # restack.select's share of the frames that pass, best first
PASS_FLUX = 0.6          # stacking.judge: a frame under this share of the better half's star light is cloud
TOO_SHALLOW = 16.0       # G: patrol.analyse's "too shallow to search" for M31's fields
MEASURED_AFTER_S = 10 * 60   # a stack's depth is known this long after its last frame (restack, then depth.py)
SAME_VISIT_S = 15 * 60   # a replayed visit this close to a recorded one of the same field is that visit
ON_TIME_S = 60           # a protected step's first frame this long after its start is late
FAILURES = ("subtraction", "no reference", "unsolved")    # search stops the frames themselves can't explain
# Nights the engine's own constants were tuned against: a check of one of
# them is not an independent test of the engine.
TUNED_ON = {"2026-11-03"}
NOT_MODELLED = ["a supernova's photometry: its visits are judged by frames and depth only",
                "what a search would discover: only whether it could run",
                "a step stopped by hand (schedule.py next)",
                "dawn and the mount's limits ending a patrol early (patrol.night_left)",
                "dispatch: what was owed at the night's start, other than the plan's own second-look steps; "
                "how strong a candidate was (every second look counts as uncertain)"]
PANEL_FIELD = re.compile(r"(.+)-P(\d+)$")
# The code the night of 3 to 4 November 2026 ran (main at 17:23 that
# evening): the as-run policy reads its programmes from it.
AS_RUN_CODE = "f9b763a"


# --- the night as recorded ------------------------------------------------------

@dataclass
class Night:
    evening: date
    plan: dict
    sessions: list
    frames: list                 # (time, field, cause, transparency or None), every frame taken
    stall_windows: list          # (start, end): long gaps between frames (inferred)
    depth_inputs: list           # dicts: mid, first, last, fwhm, sky, measured, seconds
    moves: list                  # (from field, to field, time, seconds)
    unexplained: set             # session folder names whose search found something unexplained
    start: float
    end: float
    frame_gaps: list             # seconds beyond the exposure between frames, this night's
    stacked_shares: list
    searches: dict = dc_field(default_factory=dict)    # session folder name: how its search ended
    seen_before: set = dc_field(default_factory=set)   # fields imaged on an earlier night (a reference exists)


def unexplained_in(folder):
    """Whether a session's search left anything unexplained."""
    record = outcome._json(Path(folder) / "patrol.json") or {}
    for line in record.get("summary", []):
        found = re.match(r"\s*(?:Unexplained:\s*)?(\d+)(?:\s+unexplained)?\b", line)
        if found and ("nexplained" in line) and int(found.group(1)) > 0:
            return True
    return False


def search_ended(folder, field):
    """How a recorded session's search ended: "searched", one of FAILURES,
    "too few frames", "too shallow", "other", or None (none, or no answer)."""
    programme, goals = outcome.programme_for(field)
    if not goals:
        return None
    state, why = outcome.search_state(folder, programme, working=lambda *_: False)
    if state == "searched":
        return "searched"
    return outcome.stop_kind(why) if state == "stopped" else None


def load(evening, data=None):
    """The night of `evening` from its records."""
    data = data or config.DATA
    plan_file = data / "cache" / "schedules" / f"{evening.isoformat()}.json"
    if not plan_file.exists():
        raise interface.Refusal("NO_SESSION", f"No plan kept for the night of {evening}: {plan_file}")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    every = history.sessions(data=data)
    rows = [s for s in every if s["night"] == evening.isoformat()]
    # Each field's clear-sky star light: the 90th percentile of its accepted
    # frames' flux over every night kept. A frame's flux over it is the
    # sky's transparency then (recorded), whatever field it was.
    clear = {}
    for s in every:
        clear.setdefault(s["field"], []).extend(f["flux"] for f in s["log"] if f.get("accepted") and f.get("flux"))
    clear = {k: sorted(v)[int(0.9 * (len(v) - 1))] for k, v in clear.items() if v}
    if not rows:
        raise interface.Refusal("NO_SESSION", f"No sessions on the night of {evening}.")
    frames, windows, depth_inputs, gaps, shares = [], [], [], [], []
    for s in rows:
        for f in s["log"]:
            if isinstance(f.get("taken"), (int, float)):
                ratio = (f["flux"] / clear[s["field"]]) if f.get("flux") and clear.get(s["field"]) else None
                frames.append((f["taken"], s["field"], "accepted" if f.get("accepted") else outcome.cause(f),
                               None if ratio is None else min(ratio, 1.5)))
        if s["exposure"]:
            usual = s["exposure"] + outcome.FRAME_GAP_S
            for a, b in zip(s["times"], s["times"][1:]):
                if b - a > usual + outcome.STALL_S:
                    windows.append((a + usual, b))
                elif 0 <= b - a - s["exposure"] <= outcome.STALL_S:
                    gaps.append(b - a - s["exposure"])
        d = outcome._json(s["folder"] / "depth.json") or {}
        if d.get("fwhm_arcsec") and d.get("sky_mag_per_arcsec2"):
            seen = [f["flux"] / clear[s["field"]] for f in s["log"]
                    if f.get("accepted") and f.get("flux") and clear.get(s["field"])]
            depth_inputs.append({"mid": (s["first"] + s["last"]) / 2, "first": s["first"], "last": s["last"],
                                 "transparency": statistics.median(seen) if seen else 1.0,
                                 "fwhm": d["fwhm_arcsec"], "sky": d["sky_mag_per_arcsec2"],
                                 "measured": d.get("completeness", {}).get("all", {}).get("mag_50"),
                                 "seconds": d.get("exposure_s")})
        stack = (outcome._json(s["folder"] / "restack.json") or {}).get("summary", {})
        offered = sum(1 for f in s["log"] if f.get("accepted") or outcome.cause(f) == "deferred")
        if stack.get("stacked") is not None and offered:
            shares.append(min(1.0, stack["stacked"] / offered))
    moves = [(a["field"], b["field"], a["last"], b["first"] - a["last"] - (b["exposure"] or 0))
             for a, b in zip(rows, rows[1:]) if 0 < b["first"] - a["last"] <= history.MOVE_MAX_S]
    starts = [st.get("started") for st in plan.get("steps", []) if st.get("started")]
    untils = [st.get("finished") for st in plan.get("steps", []) if st.get("until") and st.get("finished")]
    start = min(starts) if starts else rows[0]["first"]
    end = max([rows[-1]["last"]] + untils)
    return Night(evening, plan, rows, sorted(frames), sorted(windows), depth_inputs, moves,
                 {s["folder"].name for s in rows if unexplained_in(s["folder"])}, start, end, gaps, shares,
                 searches={s["folder"].name: search_ended(s["folder"], s["field"]) for s in rows},
                 seen_before={s["field"] for s in every if s["night"] < evening.isoformat()})


def sunset_of(night):
    """schedule.not_before's anchor for the replayed night: its evening's
    noon, so "05:25" is the next morning's and "21:00" that evening's."""
    anchor = datetime.combine(night.evening, dtime(12, 0)).timestamp()
    return lambda now: anchor


# --- the sky and the kit at a moment ------------------------------------------

class Conditions:
    """What a frame taken at a moment on a field would have met: recorded
    where the night says, modelled where it doesn't. `stress` overrides.
    `calibration` is "chronological" (a depth learns only from stacks
    measured before it) or "leave-one-out" (from every other stack that
    night, which the telescope could not have known: for comparison)."""

    def __init__(self, night, costs, rng, stress=None, calibration="chronological"):
        self.night, self.costs, self.rng, self.stress = night, costs, rng, stress
        self.calibration = calibration
        times = [f[0] for f in night.frames]
        self.first, self.last = (min(times), max(times)) if times else (night.start, night.end)
        clouded = [f for f in night.frames if f[2] == "cloud"]
        self.cloud_overall = len(clouded) / max(1, len(night.frames))
        self.trailed = costs["rejections"]["share"].get("trailed", 0.0)
        self.middle = (night.start + night.end) / 2
        # The chance a search with enough frames fails its subtraction, drawn
        # once a run from earlier nights' searches: few searches, wide spread.
        counts = costs.get("search_outcomes") or {}
        self.p_subtraction = rng.betavariate(counts.get("subtraction", 0) + 1, counts.get("searched", 0) + 1)

    def cloud(self, t, field):
        """(probability a frame is lost to cloud, recorded on this field?)"""
        if self.stress == "no-frames":
            return 1.0, False
        if self.stress == "flicker" and int((t - self.night.start) // 300) % 2 == 1:
            return 1.0, False
        near = [(abs(ft - t), ff, c) for ft, ff, c, _ in self.night.frames if abs(ft - t) <= FAR_S]
        if not near:
            return self.cloud_overall, False
        close = [x for x in near if x[0] <= NEAR_S] or sorted(near)[:5]
        share = sum(1 for _, _, c in close if c == "cloud") / len(close)
        same = any(ff == field and dt <= NEAR_S for dt, ff, _ in close)
        return share, same

    def transparency(self, t, field=None):
        """The sky's transparency a frame met at t: one of the recorded
        frames' near then, as a share of clear-sky star light. The same
        field's frames when the record has them (each field's clear light is
        its own), any field's otherwise."""
        # Only frames the run itself accepted: an accepted frame in the replay
        # met the light of frames that passed, not of those lost to cloud.
        good = [(ft, ff, r) for ft, ff, c, r in self.night.frames if r is not None and c == "accepted"]
        own = [r for ft, ff, r in good if ff == field and abs(ft - t) <= NEAR_S]
        if own:
            return self.rng.choice(own)
        near = [r for ft, _, r in good if abs(ft - t) <= NEAR_S]
        if not near:
            near = [r for ft, _, r in good if abs(ft - t) <= FAR_S]
        return self.rng.choice(near) if near else 1.0

    def stall(self, t):
        """Seconds the camera loses before a frame started at t: the night's
        own long gaps inside its recorded span, a modelled rate outside it."""
        if self.stress == "camera-dead" and t >= self.middle:
            return float("inf")
        if self.first <= t <= self.last:
            for a, b in self.night.stall_windows:
                if a <= t < b:
                    return b - t
            return 0.0
        rate = (self.costs["long_gaps"]["per_hour"] or {}).get("median", 0.0)
        each = (self.costs["long_gaps"]["seconds_each"] or {}).get("median", 60.0)
        frame_hours = 21.0 / 3600
        return each if self.rng.random() < rate * frame_hours else 0.0

    def gap(self, exposure):
        pool = self.night.frame_gaps
        if pool:
            return self.rng.choice(pool)
        g = self.costs["frame_gap_s_by_exposure"].get(f"{exposure:g}") or self.costs["frame_gap_s"]
        return g["median"] if g else 5.0

    def move(self, src, dst, t):
        """(seconds, recorded?) to go from one field to another at t."""
        if src == dst:
            return 0.0, True
        for a, b, mt, secs in self.night.moves:
            if a == src and b == dst and abs(mt - t) <= 10 * 60:
                return secs, True
        pool = [secs for *_, secs in self.night.moves]
        if len(pool) >= 3:
            return self.rng.choice(pool), False
        m = self.costs["move_s"]
        return (m["median"] if m else 150.0), False

    def depth(self, t, seconds, transparency=1.0, decided=None):
        """Modelled depth (G) of a stack of `seconds` made at t, or None.
        The depth model (fitted to earlier nights) with the star width and
        sky measured nearest that time, calibrated by this night's own
        measured stacks: the model is pooled over many nights, and 4
        November's stacks sit 0.6 to 0.9 mag deeper than it. Chronological
        calibration uses only stacks whose depth was known by `decided` (the
        moment the run's choice was made, t if not given)."""
        model = self.costs.get("depth_model")
        if not model or not self.night.depth_inputs or seconds <= 0:
            return None
        import depth
        near = min(self.night.depth_inputs, key=lambda d: abs(d["mid"] - t))
        known_by = t if decided is None else decided
        if self.calibration == "chronological":
            others = [d for d in self.night.depth_inputs if d["measured"] is not None and d["seconds"]
                      and d["last"] + MEASURED_AFTER_S <= known_by]
        else:
            others = [d for d in self.night.depth_inputs
                      if d["measured"] is not None and d["seconds"] and not (d["first"] - 300 <= t <= d["last"])]
        residuals = [d["measured"] - depth.predict(model, d["fwhm"], d["sky"], d["seconds"])
                     - 2.5 * math.log10(max(d["transparency"], 0.01)) for d in others]
        err = self.costs.get("depth_model_error") or {"median": 0.0, "p10": -0.4, "p90": 0.6}
        if len(residuals) >= 2:
            offset = statistics.median(residuals)
            sd = statistics.pstdev(residuals) if len(residuals) >= 3 else (err["p90"] - err["p10"]) / 2.56
        else:
            offset, sd = err["median"], (err["p90"] - err["p10"]) / 2.56
        shift = -1.0 if self.stress == "depth-wrong" else 0.0
        # Thin cloud dims stars without widening them or brightening the sky,
        # so the model alone cannot see it: the frames' own star light does.
        dimming = 2.5 * math.log10(max(transparency, 0.01))
        return depth.predict(model, near["fwhm"], near["sky"], seconds) + offset + dimming + \
            self.rng.gauss(0.0, max(0.05, sd)) + shift

    def search(self, field, recorded):
        """(how a search with enough frames and depth ends, "recorded" or
        "modelled"): the record's answer for the same visit when it has
        one; else no reference for a field never imaged before this night,
        and otherwise a failed subtraction at earlier nights' rate."""
        if recorded == "searched" or recorded in FAILURES:
            return recorded, "recorded"
        if field not in self.night.seen_before:
            return "no reference", "modelled"
        return ("subtraction" if self.rng.random() < self.p_subtraction else "searched"), "modelled"


# --- the policies ----------------------------------------------------------------

def option(command, name, kind=float):
    """The last value of `name` in a command, as argparse takes it, or None."""
    at = [i for i, c in enumerate(command) if c == name]
    return kind(command[at[-1] + 1]) if at else None


class Current:
    """The running code's rules: each call is the function the telescope runs by."""
    name = "current"
    reconstructed = False
    chooses = False          # Phases 3 and 4: the next step chosen, not the list in order

    def programme(self, name):
        return patrol.programme(name)

    def prepare(self, step, now, last, sunset, cut=None):
        return schedule.prepared(step, now, last, sunset, cut=cut)

    def capture_rule(self, run, field, minutes, exposure):
        """Phase 2's rule for a patrol's capture: none in today's code."""
        return None

    def weighed(self, run):
        """Phase 4's weighing of a second look: always yes in today's code."""
        return True, None

    def frames_for(self, minutes, exposure):
        return patrol.frames_for(minutes, exposure)

    def shoot_cap(self):
        return patrol.SHOOT_CAP

    def frames_asked(self, frames, minutes):
        return shoot.frames_asked(frames, minutes)

    def stop(self, index, frames, log, elapsed, minutes):
        return shoot.stop_for(index, frames, log, elapsed, minutes, live.KNOWN["shoot.cloud_stop"][1])

    def visit(self, minutes):
        return patrol.visit_minutes(minutes)

    def panels(self, rows, budget):
        return patrol.fit(rows, budget)

    def field_minutes(self, minutes, budget):
        return patrol.field_minutes(minutes, budget)

    def deadline(self, began, budget):
        return began + 60 * budget if budget else None

    def room(self, deadline, now, minutes):
        return patrol.room(deadline, now, minutes)

    def shoot_minutes(self, minutes, deadline, now):
        return patrol.shoot_minutes(minutes, deadline, now)

    def look_put_off(self, waiting, room_left, budget, weighed=(True, None)):
        return patrol.second_look_put_off(waiting, room_left, live.KNOWN["patrol.second_looks"][1], budget,
                                          weighed=weighed)

    def look_room(self, deadline, now):
        return patrol.room(deadline, now, patrol.visit_minutes(patrol.CONFIRM_MINUTES))


class AsRun(Current):
    """The code as it stood on 3 November 2026, reconstructed: five-minute
    panels whose frames were counted from the exposure alone, --minutes at
    1.1 times a field's, no budget, every second look taken after the panels,
    and a shoot step with only --minutes taking 60 frames. No running code
    stands behind this: it is checked only against that night's record."""
    name = "as-run 3 Nov"
    reconstructed = True

    def prepare(self, step, now, last, sunset, cut=None):
        command = [c.replace("{last}", last or "") for c in step["command"]]
        if any(Path(c).name == "patrol.py" for c in command[:2]) and not step.get("until"):
            return command, None          # no --budget and no backstop then
        return schedule.prepared(step, now, last, sunset, cut=cut)

    def programme(self, name):
        """The programme as it stood then (git show AS_RUN_CODE), or today's
        when the history is not there."""
        import subprocess
        import tomllib
        try:
            text = subprocess.run(["git", "show", f"{AS_RUN_CODE}:programmes/{name}.toml"], cwd=patrol.ROOT,
                                  capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return super().programme(name)
        if text.returncode != 0:
            return super().programme(name)
        p = tomllib.loads(text.stdout)
        p.setdefault("name", name)
        return p

    def frames_for(self, minutes, exposure):
        return max(1, round(60 * minutes / exposure))

    def shoot_cap(self):
        return 1.1

    def frames_asked(self, frames, minutes):
        return 60 if frames is None else frames

    def panels(self, rows, budget):
        return rows

    def field_minutes(self, minutes, budget):
        return minutes

    def deadline(self, began, budget):
        return None

    def look_put_off(self, waiting, room_left, budget, weighed=(True, None)):
        return None


class Goals(Current):
    """Phase 2 on today's code ([plan] goals on): a patrol's capture keeps
    going to its desired accepted frames, stalls to the time cap and
    rejections to the frame cap, by the functions shoot.py --accepted stops
    by. A desired depth becomes frames through goals.capture_rule with the
    depth model of earlier nights and the field's star width and sky from
    stacks measured before that moment."""
    name = "goals (Phase 2)"

    def capture_rule(self, run, field, minutes, exposure):
        import goals
        g = goals.of(field)
        known = [d for d in run.night.depth_inputs if d["last"] + MEASURED_AFTER_S <= run.t]
        prior = None
        if known:
            near = min(known, key=lambda d: abs(d["mid"] - run.t))
            prior = {"fwhm": near["fwhm"], "sky": near["sky"]}
        rule = goals.capture_rule(g, 1.0, exposure=exposure, model=run.cond.costs.get("depth_model"), prior=prior)
        if rule:
            rule["cap_minutes"] = minutes      # shoot.py's --minutes: the patrol's cap, kept to its budget
        return rule


class Windows(Goals):
    """Phase 3 on Phase 2 ([plan] windows on): windows.choose picks the step,
    protected starts keep their setup before them, and a flexible step is
    told the cutoff through schedule.prepared, as the runner does."""
    name = "windows (Phase 3)"
    chooses = True

    def choose(self, run, pending):
        import windows
        return windows.choose(pending, run.t, run.cond.costs, run.when)


class Dispatch(Windows):
    """Phase 4 on Phase 3 ([plan] dispatch on): dispatch.choose ranks the
    agreed steps at each step's end with the measured skyline (dispatch.Sky
    for the night), and a second look is weighed against the night's
    follow-up allowance (obligations.allowance_left). The replay knows only
    that a search left something unexplained, not how strong it was, so
    every second look counts as uncertain; what is owed is the plan's own
    second-look steps."""
    name = "dispatch (Phase 4)"

    def __init__(self):
        self.sky = None

    def choose(self, run, pending):
        import dispatch
        if self.sky is None:
            try:
                self.sky = dispatch.Sky(now=run.night.start)
            except Exception:        # no site: every target counts as up, said in the result
                self.sky = False
        owed = [{"field": f, "until": (run.night.evening.fromordinal(run.night.evening.toordinal() + 1)).isoformat()}
                for s in pending if "second look" in s["label"] for f in dispatch.what(s)[1]]
        step, cut, hold, _ = dispatch.choose(pending, run.t, self.sky or None, owed, run.cond.costs,
                                             run.last_target, keep=False, when=run.when)
        if step is not None and self.sky and dispatch.what(step)[0] and \
                not self.sky.window(dispatch.what(step)[0], run.t)[0]:
            run.below_limit.append(step["label"])
        return step, cut, hold

    def weighed(self, run):
        import obligations
        return obligations.allowance_left(run.follow_up_used, run.night.end - run.night.start, FOLLOW_UP_SHARE)


FOLLOW_UP_SHARE = 0.25   # [plan] follow_up_share, as the person approved on 4 November 2026
POLICIES = {"as-run": AsRun, "current": Current, "goals": Goals, "windows": Windows, "dispatch": Dispatch}


@dataclass
class Visit:
    step: str
    field: str
    kind: str                  # panel, field, second look, shoot
    exposure: float = 16.0
    start: float = 0.0
    first_frame: float | None = None
    end: float = 0.0
    asked: int = 0
    captured: int = 0
    accepted: int = 0
    cloud: int = 0
    stacked: int = 0
    depth: float | None = None
    search: str = "none"
    search_source: str = "none"
    recorded_share: float = 0.0
    move_recorded: bool = True
    verdicts: dict = dc_field(default_factory=dict)
    stopped_by: str = ""
    stall_s: float = 0.0


def panel_order(night, mosaic, start, end):
    """The panels in the order that night took them, then the rest."""
    seen = []
    for s in night.sessions:
        m = PANEL_FIELD.match(s["field"])
        if m and m.group(1) == mosaic and start - 60 <= s["first"] <= end and s["field"] not in seen:
            seen.append(s["field"])
    rest = [f"{mosaic}-P{n}" for n in range(1, 9) if f"{mosaic}-P{n}" not in seen]
    return seen + rest


def protected_step(night, at_time, minutes=20):
    """A step the person times for `at_time` ("HH:MM"), as Phase 3 would
    protect: a shoot of the field the record had nearest then, so its sky
    is recorded, placed in the plan after the step running at that time."""
    when = schedule.not_before(at_time, night.start, sunset_of(night))
    field = min(night.sessions, key=lambda s: min(abs(s["first"] - when), abs(s["last"] - when)))["field"]
    step = {"id": f"protected {at_time}", "label": f"protected {at_time}: {field}", "minutes": minutes,
            "not_before": at_time, "until": None, "protected": True,
            "command": ["./shoot.py", field, "--minutes", f"{minutes:g}", "--exposure", "16"]}
    steps = list(night.plan.get("steps", []))
    before = [i for i, st in enumerate(steps) if st.get("started") and st["started"] <= when]
    steps.insert((before[-1] + 1) if before else 0, step)
    return dict(night.plan, steps=steps)


# --- running a night -----------------------------------------------------------

class Run:
    """One replay of the night under one policy and one draw of the modelled
    parts. Each step goes through the policy's rules; frames, stalls, cloud
    and moves come from Conditions. Time is kept by what it went on."""

    def __init__(self, night, policy, cond, anchor=False, plan=None):
        self.night, self.policy, self.cond = night, policy, cond
        self.plan = plan or night.plan
        # With anchor, each visit starts where the record says that visit
        # started (the acquisition check): it tests the visit's model, not
        # the schedule's timing.
        self.anchor = anchor
        self.seen = {}
        self.t = night.start
        self.at = None
        self.visits = []
        self.steps = []
        self.deferred_looks = 0
        self.sunset = sunset_of(night)
        self.follow_up_used = 0.0        # seconds of second looks (Phase 4's allowance)
        self.below_limit = []            # steps chosen when the planner's skyline said their target was down
        self.not_up = []                 # steps left queued: their target not up again before dawn
        self.last_target = None
        self.spent = {"accepted": 0.0, "rejected": 0.0, "between frames": 0.0, "stalls": 0.0,
                      "moves": 0.0, "waiting for a timed step": 0.0, "steps not modelled": 0.0}

    def recorded_visit(self, field, start):
        """The recorded session this visit replays, if one is near enough in time."""
        same = [s for s in self.night.sessions if s["field"] == field and abs(s["first"] - start) <= SAME_VISIT_S]
        return min(same, key=lambda s: abs(s["first"] - start)) if same else None

    def unexplained(self, v):
        """Whether a visit's search left something unexplained: as the
        night's own visit to that field nearest in time found (recorded).
        A replay invents no candidates, and a search it could not run
        finds none."""
        if v.search != "searched":
            return False
        same = [s for s in self.night.sessions if s["field"] == v.field]
        nearest = min(same, key=lambda s: abs(s["first"] - v.start)) if same else None
        return nearest is not None and nearest["folder"].name in self.night.unexplained

    def when(self, text, now):
        """A step's clock time as the runner reads it, on this night."""
        return schedule.not_before(text, now, self.sunset)

    def capture(self, step, field, kind, frames, minutes, exposure, hard, goals, rule=None):
        """shoot.py on a field: the move there, then frames until the
        policy's stop says so or the backstop (`hard`) ends it. With a
        Phase 2 rule, shoot.goal_stop decides, as shoot.py --accepted does."""
        n = self.seen.get(field, 0)
        self.seen[field] = n + 1
        recorded = [s for s in self.night.sessions if s["field"] == field]
        if self.anchor and n < len(recorded):
            move, recorded_move = 0.0, True
            self.t = recorded[n]["first"] - exposure
        else:
            move, recorded_move = self.cond.move(self.at, field, self.t)
        self.t += move
        self.spent["moves"] += move
        self.at = field
        frames = self.policy.frames_asked(frames, minutes)
        v = Visit(step, field, kind, exposure=exposure, start=self.t, asked=rule["accepted"] if rule else frames,
                  move_recorded=recorded_move)
        began = self.t
        log, same, light = [], 0, []

        def stop():
            if rule:
                return shoot.goal_stop(log, v.captured, self.t - began, rule)
            return self.policy.stop(v.captured, frames, log, self.t - began, minutes)
        while (why_stop := stop()) is None:
            lost = self.cond.stall(self.t)
            if lost == float("inf"):
                self.spent["stalls"] += max(0.0, hard - self.t) if hard else 0.0
                v.stall_s += max(0.0, hard - self.t) if hard else 0.0
                self.t = hard if hard else self.night.end
                v.stopped_by = "the camera never came back"
                break
            if hard is not None and self.t + lost + exposure > hard:
                v.stopped_by = "the step's end"
                break
            self.t += lost
            self.spent["stalls"] += lost
            v.stall_s += lost
            p_cloud, recorded_sky = self.cond.cloud(self.t, field)
            same += recorded_sky
            if v.first_frame is None:
                v.first_frame = self.t
            gap = self.cond.gap(exposure)
            self.t += exposure + gap
            self.spent["between frames"] += gap
            v.captured += 1
            r = self.cond.rng.random()
            accepted = r >= p_cloud + self.cond.trailed
            v.cloud += r < p_cloud
            log.append({"flux": 1.0, "accepted": accepted,
                        "reason": "" if accepted else ("too few stars (cloud?)" if r < p_cloud else "trailed")})
            self.spent["accepted" if accepted else "rejected"] += exposure
            if accepted:
                v.accepted += 1
                light.append(self.cond.transparency(self.t, field))
            if self.t >= self.night.end + 3600:      # a run with no end to it stops with the night
                break
        v.stopped_by = v.stopped_by or why_stop or "the night's end"
        v.end = self.t
        v.recorded_share = round(same / v.captured, 2) if v.captured else 0.0
        # The quality pass as restack does it: frames whose star light falls
        # under PASS_FLUX of the better half's are cloud, then the best KEEP.
        if light:
            top = sorted(light, reverse=True)[:max(3, len(light) // 2)]
            typical = statistics.median(top)
            passed = [r for r in light if r >= PASS_FLUX * typical]
            v.stacked = int(round(len(passed) * KEEP))
            seen = statistics.median(sorted(passed, reverse=True)[:max(1, v.stacked)]) if passed else 1.0
        else:
            v.stacked, seen = 0, 1.0
        # Depth is decided at the end of the visit: what the telescope knows then.
        v.depth = self.cond.depth(v.start, v.stacked * exposure, seen, decided=v.end) \
            if v.stacked >= SEARCHABLE else None
        why = None
        if not goals:
            v.search = v.search_source = "none"
        elif v.stacked < SEARCHABLE:
            v.search, v.search_source = "too few frames", "modelled"
        elif (v.depth or 0) < TOO_SHALLOW:
            v.search, v.search_source = "too shallow", "modelled"
        else:
            rec = self.recorded_visit(field, v.start)
            v.search, v.search_source = self.cond.search(field, self.night.searches.get(rec["folder"].name)
                                                         if rec else None)
            why = None if v.search == "searched" else v.search
        state = "none" if not goals else "searched" if v.search == "searched" else "stopped"
        r = {"captured": v.captured, "stacked": v.stacked, "depth_g": v.depth,
             "gap_minutes": 0, "gaps": 0, "camera_retries": None,
             "rejected": {"cloud": v.cloud, "trailed": 0, "other": 0},
             "search": state, "search_stopped": why or (v.search if state == "stopped" else None)}
        v.verdicts = {k: val for k, val in outcome.judge(r, goals).items() if k != "limited_by"}
        self.visits.append(v)
        return v

    def due(self, step, began, queued):
        """schedule.due for the replay: the next queued step's label once the
        running step has used its planned minutes."""
        return queued if queued and self.t >= began + 60 * step["minutes"] else None

    def patrol(self, step, command, began, hard, queued):
        pol = self.policy
        name = command[command.index(next(c for c in command if Path(c).name == "patrol.py")) + 1]
        p = dict(pol.programme(name))
        if option(command, "--minutes"):
            p["minutes"] = option(command, "--minutes")
        budget = option(command, "--budget")
        if p.get("mosaic"):
            # The panels in the order the night took them: patrol.priorities
            # ordered them then from what it knew, which a replay can't rebuild.
            order = panel_order(self.night, p["mosaic"], step.get("started") or self.night.start,
                                step.get("finished") or self.night.end)
            rows = [{"field": f, "minutes": pol.visit(p["minutes"])} for f in order]
            chosen = [r["field"] for r in pol.panels(rows, budget)]
        else:
            p["minutes"] = pol.field_minutes(p["minutes"], budget)
            import stacking
            chosen = [stacking.folder_name(p["target"])]
        deadline = pol.deadline(began, budget)
        goals = p.get("goals") or {}
        done = []
        for field in chosen:
            if hard is not None and self.t >= hard:
                break
            if not pol.room(deadline, self.t, pol.visit(p["minutes"])):
                continue
            minutes = pol.shoot_minutes(p["minutes"] * pol.shoot_cap(), deadline, self.t)
            frames = pol.frames_for(p["minutes"], p["exposure"])
            field_goals = goals or outcome.programme_for(field)[1]
            rule = pol.capture_rule(self, field, minutes, p["exposure"])
            done.append(self.capture(step["label"], field, "panel" if p.get("mosaic") else "field",
                                     frames, minutes, p["exposure"], hard, field_goals, rule=rule))
        # Second looks: a mosaic's once the panels are done, each with the
        # GoTo back (its searches finish in the background), as patrol.run
        # does. One field's patrol lets the telescope go once its frames are
        # in (patrol.main: --release unless --wait), and its second look is
        # a step of its own; with --wait it is taken at once.
        for v in done:
            if not self.unexplained(v) or (len(chosen) == 1 and "--wait" not in command):
                continue
            weighed = pol.weighed(self)
            if len(chosen) > 1:
                why = pol.look_put_off(self.due(step, began, queued), pol.look_room(deadline, self.t), budget or 0,
                                       weighed)
            else:
                why = pol.look_put_off(None, pol.room(deadline, self.t, patrol.CONFIRM_MINUTES
                                                      * (1 + patrol.STALL_SHARE)), budget or 0, weighed)
            if why:
                self.deferred_looks += 1
                continue
            frames = patrol.second_look_frames(patrol.CONFIRM_MINUTES, p["exposure"])
            look = self.capture(step["label"], v.field, "second look", frames, None, p["exposure"], hard,
                                goals or outcome.programme_for(v.field)[1])
            self.follow_up_used += look.end - look.start

    def shoot(self, step, command, hard):
        import stacking
        at = next(i for i, c in enumerate(command) if Path(c).name == "shoot.py")
        field = stacking.folder_name(command[at + 1])
        exposure = option(command, "--exposure") or 16.0
        self.capture(step["label"], field, "shoot", option(command, "--frames", int), option(command, "--minutes"),
                     exposure, hard, outcome.programme_for(field)[1])

    def run(self):
        """The plan's steps: in order, or with Phases 3 and 4 as the
        policy chooses them (windows.choose, dispatch.choose) at each
        step's end, a flexible one told the cutoff before a protected start."""
        pending = [dict(s, status="queued") for s in self.plan.get("steps", [])]
        while pending:
            step, cut = pending[0], None
            if self.policy.chooses and self.t < self.night.end:
                chosen, cut, hold = self.policy.choose(self, pending)
                if chosen is None and hold:
                    self.spent["waiting for a timed step"] += hold
                    self.t += hold
                    continue
                if chosen is None:
                    # Nothing left up before dawn: the runner leaves them queued.
                    for s in pending:
                        self.steps.append({"label": s["label"], "planned": s["minutes"], "start": self.t,
                                           "end": self.t, "minutes": 0.0, "skipped": "not up again before dawn",
                                           "protected": bool(s.get("not_before"))})
                        self.not_up.append(s["label"])
                    break
                step = chosen
            pending.remove(step)
            self.run_step(step, cut, pending[0]["label"] if pending else None)
        return self

    def run_step(self, step, cut, queued):
        import dispatch
        entry = {"label": step["label"], "planned": step["minutes"], "protected": bool(step.get("not_before"))}
        if self.t >= self.night.end:
            self.steps.append(dict(entry, start=self.t, end=self.t, minutes=0.0, skipped="the night was over"))
            return
        if step.get("not_before") and self.policy.chooses:
            # Chosen at its launch: its setup is under way before its time.
            entry["window"] = schedule.not_before(step["not_before"], self.t, self.sunset)
        elif step.get("not_before"):
            entry["window"] = schedule.not_before(step["not_before"], self.t, self.sunset)
            if self.t < entry["window"]:
                self.spent["waiting for a timed step"] += entry["window"] - self.t
                self.t = entry["window"]
        if step.get("until"):
            entry["until"] = schedule.not_before(step["until"], self.t, self.sunset)
        begin = self.t
        command, left = self.policy.prepare(step, self.t, self.at, self.sunset, cut=cut)
        if command is None:
            self.steps.append(dict(entry, start=begin, end=begin, minutes=0.0, skipped=f"{max(left, 0)} s left"))
            return
        hard = begin + float(command[2]) if command[0] == "timeout" else None
        visits_before = len(self.visits)
        if any(Path(c).name == "patrol.py" for c in command[:5]):
            self.patrol(step, command, begin, hard, queued)
        elif any(Path(c).name == "shoot.py" for c in command[:5]):
            self.shoot(step, command, hard)
        else:
            # Focus, a GoTo or anything else: its planned minutes, said so.
            self.t += 60 * step["minutes"]
            self.spent["steps not modelled"] += 60 * step["minutes"]
            entry["not_modelled"] = True
        mine = self.visits[visits_before:]
        first = next((v.first_frame for v in mine if v.first_frame is not None), None)
        self.steps.append(dict(entry, start=begin, end=self.t, first_frame=first,
                               minutes=round((self.t - begin) / 60, 1)))
        self.last_target = dispatch.what(step)[0]


def measures(run):
    """What one replay got, as numbers. Constraints first, pass or fail."""
    judged = [v for v in run.visits if v.verdicts.get("searchable") not in ("not judged", None)]
    worth_fields = {v.field for v in judged if v.verdicts.get("worth_it") == "met"}
    windows = [st for st in run.steps if st.get("protected")]
    late = [max(0.0, (st["first_frame"] if st.get("first_frame") is not None else run.night.end + 3600)
                - st["window"]) for st in windows if st.get("window")]
    span = max(run.night.end, run.t) - run.night.start
    spent = {k: round(v / 60, 1) for k, v in run.spent.items()}
    spent["unused"] = round(max(0.0, span - sum(run.spent.values())) / 60, 1)
    searched = [v for v in run.visits if v.search_source in ("recorded", "modelled")
                and v.search not in ("too few frames", "too shallow")]
    out = {
        # A protected step (one the person timed) whose first frame came more
        # than ON_TIME_S after its time, or never: the GoTo and setup count.
        "protected_starts_missed": sum(1 for s in late if s > ON_TIME_S),
        "protected_start_late_s": round(max(late), 0) if late else 0.0,
        # A step told an end time that ran past it by more than a minute, and
        # one that ran past even the backstop's hard stop (which must not).
        "ends_overrun": sum(1 for st in run.steps if st.get("until") and st["end"] > st["until"] + 60),
        "ends_past_backstop": sum(1 for st in run.steps if st.get("until")
                                  and st["end"] > st["until"] + schedule.BACKSTOP_S + 60),
        "visits": len(run.visits),
        "searchable_visits": sum(v.verdicts.get("searchable") == "met" for v in judged),
        "fields_worth_it": len(worth_fields),
        "desired_met": sum(v.verdicts.get("desired") in ("met", "more than asked") for v in judged),
        "searches_failed_subtraction": sum(v.search == "subtraction" for v in run.visits),
        "searches_without_reference": sum(v.search == "no reference" for v in run.visits),
        "searches_modelled_share": round(sum(v.search_source == "modelled" for v in searched) / len(searched), 2)
        if searched else 0.0,
        # Each visit's own exposure, not one length for all.
        "accepted_minutes": round(sum(v.accepted * v.exposure for v in run.visits) / 60, 1),
        "second_looks": sum(v.kind == "second look" for v in run.visits),
        "second_looks_put_off": run.deferred_looks,
        # Phase 4: protected steps started when the planner's skyline (and its
        # margin) said their target was down: their time, not dispatch's choice.
        "steps_below_skyline_limit": len(run.below_limit),
        # Phase 4: steps left queued because their target was not up again before dawn.
        "steps_not_up": len(run.not_up),
        "last_step_minutes": run.steps[-1]["minutes"] if run.steps else 0.0,
        "recorded_share": round(statistics.mean([v.recorded_share for v in run.visits]), 2) if run.visits else 0.0,
    }
    for k, v in spent.items():
        out[f"time: {k}"] = v
    for st in run.steps:
        out[f"minutes: {st['label']}"] = st["minutes"]
    return out


def costs_for(night, data=None):
    """history.costs from the nights before this one only: a replay must not
    learn its costs from the night it replays."""
    return history.costs(data=data, before=night.evening)


def replay(night, policy, runs=50, seed=1, stress=None, costs=None, protect=None, calibration="chronological"):
    """`runs` replays, each with its own draw of what is modelled: each
    measure's spread, and the first run's visits for a person to read."""
    costs = costs or costs_for(night)
    plan = protected_step(night, protect) if protect else None
    rules = policy() if isinstance(policy, type) else policy
    results, first = [], None
    for i in range(runs):
        cond = Conditions(night, costs, random.Random(seed + i), stress, calibration)
        r = Run(night, rules, cond, plan=plan).run()
        first = first or r
        results.append(measures(r))
    keys = list(results[0])
    summary = {k: history.spread([m.get(k) for m in results]) for k in keys}
    return {"policy": rules.name, "reconstructed": rules.reconstructed, "runs": runs, "stress": stress,
            "protect": protect, "calibration": calibration, "costs_before": costs.get("before"),
            "costs_nights": costs.get("nights"), "measures": summary, "not_modelled": NOT_MODELLED,
            "visits": [visit_dict(v) for v in first.visits]}


def visit_dict(v):
    return {"step": v.step, "field": v.field, "kind": v.kind,
            "start": datetime.fromtimestamp(v.start).strftime("%H:%M"),
            "minutes": round((v.end - v.start) / 60, 1), "asked": v.asked, "captured": v.captured,
            "accepted": v.accepted, "stacked": v.stacked, "exposure": v.exposure,
            "depth_g": None if v.depth is None else round(v.depth, 2),
            "search": v.search, "search_source": v.search_source,
            "stopped_by": v.stopped_by, "stall_minutes": round(v.stall_s / 60, 1), "cloud": v.cloud,
            "shortfall": shortfall(v),
            "recorded_share": v.recorded_share, "move_recorded": v.move_recorded, **v.verdicts}


def shortfall(v):
    """Why a visit fell short of its minimum (searchable), from what the
    replay recorded of it: its stalls, its cloud, the quality pass, what
    stopped it. None if it met it or has no minimum."""
    if v.verdicts.get("searchable") != "short":
        return None
    causes = []
    if v.stall_s >= 60:
        causes.append(f"camera stalls {v.stall_s / 60:.1f} min")
    if v.cloud:
        causes.append(f"cloud {v.cloud} frames")
    if v.captured and v.stacked < SEARCHABLE <= v.accepted:
        causes.append(f"the quality pass kept {v.stacked} of {v.accepted}")
    if v.search not in ("searched", "none", "too few frames"):
        causes.append(f"search: {v.search}")
    causes.append(f"stopped: {v.stopped_by}")
    return "; ".join(causes)


# --- checking the engine against the record ------------------------------------

def check(night, runs=50, seed=1, costs=None, calibration="chronological"):
    """The as-run policy set against what the night recorded, in two parts
    reported apart: the acquisition model (each visit started where the
    record started it: cadence, stalls, cloud, the quality pass, depth and
    the search's end) and the whole night (the as-run rules from the night's
    start: which visits, in what order, and each step's timing)."""
    costs = costs or costs_for(night)
    return {"night": night.evening.isoformat(), "runs": runs, "calibration": calibration,
            "costs_before": costs.get("before"), "costs_nights": costs.get("nights"),
            "independent": night.evening.isoformat() not in TUNED_ON,
            "acquisition": acquisition_check(night, runs, seed, costs, calibration),
            "whole_night": night_check(night, runs, seed, costs, calibration)}


def acquisition_check(night, runs, seed, costs, calibration):
    per = {}
    for i in range(runs):
        cond = Conditions(night, costs, random.Random(seed + i), calibration=calibration)
        r = Run(night, AsRun(), cond, anchor=True).run()
        counts = {}
        for v in r.visits:
            n = counts.get(v.field, 0)
            counts[v.field] = n + 1
            per.setdefault((v.field, n), []).append(v)
    rows = []
    seen = {}
    for s in night.sessions:
        n = seen.get(s["field"], 0)
        seen[s["field"]] = n + 1
        rec = outcome.of_session(s["folder"])
        sims = per.get((s["field"], n), [])

        def mid(attr):
            vals = [getattr(v, attr) for v in sims if getattr(v, attr) is not None]
            return history.spread(vals)
        agree = None
        if sims and rec["searchable"] in ("met", "short"):
            agree = round(sum(v.verdicts.get("searchable") == rec["searchable"] for v in sims) / len(sims), 2)
        rows.append({"field": s["field"], "session": s["folder"].name,
                     "recorded": {"captured": rec["captured"], "accepted": rec["accepted"], "stacked": rec["stacked"],
                                  "depth_g": rec["depth_g"], "searchable": rec["searchable"],
                                  "search": night.searches.get(s["folder"].name)},
                     "replayed": {"captured": mid("captured"), "accepted": mid("accepted"),
                                  "stacked": mid("stacked"), "depth_g": mid("depth"),
                                  "runs_with_it": len(sims)},
                     "searchable_agrees": agree})
    return {"sessions": rows, "agreement": agreement(rows)}


def night_check(night, runs, seed, costs, calibration):
    """The as-run rules from the night's start, unanchored: each step's
    start and length against the plan's record, and the visits' order
    against the sessions'."""
    recorded_order = [s["field"] for s in night.sessions]
    steps, orders, counts = {}, [], []
    for i in range(runs):
        cond = Conditions(night, costs, random.Random(seed + i), calibration=calibration)
        r = Run(night, AsRun(), cond).run()
        for st in r.steps:
            steps.setdefault(st["label"], []).append(st)
        order = [v.field for v in r.visits]
        orders.append(order)
        counts.append(len(order))
    rows = []
    for st in night.plan.get("steps", []):
        sims = steps.get(st["label"], [])
        row = {"label": st["label"], "recorded_start": st.get("started"),
               "recorded_minutes": round((st["finished"] - st["started"]) / 60, 1)
               if st.get("started") and st.get("finished") else None,
               "replayed_start_error_minutes": history.spread(
                   [(s["start"] - st["started"]) / 60 for s in sims]) if st.get("started") else None,
               "replayed_minutes": history.spread([s["minutes"] for s in sims])}
        rows.append(row)
    same_order = sum(o == recorded_order for o in orders) / len(orders) if orders else 0.0
    prefix = statistics.median([common_prefix(o, recorded_order) for o in orders]) if orders else 0
    starts = [abs(r["replayed_start_error_minutes"]["median"]) for r in rows if r["replayed_start_error_minutes"]]
    lengths = [abs(r["replayed_minutes"]["median"] - r["recorded_minutes"]) for r in rows
               if r["replayed_minutes"] and r["recorded_minutes"] is not None]
    return {"steps": rows, "recorded_visits": len(recorded_order),
            "replayed_visits": history.spread(counts),
            "agreement": {"same_visit_order_share": round(same_order, 2),
                          "visits_in_recorded_order_median": prefix,
                          "step_start_error_minutes": round(statistics.median(starts), 1) if starts else None,
                          "step_length_error_minutes": round(statistics.median(lengths), 1) if lengths else None}}


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def agreement(rows):
    """How close the replay came, over the sessions both have: the median
    error of each count as a share of the recorded one, of depth in mag,
    and the share of runs whose searchable verdict matched the record's."""
    out = {}
    for key in ("captured", "accepted", "stacked"):
        errs = [abs(r["replayed"][key]["median"] - r["recorded"][key]) / r["recorded"][key]
                for r in rows if r["replayed"][key] and r["recorded"][key]]
        out[f"{key}_error_share"] = round(statistics.median(errs), 3) if errs else None
    depth = [abs(r["replayed"]["depth_g"]["median"] - r["recorded"]["depth_g"])
             for r in rows if r["replayed"]["depth_g"] and r["recorded"]["depth_g"] is not None]
    out["depth_error_mag"] = round(statistics.median(depth), 2) if depth else None
    out["depth_error_mag_worst"] = round(max(depth), 2) if depth else None
    agrees = [r["searchable_agrees"] for r in rows if r["searchable_agrees"] is not None]
    out["searchable_agrees"] = round(statistics.mean(agrees), 2) if agrees else None
    return out


# --- the command ---------------------------------------------------------------

def say_replay(result, say=print):
    say(f"== {result['policy']}" + (" (reconstructed: no running code behind it)" if result["reconstructed"] else
                                    " (the running code's rules)")
        + (f", stress {result['stress']}" if result["stress"] else "")
        + (f", a step protected at {result['protect']}" if result["protect"] else "")
        + f" ({result['runs']} runs; costs from {result['costs_nights']} nights before {result['costs_before']}, "
          f"depth calibrated {result['calibration']})")
    for k, s in result["measures"].items():
        if s is None:
            continue
        say(f"  {k}: {s['median']:g} (10-90% {s['p10']:g}-{s['p90']:g})")
    say("  not modelled: " + "; ".join(result["not_modelled"]))


def say_check(result, say=print):
    say(f"The as-run rules against the record, night of {result['night']} ({result['runs']} runs; costs from "
        f"{result['costs_nights']} nights before it, depth calibrated {result['calibration']})")
    if not result["independent"]:
        say("  This night was used to build the engine: agreement here is not an independent test. "
            "Nights with a kept plan from 4 November 2026 on are.")
    acq = result["acquisition"]
    say("1. Acquisition, each visit started where the record started it:")
    say(f"  {'session':<22} {'captured':>14} {'accepted':>14} {'stacked':>14} {'depth G':>16}  search")
    for row in acq["sessions"]:
        rec, rep = row["recorded"], row["replayed"]

        def cell(key):
            s = rep[key]
            got = "-" if s is None else f"{s['median']:g}"
            return f"{rec[key] if rec[key] is not None else '-'} / {got}"
        say(f"  {row['field'] + ' ' + row['session'][9:13]:<22} {cell('captured'):>14} {cell('accepted'):>14} "
            f"{cell('stacked'):>14} {cell('depth_g'):>16}  {rec['search'] or '-'}")
    say("  (recorded / replayed median; '-' where the replay never reached that visit)")
    for row in acq["sessions"]:
        if row["searchable_agrees"] is not None and row["searchable_agrees"] < 0.5:
            say(f"  searchable disagrees: {row['field']} {row['session'][9:13]} recorded {row['recorded']['searchable']}, "
                f"the replay agrees in {100 * row['searchable_agrees']:.0f}% of runs")
    a = acq["agreement"]

    def pct(v):
        return "-" if v is None else f"{100 * v:.0f}%"
    say(f"  Agreement: captured within {pct(a['captured_error_share'])}, accepted {pct(a['accepted_error_share'])}, "
        f"stacked {pct(a['stacked_error_share'])} (median); depth {a['depth_error_mag']} mag "
        f"(worst {a['depth_error_mag_worst']}); searchable verdict as recorded in {pct(a['searchable_agrees'])} of runs")
    whole = result["whole_night"]
    w = whole["agreement"]
    say("2. Whole night, the as-run rules from the night's start:")
    for row in whole["steps"]:
        err, mins = row["replayed_start_error_minutes"], row["replayed_minutes"]
        say(f"  {row['label']:<28} recorded {row['recorded_minutes']} min, replayed "
            f"{'-' if mins is None else mins['median']:} min; start "
            f"{'-' if err is None else format(err['median'], '+.1f')} min from the record")
    rv = whole["replayed_visits"]
    say(f"  Agreement: steps start within {w['step_start_error_minutes']} min and last within "
        f"{w['step_length_error_minutes']} min of the record (median); {whole['recorded_visits']} visits recorded, "
        f"{'-' if rv is None else rv['median']:} replayed; the same visits in the same order in "
        f"{pct(w['same_visit_order_share'])} of runs, the first {w['visits_in_recorded_order_median']} in order "
        f"(median)")


def run(args, say=print):
    evening = date.fromisoformat(args.night)
    night = load(evening)
    costs = costs_for(night)
    calibration = getattr(args, "calibration", "chronological")
    if args.check:
        result = check(night, args.runs, costs=costs, calibration=calibration)
        say_check(result, say)
        return result
    names = args.policy.split(",")
    unknown = [n for n in names if n not in POLICIES]
    if unknown:
        raise interface.Refusal("INVALID_REQUEST", f"No policy {', '.join(unknown)}: {', '.join(POLICIES)}")
    results = [replay(night, POLICIES[n], args.runs, stress=args.stress, costs=costs,
                      protect=getattr(args, "protect", None), calibration=calibration) for n in names]
    for r in results:
        say_replay(r, say)
    return {"night": evening.isoformat(), "replays": results}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("night", help="the evening's date (YYYY-MM-DD)")
    ap.add_argument("--policy", default="as-run,current",
                    help="policies to replay, comma-separated: as-run, current, goals (Phase 2), windows "
                         "(Phase 3), dispatch (Phase 4)")
    ap.add_argument("--runs", type=int, default=50, help="replays of each, each with its own draw of the modelled parts")
    ap.add_argument("--stress", choices=["camera-dead", "flicker", "no-frames", "depth-wrong"],
                    help="the night made worse in one way")
    ap.add_argument("--protect", metavar="HH:MM",
                    help="put a step the person times for HH:MM in the plan, and see whether it starts on time")
    ap.add_argument("--calibration", choices=["chronological", "leave-one-out"], default="chronological",
                    help="depth calibrated only by stacks measured before (default), or by every other stack")
    ap.add_argument("--check", action="store_true", help="the as-run rules against what was recorded")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("nightreplay", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
