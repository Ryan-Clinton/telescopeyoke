#!/usr/bin/env python3
"""Replay a recorded night under a scheduling policy, to compare policies
on the same sky (docs/observing-plan-spec.md, Phase 5).

    ./nightreplay.py 2026-11-03                       the night's own plan, as-run and current, 50 runs each
    ./nightreplay.py 2026-11-03 --check               the as-run policy against what was recorded
    ./nightreplay.py 2026-11-03 --stress camera-dead  the same night with the camera failing at its middle
    ./nightreplay.py 2026-11-03 --json

What it uses, and how each figure is labelled:

- Recorded: the night's plan (cache/schedules/DATE.json), the frames
  taken and why each was rejected, the gaps between them, the moves
  between sessions, the depth inputs (star width and sky) measured that
  night, and which fields' searches found something unexplained.
- Modelled: everything the record cannot say. A field at a time the
  telescope was not on it borrows the cloud of the frames taken nearest
  that time, from whatever field. Cadence, moves, the quality pass's
  stacked share and depth come from the night's own measures or
  history.py's, with their spread. Monte Carlo runs give each measure its
  uncertainty.

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
from datetime import date, datetime
from pathlib import Path

import config
import history
import interface
import outcome

NEAR_S = 5 * 60          # a recorded frame this close in time stands for the sky then
FAR_S = 15 * 60          # beyond this, the night's overall cloud is used
SEARCHABLE = 8           # stacked frames the search needs (vet.HALVES_FROM)
KEEP = 0.85              # restack.select's share of the frames that pass, best first
PASS_FLUX = 0.6          # stacking.judge: a frame under this share of the better half's star light is cloud
TOO_SHALLOW = 16.0       # G: patrol.analyse's "too shallow to search" for M31's fields
PANEL_FIELD = re.compile(r"(.+)-P(\d+)$")


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
    unexplained: set             # fields whose search found something unexplained
    start: float
    end: float
    frame_gaps: list             # seconds beyond the exposure between frames, this night's
    stacked_shares: list


def unexplained_in(folder):
    """Whether a session's search left anything unexplained."""
    record = outcome._json(Path(folder) / "patrol.json") or {}
    for line in record.get("summary", []):
        found = re.match(r"\s*(?:Unexplained:\s*)?(\d+)(?:\s+unexplained)?\b", line)
        if found and ("nexplained" in line) and int(found.group(1)) > 0:
            return True
    return False


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
                 {s["field"] for s in rows if unexplained_in(s["folder"])}, start, end, gaps, shares)


# --- the sky and the kit at a moment ------------------------------------------

class Conditions:
    """What a frame taken at a moment on a field would have met: recorded
    where the night says, modelled where it doesn't. `stress` overrides."""

    def __init__(self, night, costs, rng, stress=None):
        self.night, self.costs, self.rng, self.stress = night, costs, rng, stress
        times = [f[0] for f in night.frames]
        self.first, self.last = (min(times), max(times)) if times else (night.start, night.end)
        clouded = [f for f in night.frames if f[2] == "cloud"]
        self.cloud_overall = len(clouded) / max(1, len(night.frames))
        trailed = costs["rejections"]["share"].get("trailed", 0.0)
        self.trailed = trailed
        self.middle = (night.start + night.end) / 2

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

    def stacked(self, offered):
        pool = self.night.stacked_shares
        share = self.rng.choice(pool) if pool else ((self.costs["stacked_share"] or {}).get("median", 0.85))
        return int(round(offered * share))

    def depth(self, t, seconds, transparency=1.0):
        """Modelled depth (G) of a stack of `seconds` made at t, or None.
        The depth model with the star width and sky measured nearest that
        time, calibrated by the night's own measured stacks: the model is
        pooled over many nights, and 4 November's stacks sit 0.6 to 0.9 mag
        deeper than it. A stack measured at the same time is left out of
        the calibration, so a replay never reads back its own answer."""
        model = self.costs.get("depth_model")
        if not model or not self.night.depth_inputs or seconds <= 0:
            return None
        import depth
        near = min(self.night.depth_inputs, key=lambda d: abs(d["mid"] - t))
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


# --- the policies ----------------------------------------------------------------

