"""Replaying a night under a policy: a small made-up night with its plan,
read back by the engine. What is recorded is used as recorded; the rest is
modelled and said so; the current policy is the running code's own rules;
a policy that keeps a step to its time leaves the next its own; a
protected step is judged by its first frame."""
import json
import random
from datetime import date, datetime

import pytest

import config
import nightreplay

EVENING = date(2026, 11, 3)
COSTS = {
    "before": "2026-11-03", "nights": 5,
    "rejections": {"share": {"trailed": 0.0}},
    "long_gaps": {"per_hour": {"median": 0.0}, "seconds_each": {"median": 60.0}},
    "frame_gap_s_by_exposure": {"16": {"median": 5.0, "p10": 5.0, "p90": 5.0, "n": 1}},
    "frame_gap_s": {"median": 5.0, "p10": 5.0, "p90": 5.0, "n": 1},
    "move_s": {"median": 120.0, "p10": 120.0, "p90": 120.0, "n": 1},
    "stacked_share": {"median": 0.85, "p10": 0.8, "p90": 1.0, "n": 1},
    "depth_model": {"constant": 7.85, "time": 0.651, "fwhm": -2.5, "sky": 0.5},
    "depth_model_error": {"median": 0.0, "p10": -0.1, "p90": 0.1, "n": 1},
    "search_outcomes": {"searched": 20, "subtraction": 0},
}
SUBTRACTION = ("Stopped at vet: the subtraction left as many dark leftovers as bright ones (7 fading, 4 brightening): "
               "it did not match tonight's stack to the reference; nothing reported")


def at(hour, minute=0):
    day = 3 if hour >= 12 else 4
    return datetime(2026, 11, day, hour, minute).timestamp()


def session(data, field, start, n, gap=21.0, cloud=(), flux=100.0, depth=None, stopped=None, exposure=16.0):
    """A session of n frames from `start`; frames whose index is in `cloud`
    were lost to cloud; `stopped`, the words its search stopped with."""
    name = datetime.fromtimestamp(start).strftime("%Y%m%d-%H%M%S")
    folder = data / "frames" / field / name
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({"frames": n, "exposure": exposure}))
    lines = []
    for i in range(n):
        lost = i in cloud
        lines.append(json.dumps({"index": i + 1, "taken": start + i * gap, "accepted": not lost,
                                 "reason": "too few stars (cloud?)" if lost else "", "flux": 5.0 if lost else flux}))
    (folder / "frames.jsonl").write_text("\n".join(lines) + "\n")
    (folder / "restack.json").write_text(json.dumps({"summary": {"stacked": int((n - len(cloud)) * 0.85)}}))
    if depth:
        (folder / "depth.json").write_text(json.dumps({"fwhm_arcsec": 6.4, "sky_mag_per_arcsec2": 17.8,
                                                       "exposure_s": exposure * n,
                                                       "completeness": {"all": {"mag_50": depth}}}))
    if stopped:
        (folder / "patrol.json").write_text(json.dumps({"summary": [f"Stopped at vet: {stopped}"]}))
    return folder


def plan(data, steps):
    folder = data / "cache" / "schedules"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{EVENING.isoformat()}.json").write_text(json.dumps({"steps": steps}))


PANELS = {"label": "M31 panels", "minutes": 45, "until": None, "started": at(3, 14), "finished": at(4, 53),
          "command": ["./patrol.py", "m31-panels"]}
SN = {"label": "SN", "minutes": 90, "until": "05:25", "started": at(4, 53), "finished": at(5, 25),
      "command": ["./shoot.py", "NGC 3310", "--minutes", "90", "--exposure", "16", "--gain", "1500"]}


@pytest.fixture
def night(tmp_path, monkeypatch):
    """Panels from 03:14 for a 45-minute step, then a supernova to 05:25.
    Panel 4's search failed its subtraction; every panel was imaged before."""
    monkeypatch.setattr(config, "DATA", tmp_path)
    plan(tmp_path, [PANELS, SN])
    t = at(3, 15)
    for n in (1, 2, 3, 4, 5, 6, 7, 8):
        session(tmp_path, f"M31-P{n}", t, 16, depth=16.8, stopped=SUBTRACTION if n == 4 else None)
        session(tmp_path, f"M31-P{n}", datetime(2026, 10, 20, 22, n).timestamp(), 16)
        t += 16 * 21 + 120
    session(tmp_path, "NGC3310", at(4, 54), 75, cloud=set(range(10)))
    return nightreplay.load(EVENING, tmp_path)


