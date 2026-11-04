"""Goals by purpose and the capture's one rule (docs/observing-plan-spec.md,
Phase 2): a capture keeps going until its desired accepted frames, a stall
costs time up to the cap, a rejection costs a frame up to the frame cap,
and a supernova's goal follows its reference case."""
import argparse
import json
from types import SimpleNamespace

import config
import goals
import patrol
import shoot

ON = {"plan": {"goals": True, "windows": False, "dispatch": False}}
RULE = {"accepted": 29, "cap_minutes": 12.0, "most_frames": 44}


def test_the_programmes_say_their_purpose_and_levels():
    panels = goals.of("M31-P3")
    assert panels["purpose"] == "nova-patrol" and panels["timing"] == "revisit" and panels["graded_on"] == "search"
    assert panels["minimum"] == {"stacked": 8} and panels["desired"] == {"stacked": 24}
    assert panels["worth"]["depth"] == 16.5 and panels["worth"]["quality_max"] == goals.QUALITY_MAX
    assert panels["stretch"] == {"depth": 17.5}
    assert goals.of("M33")["desired"] == {"depth": 17.5}
    assert goals.of("Tabby")["purpose"] == "lead" and goals.of("Tabby")["graded_on"] == "photometry"
    assert goals.of("M101")["purpose"] is None
    # The Phase 1 names outcome.judge reads are kept.
    assert goals.flat(panels)["searchable_frames"] == 8 and goals.flat(panels)["desired_frames"] == 24


def test_the_supernova_without_a_discovery_date_is_case_three():
    sn = goals.of("NGC3310")
    assert sn["purpose"] == "known-transient" and sn["case"] == 3 and sn["stretch"] == {}
    assert "more frames don't change this" in sn["notes"][0]


def test_a_reference_from_before_the_discovery_makes_case_one():
    kept = [{"version": 1, "sessions": ["/x/frames/NGC3310/20261001-220000"]}]
    case, why = goals.reference_case("NGC3310", {"discovered": "2026-10-20"}, kept)
    assert case == 1 and "2026-10-01" in why
    assert goals.reference_case("NGC3310", {"discovered": "2026-09-20"}, kept)[0] == 3
    assert goals.reference_case("NGC3310", {"discovered": "2026-09-20", "host_model": True}, kept)[0] == 2
    assert goals.reference_case("NGC3310", {"archive_reference": "https://example.org/x"}, [])[0] == 1


def test_desired_stacked_frames_become_accepted_ones_through_the_quality_pass():
    rule = goals.capture_rule(goals.of("M31-P3"), 8)
    assert rule == {"accepted": 29, "cap_minutes": 12.0, "most_frames": 44}


def test_a_desired_depth_becomes_the_frames_the_model_says_reach_it():
    model = {"constant": 7.85, "time": 0.651, "fwhm": -2.5, "sky": 0.5}
    prior = {"fwhm": 6.0, "sky": 18.0, "scale": 0.66, "background": 400.0}
    seconds = goals.seconds_for_depth(model, 6.0, 18.0, 17.5)
    rule = goals.capture_rule(goals.of("M33"), 30, exposure=16, model=model, prior=prior)
    assert rule["accepted"] == goals.accepted_for(max(round(seconds * goals.STACKED_SHARE / 16 + 0.5), 8))
    # Without a model the depth can't be turned into frames: the minutes hold.
    assert goals.capture_rule(goals.of("M33"), 30) is None


def test_the_rule_counts_stalls_and_rejections_apart():
    assert goals.keep_capturing(10, 12, 0, 300, RULE) == (True, None)
    assert goals.keep_capturing(29, 30, 0, 300, RULE)[1] == "desired accepted frames reached"
    # A stall costs time, not frames.
    assert goals.keep_capturing(20, 21, 0, 12 * 60, RULE)[1].startswith("time cap")
    # A rejection costs a frame, not time.
    assert goals.keep_capturing(20, 44, 0, 300, RULE)[1].startswith("frame cap")
    # Retakes stop once the desired count is taken and three in a row are lost: cloud.
    assert goals.keep_capturing(25, 29, 3, 300, RULE)[1].startswith("cloud")
    assert goals.keep_capturing(5, 20, 3, 300, RULE) == (True, None)
    assert goals.keep_capturing(0, 20, 20, 300, RULE)[1] == "cloud: every frame rejected"