@dataclass
class Policy:
    """How the scheduling code chose and ran visits."""
    name: str
    panel_minutes: float
    cap: float                 # shoot.py's --minutes as a multiple of the visit's
    frame_gap_s: float         # the pace the frame count was worked out from
    budget: bool               # a patrol kept to its step's minutes (with room checks)
    stall_share: float = 0.0   # planned extra for stalls, in visit_minutes
    overhead: float = 1.5      # planned minutes for the GoTo
    second_look_cap: float | None = None   # minutes; None: as many frames as asked, however long
    backstop_min: float | None = None
    minutes_mean_minutes: bool = False     # shoot.py --minutes with no --frames runs for the minutes

    def visit_minutes(self, minutes):
        return minutes * (1 + self.stall_share) + self.overhead


# As the code ran on the night of 3 to 4 November 2026: five-minute panels,
# the frame count from the exposure alone, no budget, second looks after.
AS_RUN = Policy("as-run 3 Nov", panel_minutes=5, cap=1.1, frame_gap_s=0.0, budget=False)
# The code since 4 November 2026: eight-minute panels planned with stalls
# and the GoTo, frames at the camera's pace, captures that make up stalled
# frames, and a budget kept as the patrol runs.
CURRENT = Policy("current", panel_minutes=8, cap=1.5, frame_gap_s=5.6, budget=True, stall_share=0.25,
                 overhead=2.5, second_look_cap=None, backstop_min=15, minutes_mean_minutes=True)
POLICIES = {"as-run": AS_RUN, "current": CURRENT}


@dataclass
class Visit:
    step: str
    field: str
    kind: str                  # panel, field, second look, shoot
    start: float = 0.0
    end: float = 0.0
    asked: int = 0
    captured: int = 0
    accepted: int = 0
    cloud: int = 0
    stacked: int = 0
    depth: float | None = None
    recorded_share: float = 0.0
    move_recorded: bool = True
    verdicts: dict = dc_field(default_factory=dict)


def programme_of(name):
    import patrol
    return patrol.programme(name)


def steps_of(night):
    """The plan's steps as (label, kind, fields or target, minutes,
    exposure, until, planned minutes), from each step's command."""
    import patrol
    import stacking
    out = []
    for st in night.plan.get("steps", []):
        cmd = [Path(c).name if c.endswith(".py") else c for c in st["command"]]
        until = None
        if st.get("until"):
            until = st.get("finished") or None
        if cmd[0] == "patrol.py":
            p = programme_of(cmd[1])
            minutes = float(cmd[cmd.index("--minutes") + 1]) if "--minutes" in cmd else p["minutes"]
            if p.get("mosaic"):
                out.append({"label": st["label"], "kind": "mosaic", "programme": cmd[1], "mosaic": p["mosaic"],
                            "exposure": p["exposure"], "planned": st["minutes"], "until": until, "goals":
                            p.get("goals", {})})
            else:
                out.append({"label": st["label"], "kind": "field", "field": stacking.folder_name(p["target"]),
                            "programme": cmd[1] if (patrol.PROGRAMMES / f"{cmd[1]}.toml").exists() else None,
                            "minutes": minutes, "exposure": p["exposure"], "planned": st["minutes"],
                            "until": until, "goals": p.get("goals", {}) or outcome.programme_for(
                                stacking.folder_name(p["target"]))[1]})
        elif cmd[0] == "shoot.py":
            target = cmd[1]
            minutes = float(cmd[cmd.index("--minutes") + 1]) if "--minutes" in cmd else st["minutes"]
            exposure = float(cmd[cmd.index("--exposure") + 1]) if "--exposure" in cmd else 16.0
            frames = int(cmd[cmd.index("--frames") + 1]) if "--frames" in cmd else None
            out.append({"label": st["label"], "kind": "shoot", "field": stacking.folder_name(target),
                        "minutes": minutes, "exposure": exposure, "planned": st["minutes"], "until": until,
                        "frames": frames, "goals": {}})
    return out