def test_a_night_is_read_from_its_plan_and_its_sessions(night):
    assert [s["field"] for s in night.sessions][:2] == ["M31-P1", "M31-P2"]
    # Seven moves between the eight panels; the long wait before the supernova is not a move.
    assert len(night.frames) == 8 * 16 + 75 and len(night.moves) == 7
    assert night.start == at(3, 14)
    assert "M31-P4" in night.seen_before
    assert night.searches[datetime.fromtimestamp(at(3, 15) + 3 * (16 * 21 + 120)).strftime("%Y%m%d-%H%M%S")] \
        == "subtraction"


def test_a_night_without_its_plan_is_refused(tmp_path, monkeypatch):
    import interface
    monkeypatch.setattr(config, "DATA", tmp_path)
    with pytest.raises(interface.Refusal):
        nightreplay.load(EVENING, tmp_path)


def test_the_sky_is_recorded_on_the_same_field_and_borrowed_elsewhere(night):
    cond = nightreplay.Conditions(night, COSTS, random.Random(1))
    p, same = cond.cloud(at(4, 55), "NGC3310")
    assert p > 0.5 and same                       # the supernova's cloudy start, on its own field
    p, same = cond.cloud(at(3, 16), "M33")
    assert p == 0.0 and not same                  # M31's clear sky, borrowed for a field not taken then
    # Only accepted frames lend their light to an accepted frame.
    assert cond.transparency(at(4, 55), "NGC3310") > 0.5


def test_keeping_the_panels_to_their_step_gives_the_supernova_its_time(night):
    as_run = nightreplay.replay(night, nightreplay.AsRun, runs=3, costs=COSTS)["measures"]
    current = nightreplay.replay(night, nightreplay.Current, runs=3, costs=COSTS)["measures"]
    # Eight 5-minute panels as run; 45 minutes hold three of the 12.5 the current code plans.
    assert as_run["visits"]["median"] == 9 and current["visits"]["median"] == 4
    assert current["minutes: M31 panels"]["median"] <= 45
    # The supernova: 60 frames as it was asked then, its minutes now.
    assert as_run["minutes: SN"]["median"] < 30 < current["minutes: SN"]["median"]
    assert current["ends_overrun"]["median"] == 0


def test_the_current_policy_runs_on_the_running_code_s_own_rules(night, monkeypatch):
    """Not a copy: change a rule in patrol, schedule or shoot and the replay
    changes with it (the Phase 5 audit, 4 November 2026)."""
    import patrol
    import schedule
    import shoot
    called = set()
    for module, name in ((schedule, "prepared"), (patrol, "fit"), (patrol, "room"), (patrol, "shoot_minutes"),
                         (patrol, "frames_for"), (shoot, "stop_for"), (shoot, "frames_asked")):
        real = getattr(module, name)

        def spy(*a, _real=real, _name=name, **k):
            called.add(_name)
            return _real(*a, **k)
        monkeypatch.setattr(module, name, spy)
    nightreplay.replay(night, nightreplay.Current, runs=1, costs=COSTS)
    assert called == {"prepared", "fit", "room", "shoot_minutes", "frames_for", "stop_for", "frames_asked"}
    before = nightreplay.replay(night, nightreplay.Current, runs=1, costs=COSTS)["measures"]["visits"]["median"]
    monkeypatch.setattr(patrol, "STALL_SHARE", 0.0)      # panels planned without room for stalls
    after = nightreplay.replay(night, nightreplay.Current, runs=1, costs=COSTS)["measures"]["visits"]["median"]
    assert after > before


def test_the_as_run_policy_is_labelled_a_reconstruction(night):
    assert nightreplay.replay(night, nightreplay.AsRun, runs=1, costs=COSTS)["reconstructed"]
    assert not nightreplay.replay(night, nightreplay.Current, runs=1, costs=COSTS)["reconstructed"]


def test_a_recorded_failed_subtraction_stays_failed(night):
    visits = nightreplay.replay(night, nightreplay.AsRun, runs=1, costs=COSTS)["visits"]
    p4 = next(v for v in visits if v["field"] == "M31-P4")
    assert p4["search"] == "subtraction" and p4["search_source"] == "recorded" and p4["searchable"] == "short"
    p2 = next(v for v in visits if v["field"] == "M31-P2")
    assert p2["search"] == "searched" and p2["searchable"] == "met"