def test_the_quick_depth_uses_the_fields_last_measured_stack():
    model = {"constant": 7.85, "time": 0.651, "fwhm": -2.5, "sky": 0.5}
    prior = {"scale": 0.66, "sky": 18.0, "background": 400.0}
    log = [{"accepted": True, "fwhm": 9.0, "background": 400.0}] * 20
    same = goals.quick_depth(log, 16, model, prior)
    brighter = goals.quick_depth([dict(f, background=800.0) for f in log], 16, model, prior)
    assert brighter < same and round(same - brighter, 2) == round(0.5 * 2.5 * 0.30103, 2)
    assert goals.quick_depth(log, 16, model, None) is None


def test_the_last_measured_stack_of_a_field_is_its_prior(tmp_path):
    folder = tmp_path / "frames" / "M33" / "20261104-011700"
    folder.mkdir(parents=True)
    (folder / "depth.json").write_text(json.dumps({"scale_arcsec_per_px": 0.66, "sky_mag_per_arcsec2": 18.2,
                                                   "fwhm_arcsec": 5.9}))
    (folder / "frames.jsonl").write_text(json.dumps({"accepted": True, "background": 420.0}) + "\n")
    assert goals.prior_for("M33", tmp_path) == {"scale": 0.66, "sky": 18.2, "fwhm": 5.9, "background": 420.0,
                                               "from": "20261104-011700"}
    assert goals.prior_for("M31", tmp_path) is None


def test_the_phases_are_off_unless_switched_on():
    assert not goals.enabled("goals")                # the tests read the example's: all off
    assert goals.enabled("goals", ON) and not goals.enabled("windows", ON)
    assert config.example()["plan"] == {"goals": False, "windows": False, "dispatch": False, "follow_up_share": 0.25}


def test_a_patrol_asks_for_accepted_frames_only_with_goals_on(monkeypatch):
    p = {"target": "M31-P3", "exposure": 16, "gain": 1500, "minutes": 8, "mosaic": "M31", "grid": "4x2",
         "goals": {"searchable_frames": 8, "desired_frames": 24}}
    _, off = patrol.steps(p)
    assert "--frames" in off and "--accepted" not in off
    monkeypatch.setattr(goals, "enabled", lambda phase, cfg=None: phase == "goals")
    import windows
    monkeypatch.setattr(windows, "costs", lambda: {"depth_model": None})
    _, on = patrol.steps(p)
    assert on[on.index("--accepted") + 1] == "29" and on[on.index("--most") + 1] == "44"
    assert on[on.index("--minutes") + 1] == "12" and "--frames" not in on


def frame(ok, measured=True):
    return {"accepted": ok, "flux": 1.0 if measured else None}


def test_a_run_given_accepted_frames_stops_on_them_and_says_why(tmp_path):
    session = SimpleNamespace(folder=tmp_path, log=[frame(True)] * 28)
    args = argparse.Namespace(accepted=29, minutes=12.0, most=None)
    assert shoot.goal_reached(session, 28, 300, args) == (True, None)
    # A frame set aside while the live stack was behind counts with the accepted.
    session.log.append(frame(False, measured=False))
    go, why = shoot.goal_reached(session, 29, 300, args)
    assert not go and why == "desired accepted frames reached"
    kept = json.loads((tmp_path / "capture.json").read_text())
    assert kept["stopped_by"] == why and kept["rule"]["most_frames"] == 44 and kept["rejected"] == 0


def test_a_run_with_rejections_runs_to_its_frame_cap(tmp_path):
    session = SimpleNamespace(folder=tmp_path, log=[frame(True), frame(False)] * 10)
    args = argparse.Namespace(accepted=29, minutes=12.0, most=20)
    go, why = shoot.goal_reached(session, 20, 300, args)
    assert not go and why.startswith("frame cap")
    assert json.loads((tmp_path / "capture.json").read_text())["rejected"] == 10