def panel_order(night, step, start, end):
    """The panels in the order that night took them, then the rest."""
    seen = []
    for s in night.sessions:
        m = PANEL_FIELD.match(s["field"])
        if m and m.group(1) == step["mosaic"] and start - 60 <= s["first"] <= end and s["field"] not in seen:
            seen.append(s["field"])
    rest = [f"{step['mosaic']}-P{n}" for n in range(1, 9) if f"{step['mosaic']}-P{n}" not in seen]
    return seen + rest


# --- running a night -----------------------------------------------------------

class Run:
    """One replay of the night under one policy and one draw of the modelled parts."""

    def __init__(self, night, policy, cond, anchor=False):
        self.night, self.policy, self.cond = night, policy, cond
        # With anchor, each visit starts where the record says that visit
        # started (the check): it tests the visit's model, not timing drift.
        self.anchor = anchor
        self.seen = {}
        self.t = night.start
        self.at = None
        self.visits = []
        self.steps = []
        self.deferred_looks = 0

    def capture(self, step, field, kind, minutes, exposure, frames, cap_minutes, deadline, goals, retakes=True):
        n = self.seen.get(field, 0)
        self.seen[field] = n + 1
        recorded = [s for s in self.night.sessions if s["field"] == field]
        if self.anchor and n < len(recorded):
            move, recorded_move = 0.0, True
            self.t = recorded[n]["first"] - exposure
        else:
            move, recorded_move = self.cond.move(self.at, field, self.t)
        self.t += move
        self.at = field
        v = Visit(step, field, kind, start=self.t, asked=frames, move_recorded=recorded_move)
        stop = min(deadline, self.t + 60 * cap_minutes) if cap_minutes else deadline
        rejected_run, extra, same = 0, 0, 0
        light = []
        while self.t < stop:
            limit = frames + (min(extra, max(2, frames // 4)) if retakes and rejected_run < 3 else 0)
            if v.captured >= limit:
                break
            lost = self.cond.stall(self.t)
            if lost == float("inf"):
                self.t = stop
                break
            self.t += lost
            if self.t + exposure > stop:
                break
            p_cloud, recorded = self.cond.cloud(self.t, field)
            same += recorded
            self.t += exposure + self.cond.gap(exposure)
            v.captured += 1
            r = self.cond.rng.random()
            if r < p_cloud:
                v.cloud += 1
                extra += 1
                rejected_run += 1
            elif r < p_cloud + self.cond.trailed:
                extra += 1
                rejected_run += 1
            else:
                v.accepted += 1
                rejected_run = 0
                light.append(self.cond.transparency(self.t, field))
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
        v.depth = self.cond.depth(v.start, v.stacked * exposure, seen) if v.stacked >= SEARCHABLE else None
        searched = goals and v.stacked >= SEARCHABLE and (v.depth or 0) >= TOO_SHALLOW
        r = {"captured": v.captured, "stacked": v.stacked if goals else v.stacked, "depth_g": v.depth,
             "gap_minutes": 0, "gaps": 0, "camera_retries": None,
             "rejected": {"cloud": v.cloud, "trailed": 0, "other": 0},
             "search": ("searched" if searched else "stopped") if goals else "none", "search_stopped": None}
        v.verdicts = {k: val for k, val in outcome.judge(r, goals).items() if k != "limited_by"}
        self.visits.append(v)
        return v

    def run_step(self, step):
        pol = self.policy
        begin = self.t
        deadline = step["until"] or self.night.end
        budget_end = begin + 60 * step["planned"] if pol.budget and step["kind"] != "shoot" else None
        hard = min(deadline, budget_end + 60 * (pol.backstop_min or 0)) if budget_end else deadline

        def room(minutes):
            return budget_end is None or (budget_end - self.t) / 60 >= minutes

        def frames_for(minutes, exposure):
            return max(1, round(60 * minutes / (exposure + pol.frame_gap_s)))

        if step["kind"] == "mosaic":
            minutes, exposure = pol.panel_minutes, step["exposure"]
            done = []
            order = panel_order(self.night, step, self.night.start, self.night.end)
            if pol.budget:
                fit = int(step["planned"] // pol.visit_minutes(minutes))
                order = order[:max(fit, 0)]
            for f in order:
                if self.t >= hard:
                    break
                if not room(pol.visit_minutes(minutes)):
                    break
                cap = minutes * pol.cap
                if budget_end:
                    cap = max(1.0, min(cap, (budget_end - self.t) / 60))
                done.append(self.capture(step["label"], f, "panel", minutes, exposure,
                                         frames_for(minutes, exposure), cap, hard, step["goals"]))
            for v in done:
                if v.field not in self.night.unexplained:
                    continue
                if not room(pol.visit_minutes(10)):
                    self.deferred_looks += 1
                    continue
                self.capture(step["label"], v.field, "second look", 10, exposure, 38,
                             pol.second_look_cap, hard, step["goals"])
        elif step["kind"] == "field":
            minutes, exposure = step["minutes"], step["exposure"]
            if pol.budget:
                minutes = min(minutes, max(1.0, (step["planned"] - pol.overhead) / (1 + pol.stall_share)))
            cap = minutes * pol.cap
            if budget_end:
                cap = min(cap, (budget_end - self.t) / 60)
            self.capture(step["label"], step["field"], "field", minutes, exposure,
                         frames_for(minutes, exposure), cap, hard, step["goals"])
        else:
            frames = step.get("frames")
            if frames is None:
                # Before 4 November 2026 a shoot step with only --minutes took 60 frames.
                frames = 10 ** 6 if pol.minutes_mean_minutes and step["minutes"] else 60
            self.capture(step["label"], step["field"], "shoot", step["minutes"], step["exposure"],
                         frames, step["minutes"], deadline, {}, retakes=frames < 10 ** 6)
        self.steps.append({"label": step["label"], "planned": step["planned"], "until": step["until"],
                           "start": begin, "end": self.t, "minutes": round((self.t - begin) / 60, 1)})

    def run(self):
        for step in steps_of(self.night):
            if self.t >= self.night.end:
                self.steps.append({"label": step["label"], "planned": step["planned"], "start": self.t,
                                   "end": self.t, "minutes": 0.0})
                continue
            self.run_step(step)
        return self


def measures(run):
    """What one replay got, as numbers."""
    judged = [v for v in run.visits if v.verdicts.get("searchable") not in ("not judged", None)]
    worth_fields = {v.field for v in judged if v.verdicts.get("worth_it") == "met"}
    used = sum(v.end - v.start for v in run.visits)
    last = run.steps[-1]
    out = {
        # Constraints, pass or fail: a step that ran past its end time, and a
        # step the plan protects that started late (this plan protects none).
        "deadlines_passed": sum(1 for st in run.steps if st.get("until") and st["end"] > st["until"] + 60),
        "visits": len(run.visits),
        "searchable_visits": sum(v.verdicts.get("searchable") == "met" for v in judged),
        "fields_worth_it": len(worth_fields),
        "desired_met": sum(v.verdicts.get("desired") in ("met", "more than asked") for v in judged),
        "accepted_minutes": round(sum(v.accepted * 16 for v in run.visits) / 60, 1),
        "second_looks": sum(v.kind == "second look" for v in run.visits),
        "second_looks_put_off": run.deferred_looks,
        "idle_minutes": round(max(0.0, (run.night.end - run.night.start) - used) / 60, 1),
        "last_step_minutes": last["minutes"],
        "recorded_share": round(statistics.mean([v.recorded_share for v in run.visits]), 2) if run.visits else 0.0,
    }
    for st in run.steps:
        out[f"minutes: {st['label']}"] = st["minutes"]
    return out


def replay(night, policy, runs=50, seed=1, stress=None, costs=None):
    """`runs` replays, each with its own draw of what is modelled: each
    measure's spread, and the first run's visits for a person to read."""
    costs = costs or history.costs()
    results, first = [], None
    for i in range(runs):
        cond = Conditions(night, costs, random.Random(seed + i), stress)
        r = Run(night, policy, cond).run()
        first = first or r
        results.append(measures(r))
    keys = list(results[0])
    summary = {k: history.spread([m.get(k) for m in results]) for k in keys}
    return {"policy": policy.name, "runs": runs, "stress": stress, "measures": summary,
            "visits": [visit_dict(v) for v in first.visits]}


def visit_dict(v):
    return {"step": v.step, "field": v.field, "kind": v.kind,
            "start": datetime.fromtimestamp(v.start).strftime("%H:%M"),
            "minutes": round((v.end - v.start) / 60, 1), "asked": v.asked, "captured": v.captured,
            "accepted": v.accepted, "stacked": v.stacked,
            "depth_g": None if v.depth is None else round(v.depth, 2),
            "recorded_share": v.recorded_share, "move_recorded": v.move_recorded, **v.verdicts}


# --- checking the engine against the record ------------------------------------

def check(night, runs=50, seed=1, costs=None):
    """The as-run policy replayed, set against what the night recorded,
    session by session: does the engine give back what happened?"""
    costs = costs or history.costs()
    per = {}
    for i in range(runs):
        cond = Conditions(night, costs, random.Random(seed + i))
        r = Run(night, AS_RUN, cond, anchor=True).run()
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
                                  "depth_g": rec["depth_g"], "searchable": rec["searchable"]},
                     "replayed": {"captured": mid("captured"), "accepted": mid("accepted"),
                                  "stacked": mid("stacked"), "depth_g": mid("depth"),
                                  "runs_with_it": len(sims)},
                     "searchable_agrees": agree})
    return {"night": night.evening.isoformat(), "runs": runs, "sessions": rows, "agreement": agreement(rows)}


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
    say(f"== {result['policy']}" + (f", stress {result['stress']}" if result["stress"] else "")
        + f" ({result['runs']} runs)")
    for k, s in result["measures"].items():
        if s is None:
            continue
        say(f"  {k}: {s['median']:g} (10-90% {s['p10']:g}-{s['p90']:g})")


def say_check(result, say=print):
    say(f"The as-run policy against the record, night of {result['night']} ({result['runs']} runs):")
    say(f"  {'session':<22} {'captured':>14} {'accepted':>14} {'stacked':>14} {'depth G':>16}")
    for row in result["sessions"]:
        rec, rep = row["recorded"], row["replayed"]

        def cell(key):
            s = rep[key]
            got = "-" if s is None else f"{s['median']:g}"
            return f"{rec[key] if rec[key] is not None else '-'} / {got}"
        say(f"  {row['field'] + ' ' + row['session'][9:13]:<22} {cell('captured'):>14} {cell('accepted'):>14} "
            f"{cell('stacked'):>14} {cell('depth_g'):>16}")
    say("  (recorded / replayed median; '-' where the replay never reached that visit)")
    for row in result["sessions"]:
        if row["searchable_agrees"] is not None and row["searchable_agrees"] < 0.5:
            say(f"  searchable disagrees: {row['field']} {row['session'][9:13]} recorded {row['recorded']['searchable']}, "
                f"the replay agrees in {100 * row['searchable_agrees']:.0f}% of runs")
    a = result["agreement"]
    say(f"Agreement: captured within {100 * a['captured_error_share']:.0f}%, accepted {100 * a['accepted_error_share']:.0f}%, "
        f"stacked {100 * a['stacked_error_share']:.0f}% (median); depth {a['depth_error_mag']} mag "
        f"(worst {a['depth_error_mag_worst']}); searchable verdict as recorded in {100 * a['searchable_agrees']:.0f}% of runs")


def run(args, say=print):
    evening = date.fromisoformat(args.night)
    night = load(evening)
    costs = history.costs()
    if args.check:
        result = check(night, args.runs, costs=costs)
        say_check(result, say)
        return result
    names = args.policy.split(",")
    unknown = [n for n in names if n not in POLICIES]
    if unknown:
        raise interface.Refusal("INVALID_REQUEST", f"No policy {', '.join(unknown)}: {', '.join(POLICIES)}")
    results = [replay(night, POLICIES[n], args.runs, stress=args.stress, costs=costs) for n in names]
    for r in results:
        say_replay(r, say)
    return {"night": evening.isoformat(), "replays": results}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("night", help="the evening's date (YYYY-MM-DD)")
    ap.add_argument("--policy", default="as-run,current", help="policies to replay, comma-separated")
    ap.add_argument("--runs", type=int, default=50, help="replays of each, each with its own draw of the modelled parts")
    ap.add_argument("--stress", choices=["camera-dead", "flicker", "no-frames", "depth-wrong"],
                    help="the night made worse in one way")
    ap.add_argument("--check", action="store_true", help="the as-run policy against what was recorded")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("nightreplay", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