def test_an_unrecorded_search_fails_at_the_earlier_nights_rate(night):
    """A visit the record has no answer for: a field never imaged before has
    no reference, and the rest fail their subtraction as often as before."""
    cond = nightreplay.Conditions(night, dict(COSTS, search_outcomes={"searched": 0, "subtraction": 40}),
                                  random.Random(1))
    assert cond.search("M31-P2", None) == ("subtraction", "modelled")
    assert cond.search("M33", None) == ("no reference", "modelled")
    assert cond.search("M31-P2", "searched") == ("searched", "recorded")


def test_depth_learns_only_from_stacks_measured_before_it(night):
    """Chronological: at 03:20 none of the night's stacks has been measured,
    so the model's own error from earlier nights stands; leave-one-out would
    use the panels measured later that night."""
    early = at(3, 20)
    chrono = nightreplay.Conditions(night, COSTS, random.Random(1)).depth(early, 16 * 16)
    later = nightreplay.Conditions(night, COSTS, random.Random(1), calibration="leave-one-out").depth(early, 16 * 16)
    import depth
    model = depth.predict(COSTS["depth_model"], 6.4, 17.8, 16 * 16)
    assert abs(chrono - model) < 0.3                # no same-night offset yet
    assert abs(later - chrono) > 0.3                # the later panels' offset, which 03:20 can't know


def test_accepted_minutes_use_each_visit_s_own_exposure(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    plan(tmp_path, [{"label": "long", "minutes": 20, "until": None, "started": at(1, 0), "finished": at(1, 20),
                     "command": ["./shoot.py", "M33", "--frames", "20", "--exposure", "30"]}])
    session(tmp_path, "M33", at(1, 1), 20, gap=35.0, exposure=30.0)
    n = nightreplay.load(EVENING, tmp_path)
    m = nightreplay.replay(n, nightreplay.Current, runs=1, costs=COSTS)["measures"]
    assert m["accepted_minutes"]["median"] == 10.0     # 20 frames of 30 s, not of 16


def test_time_is_said_by_what_it_went_on(night):
    m = nightreplay.replay(night, nightreplay.Current, runs=1, costs=COSTS)["measures"]
    parts = [k for k in m if k.startswith("time: ")]
    assert {"time: accepted", "time: moves", "time: stalls", "time: unused",
            "time: waiting for a timed step"} <= set(parts)
    assert m["time: moves"]["median"] > 0 and m["time: unused"]["median"] >= 0


def test_a_protected_step_is_judged_by_its_first_frame(night):
    """At 04:30 the 45-minute panels step is long over in the current
    policy, so the runner waits for 04:30 and then makes the GoTo: the first
    frame comes a move after the time, which is late. Under the as-run
    rules the panels overrun into it and it is later still."""
    current = nightreplay.replay(night, nightreplay.Current, runs=3, costs=COSTS, protect="04:30")["measures"]
    assert current["protected_starts_missed"]["median"] == 1
    assert 60 < current["protected_start_late_s"]["median"] <= 200     # the 120 s GoTo after the wait
    assert current["time: waiting for a timed step"]["median"] > 0
    as_run = nightreplay.replay(night, nightreplay.AsRun, runs=3, costs=COSTS, protect="03:40")["measures"]
    assert as_run["protected_start_late_s"]["median"] > 20 * 60


def test_the_check_reports_acquisition_and_the_whole_night_apart(night):
    result = nightreplay.check(night, runs=5, costs=COSTS)
    p2 = next(r for r in result["acquisition"]["sessions"] if r["field"] == "M31-P2")
    assert p2["recorded"]["captured"] == 16 and abs(p2["replayed"]["captured"]["median"] - 16) <= 1
    assert result["acquisition"]["agreement"]["captured_error_share"] <= 0.1
    whole = result["whole_night"]
    assert [s["label"] for s in whole["steps"]] == ["M31 panels", "SN"]
    assert whole["agreement"]["visits_in_recorded_order_median"] >= 8
    assert not result["independent"]         # 3 November is the night the engine was built on


def test_each_visit_says_how_much_of_its_sky_was_recorded(night):
    visits = nightreplay.replay(night, nightreplay.Current, runs=1, costs=COSTS)["visits"]
    assert all(0.0 <= v["recorded_share"] <= 1.0 for v in visits)
    assert visits[0]["field"] == "M31-P1" and visits[0]["recorded_share"] > 0.5


def test_a_stressed_night_still_ends(night):
    for stress in ("camera-dead", "flicker", "no-frames", "depth-wrong"):
        m = nightreplay.replay(night, nightreplay.Current, runs=2, stress=stress, costs=COSTS)["measures"]
        assert m["ends_past_backstop"]["median"] == 0, stress
        # A camera that hangs mid-step is ended by the backstop, past its time, and said so.
        assert m["ends_overrun"]["median"] == (1 if stress == "camera-dead" else 0), stress
    dead = nightreplay.replay(night, nightreplay.Current, runs=2, stress="no-frames", costs=COSTS)["measures"]
    assert dead["accepted_minutes"]["median"] == 0


def test_with_goals_a_panel_keeps_going_to_its_desired_frames_and_says_why_it_stopped(night):
    visits = nightreplay.replay(night, nightreplay.Goals, runs=1, costs=COSTS)["visits"]
    panel = next(v for v in visits if v["kind"] == "panel")
    # 24 desired stacked frames are 29 accepted (goals.capture_rule), stopped by shoot.goal_stop.
    assert panel["asked"] == 29
    assert panel["stopped_by"] in ("desired accepted frames reached", "time cap reached (stalls and slow frames)",
                                   "frame cap reached (rejections)", "the step's end")
    assert "stall_minutes" in panel and "shortfall" in panel
    # Today's code asks for the frames its minutes allow.
    current = nightreplay.replay(night, nightreplay.Current, runs=1, costs=COSTS)["visits"]
    assert next(v for v in current if v["kind"] == "panel")["asked"] != 29


def test_a_shortfall_says_its_cause():
    v = nightreplay.Visit("panels", "M31-P3", "panel", captured=12, accepted=7, stacked=6, cloud=5, stall_s=150,
                          stopped_by="time cap reached (stalls and slow frames)", verdicts={"searchable": "short"})
    said = nightreplay.shortfall(v)
    assert "camera stalls 2.5 min" in said and "cloud 5 frames" in said and "time cap" in said
    v.verdicts = {"searchable": "met"}
    assert nightreplay.shortfall(v) is None


def test_a_protected_step_starts_on_time_only_with_windows_on(night):
    """Today's runner waits for 04:30 and then makes the GoTo, so its first
    frame is a move late; with windows the setup is reserved before it."""
    late = nightreplay.replay(night, nightreplay.Goals, runs=3, costs=COSTS, protect="04:30")["measures"]
    kept = nightreplay.replay(night, nightreplay.Windows, runs=3, costs=COSTS, protect="04:30")["measures"]
    assert late["protected_starts_missed"]["median"] == 1
    assert kept["protected_starts_missed"]["median"] == 0 and kept["protected_start_late_s"]["median"] == 0


def test_the_backstop_does_not_run_into_a_protected_start():
    """A flexible step ended by a cutoff is told to end BACKSTOP_S early, so
    its hard stop falls on the cutoff (the replay of 3 November found
    protected starts 209 s late by it)."""
    import schedule
    step = {"label": "panels", "minutes": 45, "command": ["./patrol.py", "m31-panels"]}
    command, left = schedule.prepared(step, 1000.0, "M31-P1", cut=1000.0 + 1800)
    assert left == 1800 and command[:3] == ["timeout", "--signal=INT", "1800"]
    assert command[command.index("--budget") + 1] == f"{(1800 - schedule.BACKSTOP_S) / 60:.1f}"
    # A step's own end time keeps the backstop after it, as before.
    own, left = schedule.prepared(dict(step, until="2026-11-04 03:00"), datetime(2026, 11, 4, 2, 30).timestamp(),
                                  "M31-P1")
    assert left == 1800 + schedule.BACKSTOP_S


def test_dispatch_and_windows_keep_every_stress_night_safe(night):
    for policy in (nightreplay.Windows, nightreplay.Dispatch):
        for stress in ("camera-dead", "flicker", "no-frames", "depth-wrong"):
            m = nightreplay.replay(night, policy, runs=2, stress=stress, costs=COSTS)["measures"]
            assert m["ends_past_backstop"]["median"] == 0 and m["protected_starts_missed"]["median"] == 0, stress
        protected = nightreplay.replay(night, policy, runs=2, costs=COSTS, protect="04:30")["measures"]
        assert protected["protected_starts_missed"]["median"] == 0


def test_the_policies_are_named_for_their_phases():
    assert set(nightreplay.POLICIES) == {"as-run", "current", "goals", "windows", "dispatch"}
    assert issubclass(nightreplay.Dispatch, nightreplay.Windows) and issubclass(nightreplay.Windows,
                                                                                  nightreplay.Goals)
    assert nightreplay.Windows.chooses and not nightreplay.Goals.chooses
